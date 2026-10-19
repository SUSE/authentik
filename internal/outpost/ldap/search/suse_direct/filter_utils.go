package suse_direct

import (
	"beryju.io/ldap"
	"encoding/json"
	goldap "github.com/go-ldap/ldap/v3"
	ber "github.com/nmcclain/asn1-ber"
	"goauthentik.io/api/v3"
	"goauthentik.io/internal/outpost/ldap/constants"

	"fmt"
	"strconv"
)

func stringify(in interface{}) *string {
	switch t := in.(type) {
	case string:
		return &t
	case *string:
		return t
	case bool:
		s := strconv.FormatBool(t)
		return &s
	case float32:
		s := strconv.FormatFloat(float64(t), 'f', -1, 64)
		return &s
	case float64:
		s := strconv.FormatFloat(t, 'f', -1, 64)
		return &s
	case int:
		s := strconv.FormatInt(int64(t), 10)
		return &s
	default:
		if in != nil {
			s := fmt.Sprintf("%s", in)
			return &s
		}
		return nil
	}
}

func parseFilterForUserSingle(req api.ApiCoreUsersListRequest, f *ber.Packet, attrs *map[string]string) (api.ApiCoreUsersListRequest, bool) {
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

func recurseParseFilterForUser(req api.ApiCoreUsersListRequest, f *ber.Packet, skip bool, attrs *map[string]string) (api.ApiCoreUsersListRequest, bool) {
	switch f.Tag {
	case ldap.FilterEqualityMatch:
		return parseFilterForUserSingle(req, f, attrs)
	case ldap.FilterAnd:
		for _, child := range f.Children {
			r, s := recurseParseFilterForUser(req, child, skip, attrs)
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

func parseFilterForUser(req api.ApiCoreUsersListRequest, f *ber.Packet, skip bool) (api.ApiCoreUsersListRequest, bool) {
	attrs := make(map[string]string)
	return recurseParseFilterForUser(req, f, skip, &attrs)
}
