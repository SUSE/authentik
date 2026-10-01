package suse_directpksearch

import (
	"errors"
	"fmt"
	"strings"

	goldap "github.com/go-ldap/ldap/v3"
	log "github.com/sirupsen/logrus"

	"beryju.io/ldap"
	"github.com/getsentry/sentry-go"
	"github.com/prometheus/client_golang/prometheus"
	"goauthentik.io/api/v3"
	"goauthentik.io/internal/outpost/ak"
	"goauthentik.io/internal/outpost/ldap/constants"

	"goauthentik.io/internal/outpost/ldap/metrics"
	"goauthentik.io/internal/outpost/ldap/search"
	"goauthentik.io/internal/outpost/ldap/server"
	"goauthentik.io/internal/outpost/ldap/utils"

	directsearch "goauthentik.io/internal/outpost/ldap/search/direct"
)

type DirectPKSearcher struct {
	si  server.LDAPServerInstance
	ds  *directsearch.DirectSearcher
	log *log.Entry
}

func NewDirectPKSearcher(si server.LDAPServerInstance) *DirectPKSearcher {
	ds := &DirectPKSearcher{
		si:  si,
		ds:  directsearch.NewDirectSearcher(si),
		log: log.WithField("logger", "authentik.outpost.ldap.searcher.suse_direct"),
	}
	return ds
}

func (ds *DirectPKSearcher) SearchBase(req *search.Request) (ldap.ServerSearchResult, error) {
	return ds.ds.SearchBase(req)
}

func (ds *DirectPKSearcher) SearchSubschema(req *search.Request) (ldap.ServerSearchResult, error) {
	return ds.ds.SearchSubschema(req)
}

func (ds *DirectPKSearcher) Search(req *search.Request) (ldap.ServerSearchResult, error) {
	accsp := sentry.StartSpan(req.Context(), "authentik.outpost.ldap.searcher.suse_direct")
	baseDN := ds.si.GetBaseDN()

	if len(req.BindDN) < 1 {
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ds.si.GetOutpostName(),
			"type":         "search",
			"reason":       "empty_bind_dn",
			"app":          ds.si.GetAppSlug(),
		}).Inc()
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultInsufficientAccessRights}, fmt.Errorf("Search Error: Anonymous BindDN not allowed %s", req.BindDN)
	}
	if !utils.HasSuffixNoCase(req.BindDN, ","+baseDN) {
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ds.si.GetOutpostName(),
			"type":         "search",
			"reason":       "invalid_bind_dn",
			"app":          ds.si.GetAppSlug(),
		}).Inc()
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultInsufficientAccessRights}, fmt.Errorf("Search Error: BindDN %s not in our BaseDN %s", req.BindDN, ds.si.GetBaseDN())
	}

	flags := ds.si.GetFlags(req.BindDN)
	if flags == nil {
		req.Log().Debug("User info not cached")
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ds.si.GetOutpostName(),
			"type":         "search",
			"reason":       "user_info_not_cached",
			"app":          ds.si.GetAppSlug(),
		}).Inc()
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultInsufficientAccessRights}, errors.New("access denied")
	}
	accsp.Finish()

	parsedFilter, err := ldap.CompileFilter(req.Filter)
	if err != nil {
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ds.si.GetOutpostName(),
			"type":         "search",
			"reason":       "filter_parse_fail",
			"app":          ds.si.GetAppSlug(),
		}).Inc()
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultOperationsError}, fmt.Errorf("Search Error: error parsing filter: %s", req.Filter)
	}

	if strings.Contains(req.Filter, "*") {
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ds.si.GetOutpostName(),
			"type":         "search",
			"reason":       "filter_star_not_allowed",
			"app":          ds.si.GetAppSlug(),
		}).Inc()
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultOperationsError}, fmt.Errorf("Search Error: wildcards are not allowed: %s", req.Filter)
	}

	// this mode won't support groups... at least not yet
	wantsUsers, wantsSpecificUser := utils.HasSuffixWithMore(req.BaseDN, ds.si.GetBaseUserDN())
	if !wantsUsers {
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ds.si.GetOutpostName(),
			"type":         "search",
			"reason":       "disallowed_fearch",
			"app":          ds.si.GetAppSlug(),
		}).Inc()

		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultOperationsError}, fmt.Errorf("Search Error: Asking for non-users in the base scope")
	}

	entries := make([]*ldap.Entry, 0)

	scope := req.Scope

	if scope >= 0 && strings.EqualFold(req.BaseDN, baseDN) {
		if utils.IncludeObjectClass(req.FilterObjectClass, constants.GetDomainOCs()) {
			rootEntries, _ := ds.ds.SearchBase(req)
			// Since `SearchBase` returns entries for the root DN, we need to go through the
			// entries and update the base DN
			for _, e := range rootEntries.Entries {
				e.DN = ds.si.GetBaseDN()
				entries = append(entries, e)
			}
		}

		scope -= 1 // Bring it from WholeSubtree to SingleLevel and so on
	}

	username := ""

	if wantsSpecificUser {
		dnUsername, err := ds.GetUsername(req.BaseDN)
		if err != nil {
			metrics.RequestsRejected.With(prometheus.Labels{
				"outpost_name": ds.si.GetOutpostName(),
				"type":         "search",
				"reason":       "disallowed_search",
				"app":          ds.si.GetAppSlug(),
			}).Inc()

			return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultOperationsError}, fmt.Errorf("Search Error: Asking for non-users pk field")
		}

		username = dnUsername
	}

	client := api.NewAPIClient(ds.si.GetAPIClient().GetConfig())

	// TODO: figure if group names here make sense

	userRequest, skip := utils.SUSE_ParseFilterForUser(ds.si.GetAPIController(), client.CoreAPI.CoreUsersList(req.Context()).IncludeGroups(false).IncludeRoles(false), parsedFilter, false)
	if skip {
		return ldap.ServerSearchResult{Entries: entries, Referrals: []string{}, Controls: []ldap.Control{}, ResultCode: ldap.LDAPResultSuccess}, nil
	}

	if username != "" {
		userRequest = userRequest.Username(username)
	}

	userIterator := ak.PaginatorIterator(userRequest, ak.PaginatorOptions{
		PageSize: 1,
		Logger:   ds.log,
	})

	if scope >= 0 && (wantsUsers || wantsSpecificUser) {
		if !wantsSpecificUser && utils.IncludeObjectClass(req.FilterObjectClass, constants.GetContainerOCs()) {
			entries = append(entries, utils.GetContainerEntry(req.FilterObjectClass, ds.si.GetBaseUserDN(), constants.OUUsers))
			scope -= 1
		}

		if scope >= 0 && utils.IncludeObjectClass(req.FilterObjectClass, constants.GetUserOCs()) {
			for user, err := range userIterator {
				if err != nil {
					return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultOperationsError}, fmt.Errorf("Error requesting from usptream.")
				}

				entry := ds.si.UserEntry(user)
				if strings.EqualFold(req.BaseDN, entry.DN) || !wantsSpecificUser {
					entries = append(entries, entry)
				}
			}
		}

		scope += 1 // Return the scope to what it was before we descended
	}

	return ldap.ServerSearchResult{Entries: entries, Referrals: []string{}, Controls: []ldap.Control{}, ResultCode: ldap.LDAPResultSuccess}, nil
}

func (ds *DirectPKSearcher) GetUsername(dn string) (string, error) {
	if !utils.HasSuffixNoCase(dn, ds.si.GetBaseDN()) {
		return "", errors.New("invalid base DN")
	}
	dns, err := goldap.ParseDN(dn)
	if err != nil {
		return "", err
	}
	for _, part := range dns.RDNs {
		for _, attribute := range part.Attributes {
			if strings.ToLower(attribute.Type) == "uid" {
				return attribute.Value, nil
			}
		}
	}
	return "", errors.New("failed to find uid")
}
