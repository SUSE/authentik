package ldap

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	"beryju.io/ldap"

	"goauthentik.io/api/v3"

	"goauthentik.io/internal/outpost/ldap/constants"
	"goauthentik.io/internal/outpost/ldap/suse/outpost_config"
	"goauthentik.io/internal/outpost/ldap/utils"
)

func suseGetPredefinedEntries(pi *ProviderInstance, u api.User) map[string][]string {
	configuredMapping := outpost_config.GetKey[map[string]string](pi.s.ac, "user_attribute_mapping", map[string]string{})
	mapping := constants.SUSEMergedFieldMapping(configuredMapping)

	userNameField := mapping["username"]
	akUidField := mapping["ak-uid"]

	return map[string][]string{
		"ak-user-pk":     {strconv.FormatInt(int64(u.Pk), 10)},
		"ak-active":      {strings.ToUpper(strconv.FormatBool(*u.IsActive))},
		"ak-superuser":   {strings.ToUpper(strconv.FormatBool(u.IsSuperuser))},
		"memberOf":       pi.GroupsForUser(u),
		"sAMAccountName": {u.Username},
		"name":           {u.Name},
		"displayName":    {u.Name},
		"mail":           {*u.Email},
		userNameField:    {u.Username},
		akUidField:       {u.Uid},
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
}

// Copy-paste from the original, kept separate intentionally to prevent an
// import loop trying to use ProviderInstance (a symbol from
// goauthentik.io/internal/outpost/ldap) from outside.
func (pi *ProviderInstance) suseUserEntry(u api.User) *ldap.Entry {
	dn := pi.GetUserDN(u.Username)
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

	predefinedAttrs := suseGetPredefinedEntries(pi, u)
	attrs = utils.EnsureAttributes(attrs, predefinedAttrs)
	return &ldap.Entry{DN: dn, Attributes: attrs}
}
