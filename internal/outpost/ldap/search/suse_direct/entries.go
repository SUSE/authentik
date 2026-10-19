package suse_direct

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	"beryju.io/ldap"

	"goauthentik.io/api/v3"
	"goauthentik.io/internal/outpost/ldap/constants"
	"goauthentik.io/internal/outpost/ldap/utils"
)

func userEntry(dn string, u api.User, baseDN string) *ldap.Entry {
	attrs := utils.AttributesToLDAP(u.Attributes, func(key string) string {
		return utils.AttributeKeySanitize(key)
	}, func(value []string) []string {
		for i, v := range value {
			if strings.Contains(v, "%s") {
				value[i] = fmt.Sprintf(v, u.Username)
			}
		}
		return value
	})

	if u.IsActive == nil {
		u.IsActive = api.PtrBool(false)
	}
	if u.Email == nil {
		u.Email = api.PtrString("")
	}

	presetAttrs := map[string][]string{
		"ak-user-pk":   {strconv.FormatInt(int64(u.Pk), 10)},
		"ak-active":    {strings.ToUpper(strconv.FormatBool(*u.IsActive))},
		"ak-superuser": {strings.ToUpper(strconv.FormatBool(u.IsSuperuser))},
		"memberOf":     groupEntries(u, baseDN),
		"uid":          {u.Uid},
		"name":         {u.Name},
		"displayName":  {u.Name},
		"mail":         {*u.Email},
		"objectClass": {
			constants.OCTop,
			constants.OCPerson,
			constants.OCOrgPerson,
			constants.OCInetOrgPerson,
			constants.OCUser,
			constants.OCPosixAccount,
			constants.OCAKUser,
		},
		"sn":              {u.Name},
		"pwdChangedTime":  {u.PasswordChangeDate.In(time.UTC).Format("20060102150405Z")},
		"createTimestamp": {u.DateJoined.In(time.UTC).Format("20060102150405Z")},
		"modifyTimestamp": {u.LastUpdated.In(time.UTC).Format("20060102150405Z")},
	}

	userNameField := "uid"
	presetAttrs[userNameField] = []string{u.Username}

	akUidField := "ak-uid"
	presetAttrs[akUidField] = []string{u.Uid}

	attrs = utils.EnsureAttributes(attrs, presetAttrs)
	return &ldap.Entry{DN: dn, Attributes: attrs}
}

func groupEntries(user api.User, baseDN string) []string {
	groups := make([]string, len(user.Groups))
	used := 0
	for _, group := range user.GroupsObj {
		groups[used] = fmt.Sprintf("cn=%s,ou=groups,%s", group.Name, baseDN)
		used = used + 1
	}
	return groups[0:used]
}
