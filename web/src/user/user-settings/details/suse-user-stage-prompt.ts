import { SlottedTemplateResult } from "#elements/types";

import { UserSettingsPromptStage } from "#user/user-settings/details/stages/prompt/PromptStage";

import { StagePrompt } from "@goauthentik/api";

import { msg } from "@lit/localize";
import { html, nothing, PropertyValues } from "lit";
import { customElement, query, queryAll, state } from "lit/decorators.js";

interface GeoState {
    name: string;
}

interface GeoCountry {
    name: string;
    states: GeoState[] | string[];
}

@customElement("suse-user-stage-prompt")
export class SuseUserStagePrompt extends UserSettingsPromptStage {
    @state()
    countries: GeoCountry[] = [];

    @state()
    selectedCountry: string = "";

    @state()
    sectionError: string = "";

    @query("form")
    private form?: HTMLFormElement;

    @queryAll("form input")
    private formInputs!: NodeListOf<HTMLInputElement>;

    connectedCallback() {
        super.connectedCallback();

        const geo_data_url = window?.geo_data_url;
        if (!geo_data_url) {
            console.warn(`Geo data not configured, address settings experience will be degraded.`);
            return;
        }

        fetch(geo_data_url)
            .then((res) => res.json())
            .then((data) => {
                const countriesList = data.data ? data.data : data;
                if (Array.isArray(countriesList)) {
                    this.countries = countriesList;
                }
            })
            .catch((err) =>
                console.warn(`Failed to load geographic data from ${geo_data_url}`, err),
            );
    }

    updated(changedProperties: PropertyValues) {
        super.updated(changedProperties);
        if (changedProperties.has("challenge") && this.challenge) {
            const countryField = this.challenge.fields.find(
                (f) => f.fieldKey === "attributes.address.country",
            );
            if (countryField && countryField.initialValue && !this.selectedCountry) {
                this.selectedCountry = countryField.initialValue;
            }
        }
    }

    protected override renderPromptInner(prompt: StagePrompt): SlottedTemplateResult {
        const fieldId = `field-${prompt.fieldKey}`;
        const isCountry = prompt.fieldKey === "attributes.address.country";
        const isState = prompt.fieldKey === "attributes.address.state";
        const isCommunity = prompt.fieldKey === "attributes.communityUid";

        if (isCommunity) {
            if (prompt.initialValue) {
                return html`
                    <input
                        type="text"
                        id=${fieldId}
                        name=${prompt.fieldKey}
                        class="pf-c-form-control"
                        readonly
                        .value=${prompt.initialValue}
                    />
                `;
            } else {
                return html`
                    <input
                        type="text"
                        id=${fieldId}
                        name=${prompt.fieldKey}
                        placeholder=${prompt.placeholder || ""}
                        class="pf-c-form-control"
                        ?required=${prompt.required}
                        .value=${prompt.initialValue}
                        pattern="^[a-zA-Z0-9_.-]{3,}\b$"
                        title="At least 3 characters. Only letters, numbers, dots, dashes, and underscores allowed."
                        autocomplete="off"
                    />
                `;
            }
        }

        if (isCountry) {
            return html`
                <input
                    type="text"
                    id=${fieldId}
                    name=${prompt.fieldKey}
                    placeholder=${prompt.placeholder || "Select a country..."}
                    class="pf-c-form-control"
                    ?required=${prompt.required}
                    .value=${prompt.initialValue}
                    list="suse-country-list"
                    @input=${(e: Event) => {
                        this.selectedCountry = (e.target as HTMLInputElement).value;
                    }}
                    @click=${(e: Event) => {
                        // open selection immediately if field is selected
                        const target = e.target as HTMLInputElement;
                        if (target.showPicker) target.showPicker();
                    }}
                    autocomplete="off"
                />
                <datalist id="suse-country-list">
                    ${this.countries.map((c) => html`<option value=${c.name}></option>`)}
                </datalist>
            `;
        }

        if (isState) {
            const countryData = this.countries.find((c) => c.name === this.selectedCountry);
            const states = countryData ? countryData.states || [] : [];
            return html`
                <input
                    type="text"
                    id=${fieldId}
                    name=${prompt.fieldKey}
                    placeholder=${prompt.placeholder || "Select a state/province..."}
                    class="pf-c-form-control"
                    ?required=${prompt.required}
                    .value=${prompt.initialValue}
                    list="suse-state-list"
                    @click=${(e: Event) => {
                        const target = e.target as HTMLInputElement;
                        if (target.showPicker) target.showPicker();
                    }}
                    autocomplete="off"
                />
                <datalist id="suse-state-list">
                    ${states.map((s) => {
                        const val = typeof s === "string" ? s : s.name;
                        return html`<option value=${val}></option>`;
                    })}
                </datalist>
            `;
        }

        return super.renderPromptInner(prompt);
    }

    public submitForm = async (event?: SubmitEvent, defaults?: any): Promise<boolean> => {
        event?.preventDefault();
        this.sectionError = "";

        if (this.form) {
            const data = new FormData(this.form);
            const keys = this.challenge?.fields.map((f) => f.fieldKey) || [];
            const values = keys.map((k) => data.get(k)?.toString().trim() || "");
            const filledCount = values.filter((v) => v !== "").length;

            if (filledCount > 0 && filledCount < keys.length) {
                this.sectionError = "All fields in this section must be filled.";
                return false;
            }

            if (filledCount > 0) {
                const countryKey = keys.find((k) => k.endsWith("-address-country"));
                const stateKey = keys.find((k) => k.endsWith("-address-state"));

                const countryVal = countryKey ? data.get(countryKey)?.toString().trim() : null;
                const stateVal = stateKey ? data.get(stateKey)?.toString().trim() : null;

                if (countryVal && !this.countries.some((c) => c.name === countryVal)) {
                    this.sectionError = "Please select a valid Country from the list.";
                    return false;
                }

                if (stateVal && this.selectedCountry) {
                    const countryData = this.countries.find((c) => c.name === this.selectedCountry);
                    const validStates = countryData
                        ? (countryData.states || []).map((s: any) =>
                              typeof s === "string" ? s : s.name,
                          )
                        : [];

                    if (validStates.length > 0 && !validStates.includes(stateVal)) {
                        this.sectionError = "Please select a valid Province/State from the list.";
                        return false;
                    }
                }
            }

            // this attribute is quite implementation specific, but probably not worth making configurable
            const communityUidKey = "attributes.communityUid";

            if (keys.includes(communityUidKey)) {
                const usernameVal = data.get(communityUidKey) || "";
                const field = this.challenge?.fields.find((f) => f.fieldKey === communityUidKey);

                const isSettingNew = !field?.initialValue && usernameVal !== "";

                if (isSettingNew) {
                    if (!/^[a-zA-Z0-9_.-]{3,}\b$/.test(usernameVal)) {
                        this.sectionError = "A community username must consist of at least 3 characters - letters, numbers, dots, dashes, and underscores are allowed, but dashes not at the end.";
                        return false;
                    }

                    const confirmed = window.confirm(
                        msg(
                            `Are you sure you want to set your community username to "${usernameVal}"?\n\nOnce saved, this information cannot be changed.`,
                        ),
                    );

                    if (!confirmed) {
                        return false;
                    }
                }
            }
        }

        const payload: Record<string, unknown> = defaults || {};
        if (this.form) {
            const data = new FormData(this.form);
            for (const [key, value] of data.entries()) {
                payload[key] = value;
            }
        }

        return (
            this.host?.submit(payload).then(async (successful) => {
                if (successful) {
                    await this.onSubmitSuccess?.(payload);
                } else {
                    await this.onSubmitFailure?.(payload);
                }
                return successful;
            }) ?? Promise.resolve(false)
        );
    };

    clearForm = () => {
        if (this.form) {
            this.formInputs.forEach((i) => (i.value = ""));
            this.selectedCountry = "";
            this.sectionError = "";
        }
    };

    protected override renderContinue(): SlottedTemplateResult {
        const fields = this.challenge?.fields || [];
        const isAddressSection = fields.some((f) => f.fieldKey.includes("address"));
        const isCommunitySection = fields.some((f) => f.fieldKey.includes("community"));
        const allCommunityFieldsSet =
            isCommunitySection &&
            fields.every((f) => f.fieldKey.includes("community") && f.initialValue);

        // community field is immutable in self-service - this hides the button - the write should be guarded by policy
        if (allCommunityFieldsSet) {
            return html`
                <div class="pf-c-form__group pf-m-action" style="margin-top: 0; padding-top: 0;">
                    <p class="pf-c-form__helper-text" style="color: var(--pf-global--Color--100);">
                        <i class="fas fa-lock"></i> ${msg("These details are immutable.")}
                    </p>
                </div>
            `;
        }

        return html`
            ${this.sectionError
                ? html`
                      <div class="pf-c-alert pf-m-danger pf-m-inline" style="margin-bottom: 1rem;">
                          <div class="pf-c-alert__icon">
                              <i class="fas fa-exclamation-circle" aria-hidden="true"></i>
                          </div>
                          <h4 class="pf-c-alert__title">${this.sectionError}</h4>
                      </div>
                  `
                : nothing}
            <div class="pf-c-form__group pf-m-action" style="margin-top: 0; padding-top: 0;">
                <div class="pf-c-form__horizontal-group">
                    <div class="pf-c-form__actions">
                        <button name="continue" type="submit" class="pf-c-button pf-m-primary">
                            ${msg("Save")}
                        </button>
                        ${isAddressSection
                            ? html`
                                  <button
                                      type="button"
                                      class="pf-c-button pf-m-secondary"
                                      @click=${this.clearForm}
                                  >
                                      ${msg("Clear")}
                                  </button>
                              `
                            : nothing}
                    </div>
                </div>
            </div>
        `;
    }
}
