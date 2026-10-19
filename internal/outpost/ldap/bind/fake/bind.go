package direct

import (
	"beryju.io/ldap"
	"context"
	log "github.com/sirupsen/logrus"
	"goauthentik.io/api/v3"
	"goauthentik.io/internal/outpost/ldap/bind"
	"goauthentik.io/internal/outpost/ldap/flags"
	"goauthentik.io/internal/outpost/ldap/server"
)

type DirectBinder struct {
	si  server.LDAPServerInstance
	log *log.Entry
}

func NewDirectBinder(si server.LDAPServerInstance) *DirectBinder {
	db := &DirectBinder{
		si:  si,
		log: log.WithField("logger", "authentik.outpost.ldap.binder.direct"),
	}
	db.log.Info("initialised direct binder")
	return db
}
func (db *DirectBinder) TimerFlowCacheExpiry(ctx context.Context) {
}
func (db *DirectBinder) GetUsername(dn string) (string, error) {
	return "fake", nil
}

func (db *DirectBinder) Unbind(username string, req *bind.Request) (ldap.LDAPResultCode, error) {
	return ldap.LDAPResultSuccess, nil

}
func (db *DirectBinder) Bind(username string, req *bind.Request) (ldap.LDAPResultCode, error) {
	req.Log().Debug("Fake bind")
	flags := flags.UserFlags{
		Session:    nil,
		SessionJWT: nil,
		UserPk:     flags.InvalidUserPK,
	}
	flags.UserPk = 37

	// Reconstruct a full User object from the /users/me response
	flags.UserInfo = api.NewUserWithDefaults()
	flags.UserInfo.Pk = 37
	flags.UserInfo.Username = "stub"
	flags.UserInfo.Name = "foo"
	flags.UserInfo.SetIsActive(true)
	flags.UserInfo.IsSuperuser = false
	flags.UserInfo.SetEmail("mail@test")

	flags.CanSearch = true
	db.si.SetFlags(req.BindDN, &flags)

	return ldap.LDAPResultSuccess, nil
}
