import "#elements/forms/HorizontalFormElement";
import "#components/ak-switch-input";
import "#elements/buttons/ActionButton/ak-action-button";
import "@patternfly/elements/pf-tooltip/pf-tooltip.js";

import { DEFAULT_CONFIG } from "#common/api/config";
import { ROUTE_SEPARATOR } from "#common/constants";
import { globalAK } from "#common/global";

import { AKElement } from "#elements/Base";
import { listen } from "#elements/decorators/listen";
import { WithNotifications } from "#elements/mixins/notifications";
import { WithSession } from "#elements/mixins/session";
import { AKDrawerChangeEvent } from "#elements/notifications/events";
import { RouteChangeEvent } from "#elements/router/events";
import { isUserRoute } from "#elements/router/utils";

import Styles from "#components/ak-nav-button.css";

import { CoreApi } from "@goauthentik/api";

import { msg } from "@lit/localize";
import { html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { guard } from "lit/directives/guard.js";

import PFBrand from "@patternfly/patternfly/components/Brand/brand.css";
import PFButton from "@patternfly/patternfly/components/Button/button.css";
import PFDrawer from "@patternfly/patternfly/components/Drawer/drawer.css";
import PFDropdown from "@patternfly/patternfly/components/Dropdown/dropdown.css";
import PFNotificationBadge from "@patternfly/patternfly/components/NotificationBadge/notification-badge.css";
import PFPage from "@patternfly/patternfly/components/Page/page.css";
import PFBase from "@patternfly/patternfly/patternfly-base.css";
import PFDisplay from "@patternfly/patternfly/utilities/Display/display.css";

@customElement("ak-nav-buttons")
export class NavigationButtons extends WithNotifications(WithSession(AKElement)) {
    @property({ type: Boolean, reflect: true })
    notificationDrawerOpen = false;

    @property({ type: Boolean, reflect: true })
    apiDrawerOpen = false;

    @state()
    protected settingsOpen = this.#isSettingsOpen();

    @listen(RouteChangeEvent)
    @listen("hashchange")
    protected syncSettingsRouteState = () => {
        this.settingsOpen = this.#isSettingsOpen();
    };

    static styles = [
        PFBase,
        PFDisplay,
        PFBrand,
        PFPage,
        PFButton,
        PFDrawer,
        PFDropdown,
        PFNotificationBadge,
        Styles,
    ];

    #isSettingsOpen(): boolean {
        if (!isUserRoute()) {
            return false;
        }

        const [activePath] = window.location.hash.slice(1).split(ROUTE_SEPARATOR);
        return activePath === "/settings";
    }

    protected renderAPIDrawerTrigger() {
        const { apiDrawer } = this.uiConfig.enabledFeatures;

        return guard([apiDrawer], () => {
            if (!apiDrawer) {
                return nothing;
            }

            return html`<div class="pf-c-page__header-tools-item pf-m-hidden pf-m-visible-on-xl">
                <button
                    id="api-drawer-toggle-button"
                    class="pf-c-button pf-m-plain"
                    type="button"
                    aria-label=${msg("Toggle API requests drawer", {
                        id: "drawer-toggle-button-api-requests",
                    })}
                    @click=${AKDrawerChangeEvent.dispatchAPIToggle}
                >
                    <pf-tooltip
                        position="top"
                        content=${msg("API Drawer")}
                        trigger="api-drawer-toggle-button"
                    >
                        <i class="fas fa-code" aria-hidden="true"></i>
                    </pf-tooltip>
                </button>
            </div>`;
        });
    }

    protected renderNotificationDrawerTrigger() {
        const { notificationDrawer } = this.uiConfig.enabledFeatures;
        const notificationCount = this.notificationCount;

        return guard([notificationDrawer, notificationCount], () => {
            if (!notificationDrawer) {
                return nothing;
            }

            return html`<div class="pf-c-page__header-tools-item pf-m-hidden pf-m-visible-on-xl">
                <button
                    id="notification-drawer-toggle-button"
                    class="pf-c-button pf-m-plain"
                    type="button"
                    aria-label=${msg("Toggle notifications drawer", {
                        id: "drawer-toggle-button-notifications",
                    })}
                    aria-describedby="notification-count"
                    @click=${AKDrawerChangeEvent.dispatchNotificationsToggle}
                >
                    <span class="pf-c-notification-badge ${notificationCount ? "pf-m-unread" : ""}">
                        <pf-tooltip
                            position="top"
                            content=${msg("Notification Drawer", {
                                id: "drawer-invoker-tooltip-notifications",
                            })}
                            trigger="notification-drawer-toggle-button"
                        >
                            <i class="fas fa-bell" aria-hidden="true"></i>
                        </pf-tooltip>
                        <span
                            id="notification-count"
                            class="pf-c-notification-badge__count"
                            aria-live="polite"
                        >
                            ${notificationCount}
                            <span class="sr-only">unread</span>
                        </span>
                    </span>
                </button>
            </div>`;
        });
    }

    renderImpersonation() {
        if (!this.impersonating) return nothing;

        const onClick = async () => {
            await new CoreApi(DEFAULT_CONFIG).coreUsersImpersonateEndRetrieve();
            window.location.reload();
        };

        return html`&nbsp;
            <div class="pf-c-page__header-tools">
                <div class="pf-c-page__header-tools-group">
                    <ak-action-button class="pf-m-warning pf-m-small" .apiRequest=${onClick}>
                        ${msg("Stop impersonation")}
                    </ak-action-button>
                </div>
            </div>`;
    }

    #getCommunityUid(): string {
        const userSettings = this.currentUser?.settings as Record<string, unknown> | undefined;
        if (!userSettings) {
            return "";
        }

        const configuredAttr = window?.custom_user_settings?.fields?.community?.name;
        const rawValue =
            (configuredAttr ? userSettings[configuredAttr] : undefined) ??
            userSettings.communityUid;

        return typeof rawValue === "string" ? rawValue.trim() : "";
    }

    protected renderUserAccountControl() {
        const { currentUser } = this;
        if (!currentUser) {
            return nothing;
        }

        const username = currentUser.username || "";
        const communityUid = this.#getCommunityUid();
        const settingsEnabled = !!this.uiConfig?.enabledFeatures.settings;

        if (!username && !settingsEnabled) {
            return nothing;
        }

        const userDetails = username
            ? html`<span class="user-account-button__details">
                  <span class="user-account-button__primary">${username}</span>
                  ${communityUid
                      ? html`<span class="user-account-button__secondary">${communityUid}</span>`
                      : nothing}
              </span>`
            : nothing;

        if (!settingsEnabled) {
            return html`<div class="pf-c-page__header-tools-item">
                <span class="user-account-button user-account-button--static">
                    ${userDetails}
                </span>
            </div>`;
        }

        const targetHref = this.settingsOpen
            ? `${globalAK().api.base}if/user/#/library`
            : `${globalAK().api.base}if/user/#/settings`;

        const label = [
            this.settingsOpen ? msg("Close settings") : msg("Settings"),
            username ? (communityUid ? `${username} (${communityUid})` : username) : "",
        ]
            .filter(Boolean)
            .join(" — ");

        return html`<div class="pf-c-page__header-tools-item">
            <a
                class="user-account-button"
                href=${targetHref}
                aria-current=${this.settingsOpen ? "page" : nothing}
                aria-label=${label}
                title=${label}
            >
                <i class="fas fa-cog user-account-button__icon" aria-hidden="true"></i>
                ${userDetails}
            </a>
        </div>`;
    }

    render() {
        return html`<div role="presentation" class="pf-c-page__header-tools">
            <div class="pf-c-page__header-tools-group">
                ${this.renderAPIDrawerTrigger()}
                <!-- -->
                ${this.renderNotificationDrawerTrigger()}
                <div class="pf-c-page__header-tools-item">
                    <a
                        href="${globalAK().api.base}flows/-/default/invalidation/"
                        class="pf-c-button pf-m-plain"
                        aria-label=${msg("Sign out")}
                    >
                        <pf-tooltip position="top" content=${msg("Sign out")}>
                            <i class="fas fa-sign-out-alt" aria-hidden="true"></i>
                        </pf-tooltip>
                    </a>
                </div>
                <slot name="extra"></slot>
            </div>
            ${this.renderImpersonation()} ${this.renderUserAccountControl()}
        </div>`;
    }
}

declare global {
    interface HTMLElementTagNameMap {
        "ak-nav-buttons": NavigationButtons;
    }
}
