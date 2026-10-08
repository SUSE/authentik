import "#flow/FormStatic";
import "#flow/components/ak-flow-card";
import "webcomponent-qr-code";
import "#types/qr-code";

import { MessageLevel } from "#common/messages";

import { showMessage } from "#elements/messages/MessageContainer";
import { SlottedTemplateResult } from "#elements/types";

import { AKFormErrors } from "#components/ak-field-errors";
import { AKLabel } from "#components/ak-label";

import { FlowUserDetails } from "#flow/FormStatic";
import { BaseStage } from "#flow/stages/base";

import {
    AuthenticatorTOTPChallenge,
    AuthenticatorTOTPChallengeResponseRequest,
} from "@goauthentik/api";

import { msg } from "@lit/localize";
import { css, CSSResult, html, nothing } from "lit";
import { customElement, state } from "lit/decorators.js";

import PFButton from "@patternfly/patternfly/components/Button/button.css";
import PFForm from "@patternfly/patternfly/components/Form/form.css";
import PFFormControl from "@patternfly/patternfly/components/FormControl/form-control.css";
import PFInputGroup from "@patternfly/patternfly/components/InputGroup/input-group.css";
import PFLogin from "@patternfly/patternfly/components/Login/login.css";
import PFTitle from "@patternfly/patternfly/components/Title/title.css";

@customElement("ak-stage-authenticator-totp")
export class AuthenticatorTOTPStage extends BaseStage<
    AuthenticatorTOTPChallenge,
    AuthenticatorTOTPChallengeResponseRequest
> {
    static styles: CSSResult[] = [
        PFLogin,
        PFForm,
        PFFormControl,
        PFInputGroup,
        PFTitle,
        PFButton,
        css`
            .qr-container {
                display: flex;
                flex-direction: column;
                place-items: center;
                gap: 5px;
            }

            .totp-details {
                width: 100%;
                --details-shadow-color: #DFD4D4FF;
                --details-bg-color: #F3EBEBFF;
            }

            .totp-details > summary {
                cursor: pointer;
                padding: 2px 6px;
                background-color: var(--details-bg-color);
                border: none;
                box-shadow: 3px 3px 4px var(--details-shadow-color);
            }

            .totp-details > div {
                background-color: var(--details-bg-color);
                padding: 2px 6px;
                margin: 0;
                box-shadow: 3px 3px 4px var(--details-shadow-color);
            }
        `,
    ];

    @state()
    protected isSmallScreen = this.calcIsSmallScreen();

    public override connectedCallback(): void {
        super.connectedCallback();

          window.addEventListener('resize', this._handleResize);
    }

    public override disconnectedCallback(): void {
      window.removeEventListener('resize', this._handleResize);
      super.disconnectedCallback();
    }

    private _handleResize = () => {
        this.isSmallScreen = this.calcIsSmallScreen();
    }

    private calcIsSmallScreen() {
        return window.innerHeight < 1000;
    }


    protected render(): SlottedTemplateResult {
        if (!this.challenge) {
            return nothing;
        }

        const totpParams = new URL(this.challenge.configUrl).searchParams

        return html`
            <ak-flow-card .challenge=${this.challenge}>
                <form class="pf-c-form" @submit=${this.submitForm}>
                    ${FlowUserDetails({challenge: this.challenge})}

                    <input type="hidden" name="otp_uri" value=${this.challenge.configUrl}/>

                    <p>
                        ${msg(
                            "Scan the QR code below using an authenticator app.",
                        )}
                    </p>

                    <div class="pf-c-form__group">
                        <div class="qr-container">
                            <qr-code
                                modulesize="${ this.isSmallScreen ? 3 : 5 }"
                                role="img"
                                aria-label=${msg("QR-Code to setup a time-based one-time password")}
                                format="png"
                                data="${this.challenge.configUrl}"
                            ></qr-code>

                            <details class="totp-details">
                                <summary>Expert setup</summary>
                                <div>
                                    ${AKLabel(
                                        {
                                            "required": false,
                                            "htmlFor": "totp-secret",
                                            "aria-label": msg("Secret"),
                                        },
                                        msg("TOTP Secret"),
                                    )}
                                    <input id="totp-secret"
                                           class="pf-c-form-control pf-m-monospace"
                                           type="text" value="${totpParams.get('secret')}"
                                           readonly/>
                                    ${AKLabel(
                                        {
                                            "required": false,
                                            "htmlFor": "totp-algo",
                                            "aria-label": msg("Algorithm"),
                                        },
                                        msg("TOTP Algorithm"),
                                    )}
                                    <input id="totp-algo"
                                           class="pf-c-form-control pf-m-monospace"
                                           type="text" value="${totpParams.get('algorithm')}"
                                           readonly/>
                                    ${AKLabel(
                                        {
                                            "required": false,
                                            "htmlFor": "totp-issuer",
                                            "aria-label": msg("Issuer"),
                                        },
                                        msg("TOTP Issuer"),
                                    )}
                                    <input id="totp-issuer"
                                           class="pf-c-form-control pf-m-monospace"
                                           type="text" value="${totpParams.get('issuer')}"
                                           readonly/>
                                    ${AKLabel(
                                        {
                                            "required": false,
                                            "htmlFor": "totp-issuer",
                                            "aria-label": msg("Period"),
                                        },
                                        msg("TOTP Period"),
                                    )}
                                    <input id="totp-period"
                                           class="pf-c-form-control pf-m-monospace"
                                           type="text" value="${totpParams.get('period')}"
                                           readonly/>
                                    ${AKLabel(
                                        {
                                            "required": false,
                                            "htmlFor": "totp-digits",
                                            "aria-label": msg("Digits"),
                                        },
                                        msg("TOTP Digits"),
                                    )}
                                    <input id="totp-digits"
                                           class="pf-c-form-control pf-m-monospace"
                                           type="text" value="${totpParams.get('digits')}"
                                           readonly/>
                                    <div style="text-align: center; margin: 10px 0;">
                                        <button
                                            type="button"
                                            class="pf-c-button pf-m-secondary pf-m-progress pf-m-in-progress"
                                            aria-label=${msg("Copy time-based one-time password configuration")}
                                            @click=${(e: Event) => {
                                                e.preventDefault();
                                                if (!this.challenge?.configUrl) return;
                                                if (!navigator.clipboard) {
                                                    showMessage({
                                                        level: MessageLevel.info,
                                                        message: this.challenge?.configUrl,
                                                    });
                                                    return;
                                                }
                                                navigator.clipboard
                                                    .writeText(this.challenge?.configUrl)
                                                    .then(() => {
                                                        showMessage(
                                                            {
                                                                level: MessageLevel.success,
                                                                message: msg("Successfully copied TOTP Config."),
                                                            },
                                                            true,
                                                        );
                                                    });
                                            }}
                                        >
                                        <span class="pf-c-button__progress"
                                        ><i class="fas fa-copy" aria-hidden="true"></i
                                        ></span>
                                            ${msg("Copy TOTP Config")}
                                        </button>
                                    </div>
                                </div>
                            </details>
                        </div>
                    </div>
                    <div class="pf-c-form__group">
                        ${AKLabel(
                            {
                                "required": true,
                                "htmlFor": "totp-code-input",
                                "aria-label": msg("Time-based one-time password"),
                            },
                            msg("TOTP Code"),
                        )}
                        <input
                            id="totp-code-input"
                            type="text"
                            name="code"
                            inputmode="numeric"
                            pattern="[0-9]*"
                            placeholder="${msg("Enter the generated code for verification...")}"
                            aria-placeholder=${msg("Type your time-based one-time password code.")}
                            autocomplete="one-time-code"
                            class="pf-c-form-control pf-m-monospace"
                            spellcheck="false"
                            required
                        />
                        ${AKFormErrors({errors: this.challenge.responseErrors?.code})}
                    </div>

                    <fieldset class="pf-c-form__group pf-m-action">
                        <legend class="sr-only">${msg("Form actions")}</legend>
                        <button
                            name="continue"
                            type="submit"
                            class="pf-c-button pf-m-primary pf-m-block"
                        >
                            ${msg("Continue")}
                        </button>
                    </fieldset>

                    <div class="pf-c-form__group">

                    </div>
                </form>
            </ak-flow-card>`;
    }
}

declare global {
    interface HTMLElementTagNameMap {
        "ak-stage-authenticator-totp": AuthenticatorTOTPStage;
    }
}
