import "#flow/FormStatic";
import "#flow/components/ak-flow-card";

import { globalAK } from "#common/global";

import { FlowUserDetails } from "#flow/FormStatic";
import { BaseStage } from "#flow/stages/base";

import { AccessDeniedChallenge, FlowChallengeResponseRequest } from "@goauthentik/api";

import { msg } from "@lit/localize";
import { CSSResult, html, nothing, TemplateResult } from "lit";
import { customElement } from "lit/decorators.js";

import PFButton from "@patternfly/patternfly/components/Button/button.css";
import PFForm from "@patternfly/patternfly/components/Form/form.css";
import PFFormControl from "@patternfly/patternfly/components/FormControl/form-control.css";
import PFLogin from "@patternfly/patternfly/components/Login/login.css";
import PFTitle from "@patternfly/patternfly/components/Title/title.css";

@customElement("ak-stage-access-denied")
export class AccessDeniedStage extends BaseStage<
    AccessDeniedChallenge,
    FlowChallengeResponseRequest
> {
    static styles: CSSResult[] = [
        // ---
        PFLogin,
        PFForm,
        PFTitle,
        PFFormControl,
        PFButton,
    ];

    render(): TemplateResult {
        let errorConfig = this.challenge?.errorMessage;
        let errorData;
        let message;
        let icon = "fa-times";
        let title = msg("Request has been denied.");
        let buttons = null;

        // JSON.parse() will not accept unquoted strings, but we still want to
        // differentiate between a broken JSON object and a simple string
        // instead of just assuming a string on all parsing errors
        if (!(errorConfig.startsWith("{") && errorConfig.endsWith("}"))) {
            errorConfig = `"${errorConfig}"`;
        }

        try {
            errorData = JSON.parse(errorConfig);
        } catch (error) {
            console.log(`Failed to parse error data - error: ${error}.`);
            errorData =
                "We failed to serve more useful information about this error. This should not happen.";
        }

        switch (typeof errorData) {
            case "object":
                switch (String(errorData.type)) {
                    case "IncompleteProfile":
                        message = errorData.message || "";
                        icon = "fa-user-edit";
                        title = errorData.title || "Incomplete profile";
                        buttons = html`
                            <fieldset class="pf-c-form__group pf-m-action">
                                <legend class="sr-only">${msg("Form actions")}</legend>
                                <a
                                    class="pf-c-button pf-m-primary pf-m-block"
                                    href="${globalAK().api.base}if/user/#/settings"
                                >
                                    Go to profile settings
                                </a>
                                <a
                                    class="pf-c-button pf-m-secondary pf-m-block"
                                    href="${globalAK().api.base}if/user/#/library"
                                >
                                    Go to dashboard
                                </a>
                            </fieldset>
                        `;

                        break;

                    default:
                        console.log(`Unknown error data type "${errorData.type}".`);

                        break;
                }

                break;

            case "string":
                message = errorData;

                break;
        }

        return html`<ak-flow-card .challenge=${this.challenge}>
            <form class="pf-c-form">
                ${FlowUserDetails({ challenge: this.challenge })}

                <ak-empty-state icon=${icon}>
                    <span>${title}</span>
                    ${errorConfig
                        ? html`
                              <div slot="body">
                                  <p>${message}</p>
                              </div>
                          `
                        : nothing}
                </ak-empty-state>

                ${buttons ||
                (this.challenge?.flowInfo?.cancelUrl
                    ? html`<fieldset class="pf-c-form__group pf-m-action">
                          <legend class="sr-only">${msg("Form actions")}</legend>
                          <a
                              class="pf-c-button pf-m-primary pf-m-block"
                              href=${this.challenge.flowInfo?.cancelUrl}
                          >
                              ${msg("Go back", {
                                  id: "flow.navigation.go-back",
                              })}
                          </a>
                      </fieldset>`
                    : nothing)}
            </form>
        </ak-flow-card>`;
    }
}

declare global {
    interface HTMLElementTagNameMap {
        "ak-stage-access-denied": AccessDeniedStage;
    }
}
