package ldap

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

func (pi *ProviderInstance) outpostConfig(key string, def string) string {
	rawVal, ok := pi.s.ac.Outpost.Config["username_attribute_name"]
	if ok {
		switch val := rawVal.(type){
			case string:
				return val
		}
	}
	return def
}

func (pi *ProviderInstance) usernameAttributeName() string {
	return pi.outpostConfig("username_attr_name", "cn")
}

func (pi *ProviderInstance) akUidAttributeName() string {
	return pi.outpostConfig("ak_uid_attr_name", "uid")
}

func sUSE_getPredefinedEntries(pi *ProviderInstance, u api.User) map[string][]string {
	return map[string][]string{
		"ak-user-pk":     {strconv.FormatInt(int64(u.Pk), 10)},
		"ak-active":      {strings.ToUpper(strconv.FormatBool(*u.IsActive))},
		"ak-superuser":   {strings.ToUpper(strconv.FormatBool(u.IsSuperuser))},
		"memberOf":       pi.GroupsForUser(u),
		"sAMAccountName": {u.Username},
		"name":           {u.Name},
		"displayName":    {u.Name},
		"mail":           {*u.Email},
		"objectClass": {
			constants.OCTop,
			constants.OCPerson,
			constants.OCOrgPerson,
			constants.OCInetOrgPerson,
			constants.OCUser,
			constants.OCPosixAccount,
			constants.OCAKUser,
		},
		"uidNumber":       {pi.GetUserUidNumber(u)},
		"gidNumber":       {pi.GetUserGidNumber(u)},
		"homeDirectory":   {fmt.Sprintf("/home/%s", u.Username)},
		"sn":              {u.Name},
		"pwdChangedTime":  {u.PasswordChangeDate.In(time.UTC).Format("20060102150405Z")},
		"createTimestamp": {u.DateJoined.In(time.UTC).Format("20060102150405Z")},
		"modifyTimestamp": {u.LastUpdated.In(time.UTC).Format("20060102150405Z")},
	}

	userNameField := pi.usernameAttributeName()
	presetAttrs[userNameField] = []string{u.Username}

	akUidField := pi.akUidAttributeName()
	presetAttrs[akUidField] = []string{u.Uid}

	attrs = utils.EnsureAttributes(attrs, presetAttrs)
}
