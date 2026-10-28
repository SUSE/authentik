import { SlottedTemplateResult } from "#elements/types";

import { UserSettingsPromptStage } from "#user/user-settings/details/stages/prompt/PromptStage";

import { StagePrompt } from "@goauthentik/api";

import { msg } from "@lit/localize";
import { html, nothing, PropertyValues } from "lit";
import { customElement, query, queryAll, state } from "lit/decorators.js";

interface FieldConfig {
    geo?: {
        country?: string;
        state?: string;
    };

    community?: {
        name?: string;
        validation?: {
            regex?: string;
            message?: string;
        };
    };

    immutable?: string[];
}

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
    fieldConfig: FieldConfig = {};

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

        this.fieldConfig = window?.custom_user_settings?.fields || {};

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
                (f) => f.fieldKey === this.fieldConfig.geo?.country,
            );
            if (countryField && countryField.initialValue && !this.selectedCountry) {
                this.selectedCountry = countryField.initialValue;
            }
        }
    }

    protected override renderPromptInner(prompt: StagePrompt): SlottedTemplateResult {
        const fieldKey = prompt.fieldKey;
        const fieldId = `field-${fieldKey}`;

        if (this.fieldConfig.immutable?.includes(fieldKey) && prompt.initialValue) {
            return html`
                <input
                    type="text"
                    id=${fieldId}
                    name=${fieldKey}
                    class="pf-c-form-control"
                    readonly
                    .value=${prompt.initialValue}
                />
            `;
        }

        switch (fieldKey) {
            case this.fieldConfig.community?.name:
                return html`
                    <input
                        type="text"
                        id=${fieldId}
                        name=${fieldKey}
                        placeholder="${prompt.placeholder || ""}"
                        class="pf-c-form-control"
                        ?required=${prompt.required}
                        .value="${prompt.initialValue}"
                        pattern="${this.fieldConfig.community?.validation?.regex || "(?!)"}"
                        title="${this.fieldConfig.community?.validation?.message ||
                        "Invalid format."}"
                        autocomplete="off"
                    />
                `;

            case this.fieldConfig.geo?.country:
                return html`
                    <input
                        type="text"
                        id=${fieldId}
                        name=${fieldKey}
                        placeholder="${prompt.placeholder || "Select a country..."}"
                        class="pf-c-form-control"
                        ?required=${prompt.required}
                        .value="${prompt.initialValue}"
                        list="suse-country-list"
                        @input=${(e: Event) => {
                            this.selectedCountry = (e.target as HTMLInputElement).value;
                        }}
                        @click=${(e: Event) => {
                            const target = e.target as HTMLInputElement;
                            if (target.showPicker) target.showPicker();
                        }}
                        autocomplete="off"
                    />
                    <datalist id="suse-country-list">
                        ${this.countries.map((c) => html`<option value=${c.name}></option>`)}
                    </datalist>
                `;

            case this.fieldConfig.geo?.state:
                const countryData = this.countries.find((c) => c.name === this.selectedCountry);
                const states = countryData ? countryData.states || [] : [];

                return html`
                    <input
                        type="text"
                        id=${fieldId}
                        name=${fieldKey}
                        placeholder="${prompt.placeholder || "Select a province/state..."}"
                        class="pf-c-form-control"
                        ?required=${prompt.required}
                        .value="${prompt.initialValue}"
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

            const countryKey = this.fieldConfig.geo?.country;
            const stateKey = this.fieldConfig.geo?.state;

            if (countryKey && keys.includes(countryKey)) {
                const countryVal = data.get(countryKey)?.toString().trim() || "";
                if (countryVal && !this.countries.some((c) => c.name === countryVal)) {
                    this.sectionError = "Please select a valid Country from the list.";
                    return false;
                }
            }

            if (stateKey && keys.includes(stateKey) && this.selectedCountry) {
                const stateVal = data.get(stateKey)?.toString().trim() || "";
                const countryData = this.countries.find((c) => c.name === this.selectedCountry);
                const validStates = countryData
                    ? (countryData.states || []).map((s: any) =>
                          typeof s === "string" ? s : s.name,
                      )
                    : [];

                if (stateVal && validStates.length > 0 && !validStates.includes(stateVal)) {
                    this.sectionError = "Please select a valid Province/State from the list.";
                    return false;
                }
            }

            const communityUidKey = this.fieldConfig.community?.name;

            if (communityUidKey && keys.includes(communityUidKey)) {
                const usernameVal = data.get(communityUidKey)?.toString() || "";
                const field = this.challenge?.fields.find((f) => f.fieldKey === communityUidKey);

                const isSettingNew = !field?.initialValue && usernameVal !== "";

                if (isSettingNew) {
                    const regex = new RegExp(
                        this.fieldConfig.community?.validation?.regex || "(?!)",
                    );

                    if (!regex.test(usernameVal)) {
                        this.sectionError =
                            this.fieldConfig.community?.validation?.message || "Invalid format.";
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

        const immutableFieldsInSection = fields.filter((f) =>
            this.fieldConfig.immutable?.includes(f.fieldKey),
        );

        if (
            immutableFieldsInSection.length > 0 &&
            immutableFieldsInSection.every((f) => f.initialValue)
        ) {
            return html`
                <div class="pf-c-form__group pf-m-action" style="margin-top: 0; padding-top: 0;">
                    <p class="pf-c-form__helper-text" style="color: var(--pf-global--Color--100);">
                        <i class="fas fa-lock"></i> ${msg("These details are immutable.")}
                    </p>
                </div>
            `;
        }

        const isAddressSection = fields.some(
            (f) =>
                f.fieldKey === this.fieldConfig.geo?.country ||
                f.fieldKey === this.fieldConfig.geo?.state,
        );

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
