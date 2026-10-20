package suse_direct

import (
	"context"
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
	// "goauthentik.io/internal/outpost/ldap/constants"
	// "goauthentik.io/internal/outpost/ldap/group"
	"goauthentik.io/internal/outpost/ldap/metrics"
	"goauthentik.io/internal/outpost/ldap/search"
	"goauthentik.io/internal/outpost/ldap/server"
	"goauthentik.io/internal/outpost/ldap/utils"

	directsearch "goauthentik.io/internal/outpost/ldap/search/direct"
)

type DirectSearcher struct {
	si  server.LDAPServerInstance
	ds  *directsearch.DirectSearcher
	log *log.Entry
}

func NewDirectSearcher(si server.LDAPServerInstance) *DirectSearcher {
	ds := &DirectSearcher{
		si:  si,
		ds:  directsearch.NewDirectSearcher(si),
		log: log.WithField("logger", "authentik.outpost.ldap.searcher.direct"),
	}

	return ds
}

func (ds *DirectSearcher) SearchBase(req *search.Request) (ldap.ServerSearchResult, error) {
	return ds.ds.SearchBase(req)
}

func (ds *DirectSearcher) SearchSubschema(req *search.Request) (ldap.ServerSearchResult, error) {
	return ds.ds.SearchSubschema(req)
}

func (ds *DirectSearcher) Search(req *search.Request) (ldap.ServerSearchResult, error) {
	accsp := sentry.StartSpan(req.Context(), "authentik.providers.ldap.search.check_access")
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

	entries := make([]*ldap.Entry, 0)

	if req.Scope != ldap.ScopeSingleLevel && req.Scope != ldap.ScopeWholeSubtree {
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ds.si.GetOutpostName(),
			"type":         "search",
			"reason":       "disallowed_filter",
			"app":          ds.si.GetAppSlug(),
		}).Inc()

		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultOperationsError}, fmt.Errorf("Search Error: Scope not allowed")
	}

	wantsUsers, _ := utils.HasSuffixWithMore(req.BaseDN, ds.si.GetBaseUserDN())
	if !wantsUsers {
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ds.si.GetOutpostName(),
			"type":         "search",
			"reason":       "disallowed_fearch",
			"app":          ds.si.GetAppSlug(),
		}).Inc()

		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultOperationsError}, fmt.Errorf("Search Error: Asking for non-users in the base scope")
	}

	client := api.NewAPIClient(ds.si.GetAPIClient().GetConfig())
	client.GetConfig().AddDefaultHeader("X-authentik-outpost-ldap-query", req.Filter)

	userRequest := ds.si.GetAPIClient().CoreAPI.CoreUsersList(context.TODO()).IncludeGroups(true).IncludeRoles(false)
	userRequest, skip := parseFilterForUser(userRequest, parsedFilter, false)
	if skip {
		return ldap.ServerSearchResult{Entries: entries, Referrals: []string{}, Controls: []ldap.Control{}, ResultCode: ldap.LDAPResultSuccess}, nil
	}

	userIterator := ak.PaginatorIterator(userRequest, ak.PaginatorOptions{
		PageSize: 1,
		Logger:   ds.log,
	})

	for user, err := range userIterator {
		if err != nil {
			// Here we can't know without de-gutting the err object and reading that
			// `err.model.AdditionalProperties[*] is present to discern between
			// a _real_ error or a group-not found error.
			// Returning empty result and logging a message instead.
			switch apiErr := err.(type) {
			case *api.GenericOpenAPIError:
				req.Log().WithError(err).WithField("error-body", string(apiErr.Body())).Info("API Validation error from upstream")
			default:
				req.Log().WithError(err).Info("Error querying upstream")
			}
			return ldap.ServerSearchResult{Entries: entries, Referrals: []string{}, Controls: []ldap.Control{}, ResultCode: ldap.LDAPResultSuccess}, nil
		}

		dn := ds.GetUserDN(user.Username)
		entry := userEntry(dn, user, ds.si.GetBaseDN())
		entries = append(entries, entry)
		break
	}

	return ldap.ServerSearchResult{Entries: entries, Referrals: []string{}, Controls: []ldap.Control{}, ResultCode: ldap.LDAPResultSuccess}, nil
}

func (ds *DirectSearcher) GetUsername(dn string) (string, error) {
	if !utils.HasSuffixNoCase(dn, ds.si.GetBaseDN()) {
		return "", errors.New("invalid base DN")
	}
	dns, err := goldap.ParseDN(dn)
	if err != nil {
		return "", err
	}
	for _, part := range dns.RDNs {
		for _, attribute := range part.Attributes {
			if strings.ToLower(attribute.Type) == "uid" || strings.ToLower(attribute.Type) == "cn" {
				return attribute.Value, nil
			}
		}
	}
	return "", errors.New("failed to find username from request dn")
}

// Important note: this must match the logic in internal/outpost/ldap/bind.go:40
// and
// internal/outpost/ldap/bind/direct/direct.go
func (ds *DirectSearcher) GetUserDN(user string) string {
	return fmt.Sprintf("uid=%s,%s", user, ds.si.GetBaseUserDN())
}
