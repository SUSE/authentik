package outpost_config

import (
	"goauthentik.io/internal/outpost/ak"
)

func GetKey[T any](ac *ak.APIController, key string, def T) T {
	rawVal, ok := ac.Outpost.Config[key]
	if ok {
		switch val := rawVal.(type) {
		case T:
			return val
		}
	}
	return def
}
