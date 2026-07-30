// Copyright 2026 - 2026, SUSE LLC <georg.pfuetzenreuter@suse.com>
// SPDX-License-Identifier: Apache-2.0

package web

import (
	"net/http"

	"goauthentik.io/internal/config"
)

// specific version variables for storing the expected Python backend version
// (we build with constants.version set to our package version which does not contain the build "hash")
var (
	versionMajor string
	versionMinor string
)

func (ws *WebServer) configureIntercept() {
	interceptedPaths := make(map[string]string)

	if versionMajor != "" && versionMinor != "" {
		interceptedPaths["/api/v3/admin/version/"] = `{"version_current":"` + versionMajor + `","version_latest":"0.0.0","version_latest_valid":false,"build_hash":"` + versionMinor + `","outdated":false,"outpost_outdated":false}`
	}

	for routePath, jsonResponse := range interceptedPaths {
		p := routePath
		resp := jsonResponse

		ws.mainRouter.PathPrefix(config.Get().Web.Path).Path(p).HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
			rw.Header().Set("Content-Type", "application/json")
			rw.WriteHeader(http.StatusOK)
			_, err := rw.Write([]byte(resp))
			if err != nil {
				ws.log.WithError(err).Warning("failed to write json response")
			}
		})
	}
}
