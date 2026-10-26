/**
 * @file Minimal typings for jQuery.
 *
 * This file provides a small subset of the jQuery typings used in authentik's
 * Simplified Flow Executor.
 *
 * Unlike the `@types/jquery` package, this package does not expose `$` as a global
 * which causes issues with WebdriverIO.
 */

declare module "jquery" {
    export function JQuery<TElement = HTMLElement>(selector: string, elementSpec : Object = {}): JQuery<TElement>;

    export namespace JQuery {
        function ajax(options: JQueryAjaxSettings): void;
    }

    export interface JQuery<TElement = HTMLElement> extends ArrayLike<TElement> {
        getElements(): TElement[];
        getElement(): TElement;
        getText(): string;
        submit(): void;
        val(value: string): JQuery<TElement>;
        html(html: string): JQuery<TElement>;
        addClass(className: string): JQuery<TElement>;
        removeClass(className: string): JQuery<TElement>;
        on(eventName: string, handler: (event: Event) => void): JQuery<TElement>;
        trigger(eventName: string): void;
        ajax(options: JQueryAjaxSettings): void;
    }

    export interface JQueryAjaxSettings {
        url: string;
        type?: string;
        data?: string;
        contentType?: string;
        dataType?: string;
        success?: (data: unknown) => void;
        error?: (data: unknown) => void;
    }

    export default JQuery;
}
