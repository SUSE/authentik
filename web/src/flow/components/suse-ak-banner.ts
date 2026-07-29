import { CSSResult, html, TemplateResult, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { AKElement } from "#elements/Base";
import PFBase from "@patternfly/patternfly/patternfly-base.css";
import PFAlert from "@patternfly/patternfly/components/Alert/alert.css";

interface BannerLine {
    text: string;
    href?: string;
}

@customElement("suse-ak-banner")
export class Banner extends AKElement {
    static styles: CSSResult[] = [
        PFBase,
        PFAlert
    ];

    @property({ type: String })
    recoveryUrl?: string;

    @state()
    bannerLines: BannerLine[] = [];

    @state()
    bannerType: string;

    connectedCallback() {
        super.connectedCallback();

        const banner = window.custom_banners?.login;
        if (!banner) {
            return;
        }

        if (banner.flows) {
            // use same logic as flowSlug in FlowExecutor
            const flow = window.location.pathname.split("/")[3];
            if (!flow || !banner.flows.includes(flow)) {
                return;
            }
        }

        this.bannerType = banner.type || "info";

        this.bannerLines = (banner.lines || [])
            .filter(line => line.text)
            .map(line => ({
                text: line.text,
                href: line.href || undefined
            }));
    }

    #renderLine(line: BannerLine) {
        let href = line.href;

        // Expand special value 'recovery' to recovery flow link if one is available
        if (href === "recovery") {
            if (!this.recoveryUrl) {
                return nothing;
            }
            href = this.recoveryUrl;
        }

        if (href) {
            return html`<a href="${href}" style="font-weight: 600">${line.text}</a>`;
        }

        return line.text;
    }

    render(): TemplateResult | typeof nothing {
        if (this.bannerLines.length === 0) return nothing;

        return html`
            <div class="pf-c-alert pf-m-${this.bannerType} pf-m-inline" aria-label="Banner">
                <div class="pf-c-alert__icon">
                    <i class="fas fa-fw ${this.bannerType === 'warning' ? 'fa-exclamation-triangle' : 'fa-info-circle'}" aria-hidden="true"></i>
                </div>

                <!-- Treat first line as title -->
                <div class="pf-c-alert__title">
                    <span class="sr-only">Info:</span>
                    ${this.#renderLine(this.bannerLines[0])}
                </div>

                ${this.bannerLines.length > 1
                    ? html`
                        <div class="pf-c-alert__description">
                            ${this.bannerLines.slice(1).map((line: BannerLine, index: number, arr: BannerLine[]) => html`
                                ${this.#renderLine(line)}
                                ${index < arr.length - 1 ? html`<br />` : nothing}
                            `)}
                        </div>
                      `
                    : nothing}
            </div>
        `;
    }
}

declare global {
    interface HTMLElementTagNameMap {
        "suse-ak-banner": Banner;
    }
}
