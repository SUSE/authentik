import "#flow/components/suse-ak-banner";
import "./suse-user-stage-prompt";

import { SlottedTemplateResult } from "#elements/types";

import { UserSettingsFlowExecutor } from "#user/user-settings/details/UserSettingsFlowExecutor";

import { StageHost } from "#flow/stages/base";

import { RedirectChallenge } from "@goauthentik/api";

import { html, nothing, TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";

@customElement("suse-user-settings-flow-executor")
export class SuseUserSettingsFlowExecutor extends UserSettingsFlowExecutor {
    @property({ type: String })
    sectionTitle = "";

    @property({ type: String })
    bannerKey?: string;

    @state()
    hasSubmittedOnce = false;

    submit(payload?: any): Promise<boolean> {
        this.hasSubmittedOnce = true;
        return super.submit(payload);
    }

    renderChallenge(): SlottedTemplateResult {
        if (this.challenge?.component === "ak-stage-prompt") {
            return html`<suse-user-stage-prompt
                .host=${this as StageHost}
                .challenge=${this.challenge}
            ></suse-user-stage-prompt>`;
        }
        return super.renderChallenge();
    }

    render(): TemplateResult | typeof nothing {
        if (this.challenge?.component === "ak-stage-flow-error") {
            this.style.display = "none";
            return nothing;
        }

        const isInstantRedirect =
            this.challenge?.component === "xak-flow-redirect" &&
            (this.challenge as RedirectChallenge).to === "/";

        if ((!this.hasSubmittedOnce && isInstantRedirect) || (!this.flowSlug && !this.loading)) {
            this.style.display = "none";
            return nothing;
        }

        this.style.display = "";

        return html` <div class="pf-c-card">
            <div class="pf-c-card__title">${this.sectionTitle}</div>
            <div class="pf-c-card__body">
                ${this.bannerKey
                    ? html`<suse-ak-banner
                          bannerKey=${this.bannerKey}
                          style="display: block; margin-bottom: 1rem;"
                      ></suse-ak-banner>`
                    : nothing}
                ${this.renderChallengeWrapper()}
            </div>
        </div>`;
    }
}
