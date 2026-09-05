/** @odoo-module **/

import { browser } from "@web/core/browser/browser";


const THEME_STORAGE_KEY = "dct.color_scheme";
const VALID_THEMES = new Set(["light", "dark"]);


export function getPreferredTheme() {
    try {
        const storedTheme = browser.localStorage.getItem(THEME_STORAGE_KEY);
        if (VALID_THEMES.has(storedTheme)) {
            return storedTheme;
        }
    } catch {
        // Storage may be unavailable in privacy-restricted browser contexts.
    }
    return browser.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}


export function applyTheme(theme) {
    const selectedTheme = VALID_THEMES.has(theme) ? theme : "light";
    document.documentElement.dataset.dctTheme = selectedTheme;
    document.documentElement.style.colorScheme = selectedTheme;
    return selectedTheme;
}


export function saveTheme(theme) {
    const selectedTheme = applyTheme(theme);
    try {
        browser.localStorage.setItem(THEME_STORAGE_KEY, selectedTheme);
    } catch {
        // The active screen still changes even when persistence is unavailable.
    }
    return selectedTheme;
}


applyTheme(getPreferredTheme());
