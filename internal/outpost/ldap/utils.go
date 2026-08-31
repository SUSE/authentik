package ldap

import (
	"fmt"
	"strconv"

	"goauthentik.io/api/v3"
)

func getAttributeString(attributes map[string]any, key string) (string, bool) {
	val, ok := attributes[key]
	if !ok || val == nil {
		return "", false
	}

	switch v := val.(type) {
	case string:
		return v, true
	case float64:
		return strconv.FormatFloat(v, 'f', -1, 64), true
	default:
		return "", false
	}
}

func (pi *ProviderInstance) GroupsForUser(user api.User) []string {
	groups := make([]string, len(user.Groups))
	used := 0
	for _, group := range user.GroupsObj {
		groups[used] = pi.GetGroupDN(group.Name)
		used = used + 1
	}
	return groups[0:used]
}

func (pi *ProviderInstance) MembersForGroup(group api.Group) []string {
	users := make([]string, len(group.UsersObj))
	usedUsers := 0
	for _, user := range group.UsersObj {
		users[usedUsers] = pi.GetUserDN(user.Username)
		usedUsers = usedUsers + 1
	}
	children := make([]string, len(group.ChildrenObj))
	userChildren := 0
	for _, child := range group.ChildrenObj {
		children[userChildren] = pi.GetGroupDN(child.Name)
		userChildren = userChildren + 1
	}
	users = users[0:usedUsers]
	children = children[0:userChildren]

	return append(users, children...)
}

func (pi *ProviderInstance) MemberOfForGroup(group api.Group) []string {
	groups := make([]string, len(group.ParentsObj))
	used := 0
	for _, group := range group.ParentsObj {
		groups[used] = pi.GetGroupDN(group.Name)
		used = used + 1
	}
	return groups[0:used]
}

func (pi *ProviderInstance) GetUserDN(user string) string {
	return fmt.Sprintf("cn=%s,%s", user, pi.UserDN)
}

func (pi *ProviderInstance) GetGroupDN(group string) string {
	return fmt.Sprintf("cn=%s,%s", group, pi.GroupDN)
}

func (pi *ProviderInstance) GetVirtualGroupDN(group string) string {
	return fmt.Sprintf("cn=%s,%s", group, pi.VirtualGroupDN)
}

func (pi *ProviderInstance) GetUserUidNumber(user api.User) string {
	uidNumber, ok := getAttributeString(user.GetAttributes(), "uidNumber")

	if ok {
		return uidNumber
	}

	return strconv.FormatInt(int64(pi.uidStartNumber+user.Pk), 10)
}

func (pi *ProviderInstance) GetUserGidNumber(user api.User) string {
	gidNumber, ok := getAttributeString(user.GetAttributes(), "gidNumber")

	if ok {
		return gidNumber
	}

	return pi.GetUserUidNumber(user)
}

func (pi *ProviderInstance) GetGroupGidNumber(group api.Group) string {
	gidNumber, ok := getAttributeString(group.GetAttributes(), "gidNumber")

	if ok {
		return gidNumber
	}

	return strconv.FormatInt(int64(pi.gidStartNumber+group.NumPk), 10)
}
