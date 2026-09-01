package suse_memory

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"beryju.io/ldap"
	"github.com/getsentry/sentry-go"
	"github.com/prometheus/client_golang/prometheus"
	log "github.com/sirupsen/logrus"
	"goauthentik.io/api/v3"
	"goauthentik.io/internal/outpost/ak"

	"goauthentik.io/internal/outpost/ldap/constants"
	"goauthentik.io/internal/outpost/ldap/flags"
	"goauthentik.io/internal/outpost/ldap/group"
	"goauthentik.io/internal/outpost/ldap/metrics"
	"goauthentik.io/internal/outpost/ldap/search"
	"goauthentik.io/internal/outpost/ldap/search/direct"
	"goauthentik.io/internal/outpost/ldap/server"
	"goauthentik.io/internal/outpost/ldap/utils"
	"goauthentik.io/internal/suse"
)

type MemorySearcher struct {
	si  server.LDAPServerInstance
	log *log.Entry
	ds  *direct.DirectSearcher
}

// TODO: somewhere in the future, we'll find out how to forward SIGTERM from the
// entrypoint all the way here, and when that comes, this context can be fed
// from the signal instead to abort request when SIGTERM is received.
var globalCtx context.Context = context.TODO()
var sentinel struct{}

var globalUserCache suse.MutexMap[int32, api.User] = suse.NewMutexMap[int32, api.User]()
var globalGroupCache suse.MutexMap[string, api.Group] = suse.NewMutexMap[string, api.Group]()
var syncInProgress = false
var lastSync *time.Time

func NewMemorySearcher(si server.LDAPServerInstance, existing search.Searcher) *MemorySearcher {
	ms := &MemorySearcher{
		si: si,
		log: log.WithFields(log.Fields{
			"logger":      "ldap.searcher.suse_memory",
			"app":         si.GetAppSlug(),
			"provider-pk": si.GetProviderID(),
		}),
		ds: direct.NewDirectSearcher(si),
	}
	if existing != nil {
		if ems, ok := existing.(*MemorySearcher); ok {
			ems.si = si
			ems.fetch()
			ems.log.Debug("re-initialised memory searcher")
			return ems
		}
	}
	ms.fetch()
	ms.log.Debug("initialised memory searcher")
	return ms
}

func (ms *MemorySearcher) enrichUserGroupsFromCache(user *api.User) {
	// This does copy objects, but hey, we're copying less data, and only from
	// the data we got available.
	user.GroupsObj = make([]api.PartialGroup, len(user.Groups))
	used := 0

	for _, groupUuid := range user.Groups {
		if g, ok := suse.GetFromMapping(globalGroupCache, groupUuid); ok {
			user.GroupsObj[used] = *api.NewPartialGroup(g.Pk, g.NumPk, g.Name)
			used = used + 1
		}
	}
	user.GroupsObj = user.GroupsObj[0:used]
}

func (ms *MemorySearcher) enrichGroupUsersFromCache(group *api.Group) {
	// This does copy objects, but hey, we're copying less data, and only
	// from the data we got available.
	group.UsersObj = make([]api.PartialUser, len(group.Users))
	used := 0

	for _, userPk := range group.Users {
		if u, ok := suse.GetFromMapping(globalUserCache, userPk); ok {
			group.UsersObj[used] = *api.NewPartialUser(u.Pk, u.Username, u.Name, u.Uid)
			used = used + 1
		}
	}
	group.UsersObj = group.UsersObj[0:used]
}

func (ms *MemorySearcher) buildUserAPIRequest(pathFilter, rawGroupNames string) (*api.ApiCoreUsersListRequest, error) {
	if pathFilter == "" && rawGroupNames == "" {
		return nil, fmt.Errorf("Neither SUSE_USER_FILTER_PATH, nor SUSE_USER_FILTER_GROUP_NAMES was provided.")
	}

	userRequest := ms.si.GetAPIClient().CoreAPI.CoreUsersList(globalCtx).IncludeGroups(false).IncludeRoles(false)
	if pathFilter != "" {
		userRequest = userRequest.Path(pathFilter)
		ms.log.WithField("path", pathFilter).Debug("Applying user path filter")
	}

	if rawGroupNames != "" {
		groupNames := strings.Split(rawGroupNames, ",")
		userRequest = userRequest.GroupsByName(groupNames)
		ms.log.WithField("group-names", groupNames).Debug("Applying user group names filter")
	}

	return &userRequest, nil
}

func (ms *MemorySearcher) buildGroupRequests(rawGroupNames string) ([]api.ApiCoreGroupsListRequest, error) {
	if rawGroupNames == "" {
		return nil, fmt.Errorf("SUSE_GROUP_FILTER_NAMES was not provided.")
	}

	groupRequests := []api.ApiCoreGroupsListRequest{}
	groupNames := []string{}

	for _, name := range strings.Split(rawGroupNames, ",") {
		name = strings.TrimSpace(name)
		if name != "" {
			groupNames = append(groupNames, name)
		}
	}

	if len(groupNames) == 0 {
		return nil, fmt.Errorf("SUSE_GROUP_FILTER_NAMES is effectively empty.")
	}

	for _, groupName := range groupNames {
		req := ms.si.GetAPIClient().CoreAPI.CoreGroupsList(globalCtx).IncludeUsers(false).IncludeChildren(false).IncludeParents(false).Name(groupName)
		groupRequests = append(groupRequests, req)
	}

	return groupRequests, nil
}

func (ms *MemorySearcher) fetchUsers() {
	pathFilter := strings.TrimSpace(os.Getenv("SUSE_USER_FILTER_PATH"))
	rawGroupNames := strings.TrimSpace(os.Getenv("SUSE_USER_FILTER_GROUP_NAMES"))

	userRequest, err := ms.buildUserAPIRequest(pathFilter, rawGroupNames)
	if err != nil {
		ms.log.WithError(err).Warning("Error building user request filters. Skipped fetching users.")
		return
	}

	paginatorOpts := ak.PaginatorOptions{
		PageSize: 500,
		Logger:   ms.log.WithField("fetcher", "users"),
	}
	userIterator := ak.PaginatorIterator(userRequest, paginatorOpts)
	seenRefs := suse.NewGenericMarkMapping[int32]()

	failedUsers := false

	ms.log.Info("Fetching users...")

	reconstructMemberships := suse.MapSize(globalGroupCache) > 0

	for user, err := range userIterator {
		if err != nil {
			ms.log.Error("Failed requesting users. Aborting")
			failedUsers = true
			break
		}

		if reconstructMemberships {
			ms.enrichUserGroupsFromCache(&user)
		}

		suse.SetKeyInMapping(globalUserCache, user.Pk, user)
		seenRefs[user.Pk] = sentinel
	}

	if !failedUsers {
		// Now go over the known users, and delete the not seen ones, there's prolly a
		// better way to do symmetric diff.
		ms.log.Info("Removing stale user records from memory")
		suse.SweepMap(globalUserCache, seenRefs)
		ms.log.Info("Done removing stale user records from memory")
	}
}

func (ms *MemorySearcher) fetchGroups() {
	rawGroupNames := os.Getenv("SUSE_GROUP_FILTER_NAMES")
	groupRequests, err := ms.buildGroupRequests(rawGroupNames)
	if err != nil {
		ms.log.WithError(err).Warning("Error building group requests. Skipped fetching groups.")
		return
	}

	paginatorOpts := ak.PaginatorOptions{
		PageSize: 500,
		Logger:   ms.log.WithField("fetcher", "groups"),
	}
	seenRefs := suse.NewGenericMarkMapping[string]()
	failedGroups := false
	reconstructMemberships := suse.MapSize(globalUserCache) > 0

	ms.log.Info("Fetching Groups...")

	for _, groupRequest := range groupRequests {
		groupIterator := ak.PaginatorIterator(groupRequest, paginatorOpts)

		for group, err := range groupIterator {
			if err != nil {
				ms.log.Error("Failed requesting groups. Aborting")
				failedGroups = true
				break
			}

			if reconstructMemberships {
				ms.enrichGroupUsersFromCache(&group)
			}

			suse.SetKeyInMapping(globalGroupCache, group.Pk, group)
			seenRefs[group.Pk] = sentinel
		}
	}

	if !failedGroups {
		ms.log.Info("Removing stale group records from memory")
		suse.SweepMap(globalGroupCache, seenRefs)
		ms.log.Info("Done removing stale group records from memory")
	}
}

func (ms *MemorySearcher) fetch() {
	// Overall this implementation should use a tad more ram on idle, but will never need
	// MORE THAN TWICE [one for the "live" array, one for the "new" array] the
	// amount of memory when refreshing pages.
	//
	// The combination of less data per API request + iterator implementation
	// should keep ram usage lower.

	// in fact, by virtue of:
	//
	// - mark & sweep records
	// - issuing requests with filters
	// - avoiding duplicated data
	// - consuming requests via iterators instead of slurping them
	//
	// RSS usage is < 15% of the original status quo.
	// with proper user/group filters set it can go as low as ~50M ram

	if syncInProgress {
		ms.log.Info("Busy sincing the global cache, come again later...")
		return
	}
	syncInProgress = true
	defer func() { syncInProgress = false }()

	if lastSync == nil {
		ms.log.Info("First sync")
	} else {
		ms.log.Info("Follow-up sync")
		nextSync := lastSync.Add(ms.si.GetRefreshInterval())
		if nextSync.After(time.Now()) {
			ms.log.WithFields(log.Fields{
				"next-sync": nextSync.Format(time.RFC3339),
			}).Info("Too soon ...")
			return
		}
	}
	defer func() {
		t := time.Now()
		lastSync = &t
	}()

	ms.log.Info("Fetching users/groups from filters")

	wg := sync.WaitGroup{}
	wg.Add(2)
	go func() {
		defer wg.Done()
		ms.fetchUsers()
	}()
	go func() {
		defer wg.Done()
		ms.fetchGroups()
	}()
	wg.Wait()
}

func (ms *MemorySearcher) SearchBase(req *search.Request) (ldap.ServerSearchResult, error) {
	return ms.ds.SearchBase(req)
}

func (ms *MemorySearcher) SearchSubschema(req *search.Request) (ldap.ServerSearchResult, error) {
	return ms.ds.SearchSubschema(req)
}

func (ms *MemorySearcher) entryForBaseUserDN(req *search.Request) *ldap.Entry {
	return utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseUserDN(), constants.OUUsers)
}

func (ms *MemorySearcher) entryForBaseGroupDN(req *search.Request) *ldap.Entry {
	return utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseGroupDN(), constants.OUGroups)
}

func (ms *MemorySearcher) entryForBaseVirtualGroupDN(req *search.Request) *ldap.Entry {
	return utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseVirtualGroupDN(), constants.OUVirtualGroups)
}

func (ms *MemorySearcher) filterAsksForContainers(req *search.Request) bool {
	return utils.IncludeObjectClass(req.FilterObjectClass, constants.GetContainerOCs())
}

func (ms *MemorySearcher) filterAsksForDomain(req *search.Request) bool {
	return utils.IncludeObjectClass(req.FilterObjectClass, constants.GetDomainOCs())
}

func (ms *MemorySearcher) filterAsksForBaseUser(req *search.Request) bool {
	return utils.IncludeObjectClass(req.FilterObjectClass, constants.GetUserOCs())
}

func (ms *MemorySearcher) filterAsksForBaseGroup(req *search.Request) bool {
	return utils.IncludeObjectClass(req.FilterObjectClass, constants.GetGroupOCs())
}

func (ms *MemorySearcher) filterAsksForBaseVirtualGroup(req *search.Request) bool {
	return utils.IncludeObjectClass(req.FilterObjectClass, constants.GetVirtualGroupOCs())
}

func (ms *MemorySearcher) processScopeBaseRequest(req *search.Request, entries *[]*ldap.Entry, slicedUsers *suse.MutexMap[int32, api.User], slicedGroups *suse.MutexMap[string, api.Group]) {
	requestDNisBaseDN := strings.EqualFold(req.BaseDN, ms.si.GetBaseDN())
	// If the client wants the root only
	if requestDNisBaseDN && ms.filterAsksForDomain(req) {
		// Add the base entry, and stop here.
		ms.enrichSearchBaseEntries(req, entries)
		return
	}

	// If the client wants something with users
	if wantsUsers, wantsSpecificUser := utils.HasSuffixWithMore(req.BaseDN, ms.si.GetBaseUserDN()); wantsUsers {
		// If the client wants the user dn base
		if ms.filterAsksForContainers(req) && !wantsSpecificUser {
			// append the container
			*entries = append(*entries, utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseUserDN(), constants.OUUsers))
			return
		}

		// If the client wants a specific user, then find the user by strict dn match
		if wantsSpecificUser && utils.IncludeObjectClass(req.FilterObjectClass, constants.GetUserOCs()) {
			suse.IterateMap(*slicedUsers, func(_ int32, u api.User) bool {
				entry := ms.si.UserEntry(u)
				if strings.EqualFold(req.BaseDN, entry.DN) {
					*entries = append(*entries, entry)
					return false
				}
				return true
			})
		}

		return
	}

	// If the client wants something with groups
	if wantsGroups, wantsSpecificGroup := utils.HasSuffixWithMore(req.BaseDN, ms.si.GetBaseGroupDN()); wantsGroups {
		// If the client wants the group dn base
		if ms.filterAsksForContainers(req) && !wantsSpecificGroup {
			// append the container
			*entries = append(*entries, utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseGroupDN(), constants.OUGroups))
			return
		}

		// If the client wants a group, then find the group by strict dn match
		if wantsSpecificGroup && utils.IncludeObjectClass(req.FilterObjectClass, constants.GetGroupOCs()) {
			suse.IterateMap(*slicedGroups, func(_ string, g api.Group) bool {
				entry := group.FromAPIGroup(g, ms.si)
				if strings.EqualFold(req.BaseDN, entry.DN) {
					*entries = append(*entries, entry.Entry())
					return false
				}
				return true
			})
		}

		return
	}

	// If the client wants something with virtual-groups
	if wantsVirtualGroups, wantsSpecificVirtualGroup := utils.HasSuffixWithMore(req.BaseDN, ms.si.GetBaseVirtualGroupDN()); wantsVirtualGroups {
		// If the client wants the virtual-group dn base

		if ms.filterAsksForContainers(req) && !wantsSpecificVirtualGroup {
			// append the container
			*entries = append(*entries, utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseVirtualGroupDN(), constants.OUVirtualGroups))
		}

		// If the client wants a virtual-group, then find the group by strict dn match
		if wantsSpecificVirtualGroup && utils.IncludeObjectClass(req.FilterObjectClass, constants.GetVirtualGroupOCs()) {
			suse.IterateMap(*slicedUsers, func(_ int32, u api.User) bool {
				entry := ms.si.UserEntry(u)
				if strings.EqualFold(req.BaseDN, entry.DN) {
					*entries = append(*entries, entry)
					return false
				}
				return true
			})
		}

		return
	}

	return
}

func (ms *MemorySearcher) processScopeOneRequest(req *search.Request, entries *[]*ldap.Entry, slicedUsers *suse.MutexMap[int32, api.User], slicedGroups *suse.MutexMap[string, api.Group]) {
	requestDNisBaseDN := strings.EqualFold(req.BaseDN, ms.si.GetBaseDN())
	// if request DN is base, then return the 3 nested containers: groups, users,
	// virtual-groups
	if requestDNisBaseDN {
		// if no container is asked, nothing is returned
		if !ms.filterAsksForContainers(req) {
			return
		}

		*entries = append(*entries, utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseUserDN(), constants.OUUsers))
		*entries = append(*entries, utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseGroupDN(), constants.OUGroups))
		*entries = append(*entries, utils.GetContainerEntry(req.FilterObjectClass, ms.si.GetBaseVirtualGroupDN(), constants.OUVirtualGroups))
	}

	// if request DN is the user base, then collect all available users, filters
	// are evaluated by the caller of this handler
	if strings.EqualFold(req.BaseDN, ms.si.GetBaseUserDN()) {
		if !utils.IncludeObjectClass(req.FilterObjectClass, constants.GetUserOCs()) {
			return
		}

		suse.IterateMap(*slicedUsers, func(_ int32, u api.User) bool {
			entry := ms.si.UserEntry(u)
			*entries = append(*entries, entry)
			return true
		})
	}

	// if request DN is the user base, then collect all available groups, filters
	// are evaluated by the caller of this handler
	if strings.EqualFold(req.BaseDN, ms.si.GetBaseGroupDN()) {
		// if no container is asked, nothing is returned
		if !utils.IncludeObjectClass(req.FilterObjectClass, constants.GetGroupOCs()) {
			return
		}

		suse.IterateMap(*slicedGroups, func(_ string, g api.Group) bool {
			entry := group.FromAPIGroup(g, ms.si)
			*entries = append(*entries, entry.Entry())
			return true
		})
	}

	// if request DN is the user base, then collect all available virtual-groups,
	// filters are evaluated by the caller of this handler
	if strings.EqualFold(req.BaseDN, ms.si.GetBaseVirtualGroupDN()) {
		// if no container is asked, nothing is returned
		if !utils.IncludeObjectClass(req.FilterObjectClass, constants.GetUserOCs()) {
			return
		}

		suse.IterateMap(*slicedUsers, func(_ int32, u api.User) bool {
			entry := group.FromAPIUser(u, ms.si).Entry()
			*entries = append(*entries, entry)
			return true
		})
	}

	return
}

func (ms *MemorySearcher) processScopeSubRequest(req *search.Request, entries *[]*ldap.Entry, slicedUsers *suse.MutexMap[int32, api.User], slicedGroups *suse.MutexMap[string, api.Group]) {
	requestDNisBaseDN := strings.EqualFold(req.BaseDN, ms.si.GetBaseDN())
	requestDnIsUserDn := strings.EqualFold(req.BaseDN, ms.si.GetBaseUserDN())
	requestDnIsGroupDN := strings.EqualFold(req.BaseDN, ms.si.GetBaseGroupDN())
	requestDnIsVirtualGroupDN := strings.EqualFold(req.BaseDN, ms.si.GetBaseVirtualGroupDN())

	// if request DN is the user base, then collect all available users, filters
	// are evaluated by the caller of this handler

	if requestDNisBaseDN || requestDnIsUserDn {
		if ms.filterAsksForContainers(req) && ms.filterAsksForBaseUser(req) {
			*entries = append(*entries, ms.entryForBaseUserDN(req))
		}

		suse.IterateMap(*slicedUsers, func(_ int32, u api.User) bool {
			entry := ms.si.UserEntry(u)
			*entries = append(*entries, entry)
			return true
		})
	}

	// if request DN is the user base, then collect all available groups, filters
	// are evaluated by the caller of this handler
	if requestDNisBaseDN || requestDnIsGroupDN {
		if ms.filterAsksForContainers(req) && ms.filterAsksForBaseGroup(req) {
			*entries = append(*entries, ms.entryForBaseGroupDN(req))
		}
		suse.IterateMap(*slicedGroups, func(_ string, g api.Group) bool {
			entry := group.FromAPIGroup(g, ms.si)
			*entries = append(*entries, entry.Entry())
			return true
		})
	}

	// if request DN is the user base, then collect all available virtual-groups,
	// filters are evaluated by the caller of this handler
	if requestDNisBaseDN || requestDnIsVirtualGroupDN {
		if ms.filterAsksForContainers(req) && ms.filterAsksForBaseVirtualGroup(req) {
			*entries = append(*entries, ms.entryForBaseVirtualGroupDN(req))
		}
		suse.IterateMap(*slicedUsers, func(_ int32, u api.User) bool {
			entry := group.FromAPIUser(u, ms.si).Entry()
			*entries = append(*entries, entry)
			return true
		})
	}
}

func (ms *MemorySearcher) enrichSearchBaseEntries(req *search.Request, entries *[]*ldap.Entry) {
	// From the sample response in: internal/outpost/ldap/search/direct/base.go
	// Rewrite the DN's to match the current provider base DN
	rootEntries, _ := ms.SearchBase(req)

	for _, e := range rootEntries.Entries {
		e.DN = ms.si.GetBaseDN()
		for _, ea := range e.Attributes {
			if ea.Name == "entryDN" {
				ea.Values = []string{e.DN}
			}
		}

		*entries = append(*entries, e)
	}
}
func (ms *MemorySearcher) sliceUsersFromCache(needUsers bool, flag *flags.UserFlags, currentUser api.User) *suse.MutexMap[int32, api.User] {
	// if users are not needed, then return an empty slice
	if !needUsers {
		m := suse.NewMutexMap[int32, api.User]()
		return &m
	}

	// If the user search asks for user records but it's not entitled to search
	if flag.CanSearch {
		return &globalUserCache
	}

	// forward this assignment, god knows why... upstream logic had it set.
	flag.UserInfo = &currentUser

	// User was found in cache, and it's not allowed to search, procure a user
	// list only contianing the request user.
	u := suse.NewMutexMap[int32, api.User]()
	suse.SetKeyInMapping(u, currentUser.Pk, currentUser)
	return &u
}
func (ms *MemorySearcher) sliceGroupsFromCache(needGroups bool, flag *flags.UserFlags, currentUser api.User) *suse.MutexMap[string, api.Group] {
	// if Groups are not needed, then return an empty slice
	if !needGroups {
		m := suse.NewMutexMap[string, api.Group]()
		return &m
	}

	// If the Group search asks for Group records but it's not entitled to search
	if flag.CanSearch {
		return &globalGroupCache
	}

	groups := suse.NewMutexMap[string, api.Group]()
	for _, groupUuid := range currentUser.Groups {
		g, ok := suse.GetFromMapping(globalGroupCache, groupUuid)
		if !ok {
			// if this outpost does not know this group, ignore it.
			continue
		}

		fg := api.NewGroupWithDefaults()
		fg.SetPk(g.Pk)
		fg.SetNumPk(g.NumPk)
		fg.SetName(g.Name)

		pu := *api.NewPartialUser(currentUser.Pk, currentUser.Username, currentUser.Name, currentUser.Uid)
		fg.SetUsersObj([]api.PartialUser{pu})
		fg.SetUsers([]int32{pu.Pk})
		fg.SetAttributes(g.Attributes)
		fg.SetIsSuperuser(g.GetIsSuperuser())

		suse.SetKeyInMapping(groups, groupUuid, g)
	}

	return &groups
}

func (ms *MemorySearcher) Search(req *search.Request) (ldap.ServerSearchResult, error) {
	accsp := sentry.StartSpan(req.Context(), "authentik.providers.ldap.suse_search.check_access")
	baseDN := ms.si.GetBaseDN()

	// Begin -- AuthN & AuthZ

	if len(req.BindDN) < 1 {
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ms.si.GetOutpostName(),
			"type":         "search",
			"reason":       "empty_bind_dn",
			"app":          ms.si.GetAppSlug(),
		}).Inc()
		ms.log.Debug("Rejected request [ no Anonymous binds ]")
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultInsufficientAccessRights}, fmt.Errorf("Search Error: Anonymous BindDN not allowed %s", req.BindDN)
	}
	if !utils.HasSuffixNoCase(req.BindDN, ","+baseDN) {
		ms.log.WithFields(log.Fields{
			"request-dn": req.BindDN,
			"base-dn":    baseDN,
		}).Debug("Rejected request [ request-dn not in base-dn ]")

		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ms.si.GetOutpostName(),
			"type":         "search",
			"reason":       "invalid_bind_dn",
			"app":          ms.si.GetAppSlug(),
		}).Inc()
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultInsufficientAccessRights}, fmt.Errorf("Search Error: BindDN %s not in our BaseDN %s", req.BindDN, baseDN)
	}

	flag := ms.si.GetFlags(req.BindDN)

	if flag == nil || (flag.UserInfo == nil && flag.UserPk == flags.InvalidUserPK) {
		req.Log().Debug("User info not cached")
		metrics.RequestsRejected.With(prometheus.Labels{
			"outpost_name": ms.si.GetOutpostName(),
			"type":         "search",
			"reason":       "user_info_not_cached",
			"app":          ms.si.GetAppSlug(),
		}).Inc()

		ms.log.WithFields(log.Fields{
			"request-dn": req.BindDN,
			"base-dn":    baseDN,
		}).Debug("Rejected request [ request-dn not in base-dn ]")

		err := errors.New("access denied [login failed]")
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultInsufficientAccessRights}, err
	}
	accsp.Finish()

	currentUser, ok := suse.GetFromMapping(globalUserCache, flag.UserPk)
	if !ok {
		req.Log().WithField("username", flag.UserPk).Warning("Request user is not in local cache")
		err := errors.New("access denied [not in cache]")
		// Bail early, user is not known to this outpost.
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultInsufficientAccessRights}, err
	}

	// End -- AuthN & AuthZ
	entries := make([]*ldap.Entry, 0)
	scope := req.Scope

	// Derive from the filter / base dn whether this request needs users or groups in the response
	needUsers, needGroups := ms.si.GetNeededObjects(scope, req.BaseDN, req.FilterObjectClass)

	ms.log.WithFields(log.Fields{
		"need-users":    needUsers,
		"need-groups":   needGroups,
		"have-users":    suse.MapSize(globalUserCache),
		"have-groups":   suse.MapSize(globalGroupCache),
		"search-filter": req.FilterObjectClass,
		"scope":         ldap.ScopeMap[scope],
	}).Info("Performing search")

	// Slice the result set before processing users that can't search the
	// directory get a slice of the cache where only themselves are included.
	var slicedUsers *suse.MutexMap[int32, api.User] = ms.sliceUsersFromCache(needUsers, flag, currentUser)
	var slicedGroups *suse.MutexMap[string, api.Group] = ms.sliceGroupsFromCache(needGroups, flag, currentUser)

	// Now process the request
	switch scope {
	case ldap.ScopeBaseObject:
		// Procure only the base record
		ms.processScopeBaseRequest(req, &entries, slicedUsers, slicedGroups)
	case ldap.ScopeWholeSubtree:
		// Find the base, and traverse from there
		ms.processScopeSubRequest(req, &entries, slicedUsers, slicedGroups)
	case ldap.ScopeSingleLevel:
		// Find the base, and return all the children elements
		ms.processScopeOneRequest(req, &entries, slicedUsers, slicedGroups)
	default:
		// is there a way to run into this condition? Who knows. We'll error out just in case
		err := fmt.Errorf("Failed to understand scope")
		return ldap.ServerSearchResult{ResultCode: ldap.LDAPResultOperationsError}, err
	}

	// return the resulting entries
	return ldap.ServerSearchResult{Entries: entries, Referrals: []string{}, Controls: []ldap.Control{}, ResultCode: ldap.LDAPResultSuccess}, nil
}
