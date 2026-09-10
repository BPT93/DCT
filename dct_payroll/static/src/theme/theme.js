/** @odoo-module **/

import { cookie } from "@web/core/browser/cookie";


const VALID_THEMES = new Set(["light", "dark"]);


export function getPreferredTheme() {
    const selectedTheme = cookie.get("color_scheme");
    return VALID_THEMES.has(selectedTheme) ? selectedTheme : "light";
}


export function applyTheme(theme) {
    const selectedTheme = VALID_THEMES.has(theme) ? theme : "light";
    document.documentElement.dataset.dctTheme = selectedTheme;
    return selectedTheme;
}


applyTheme(getPreferredTheme());

