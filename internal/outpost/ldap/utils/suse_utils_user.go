package utils

import (
	"beryju.io/ldap"
	goldap "github.com/go-ldap/ldap/v3"
	ber "github.com/nmcclain/asn1-ber"
	"goauthentik.io/api/v3"
	"encoding/json"
	"goauthentik.io/internal/outpost/ldap/constants"
)

func sUSE_parseFilterForUserSingle(req api.ApiCoreUsersListRequest, f *ber.Packet, attrs *map[string]string) (api.ApiCoreUsersListRequest, bool) {
	// We can only handle key = value pairs here
	if len(f.Children) < 2 {
		return req, false
	}
	k, ok := f.Children[0].Value.(string)
	// Ensure key is string
	if !ok {
		return req, false
	}
	v := f.Children[1].Value
	// Null values are ignored
	if v == nil {
		return req, false
	}
	val := stringify(v)
	if val == nil {
		return req, false
	}

	switch k {
	case "uid":
		return req.Username(*val), false
	case "name":
		fallthrough
	case "cn":
		fallthrough
	case "displayName":
		return req.Name(*val), false
	case "mail":
		return req.Email(*val), false
	case "member":
		fallthrough
	case "memberOf":
		groupDN, err := goldap.ParseDN(*val)
		if err != nil {
			return req.GroupsByName([]string{*val}), false
		}
		name := groupDN.RDNs[0].Attributes[0].Value
		// If the DN's first ou is virtual-groups, ignore this filter
		if len(groupDN.RDNs) > 1 {
			if groupDN.RDNs[1].Attributes[0].Value == constants.OUUsers || groupDN.RDNs[1].Attributes[0].Value == constants.OUVirtualGroups {
				// Since we know we're not filtering anything, skip this request
				return req, true
			}
		}
		return req.GroupsByName([]string{name}), false
	default:
		(*attrs)[k] = *val
	}
	return req, false
}

func SUSE_ParseFilterForUser_recursive(req api.ApiCoreUsersListRequest, f *ber.Packet, skip bool, attrs *map[string]string) (api.ApiCoreUsersListRequest, bool) {
	switch f.Tag {
	case ldap.FilterEqualityMatch:
		return sUSE_parseFilterForUserSingle(req, f, attrs)
	case ldap.FilterAnd:
		for _, child := range f.Children {
			r, s := SUSE_ParseFilterForUser_recursive(req, child, skip, attrs)
			skip = skip || s
			req = r
		}
	}

	if len(*attrs) > 0 {
		b, _ := json.Marshal(*attrs)
		req = req.Attributes(string(b))
	}
	return req, skip
}

func SUSE_ParseFilterForUser(req api.ApiCoreUsersListRequest, f *ber.Packet, skip bool) (api.ApiCoreUsersListRequest, bool) {
	attrs := make(map[string]string)
	return SUSE_ParseFilterForUser_recursive(req, f, skip, &attrs)
}
