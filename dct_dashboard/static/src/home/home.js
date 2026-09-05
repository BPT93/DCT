/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { imageUrl } from "@web/core/utils/urls";
import { getPreferredTheme, saveTheme } from "@dct_dashboard/theme/theme";


export class DctHome extends Component {
    static template = "dct_dashboard.Home";
    static props = { ...standardActionServiceProps };

    setup() {
        this.menuService = useService("menu");
        this.menuService.setCurrentMenu(this.menuService.getMenu("root"));
        this.searchInput = useRef("searchInput");
        this.state = useState({ search: "", theme: getPreferredTheme() });
        this.openApp = this.openApp.bind(this);
        this.clearSearch = this.clearSearch.bind(this);
        onMounted(() => this.searchInput.el?.focus());
    }

    get userName() {
        return user.name || _t("there");
    }

    get companyName() {
        return user.activeCompany?.name || _t("Company");
    }

    get companyLogoUrl() {
        return imageUrl("res.company", user.activeCompany.id, "logo_web");
    }

    get greeting() {
        const hour = new Date().getHours();
        if (hour < 12) {
            return _t("Good morning");
        }
        if (hour < 18) {
            return _t("Good afternoon");
        }
        return _t("Good evening");
    }

    get allApps() {
        return this.menuService.getApps().filter((app) => this.getLaunchMenu(app));
    }

    get apps() {
        const query = this.state.search.trim().toLocaleLowerCase();
        if (!query) {
            return this.allApps;
        }
        return this.allApps.filter((app) => app.name.toLocaleLowerCase().includes(query));
    }

    getLaunchMenu(menu) {
        if (menu.actionID) {
            return menu;
        }
        for (const child of this.menuService.getMenuAsTree(menu.id).childrenTree) {
            const target = this.getLaunchMenu(child);
            if (target) {
                return target;
            }
        }
        return null;
    }

    appInitials(name) {
        return (name || "?")
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0])
            .join("")
            .toUpperCase();
    }

    appPreview(app) {
        const names = this.menuService
            .getMenuAsTree(app.id)
            .childrenTree.slice(0, 3)
            .map((child) => child.name);
        return names.length ? names.join(" · ") : _t("Open application");
    }

    async openApp(app) {
        const target = this.getLaunchMenu(app);
        if (target) {
            await this.menuService.selectMenu(target);
        }
    }

    clearSearch() {
        this.state.search = "";
        this.searchInput.el?.focus();
    }

    toggleTheme() {
        this.state.theme = saveTheme(this.state.theme === "dark" ? "light" : "dark");
    }
}

registry.category("actions").add("dct_dashboard.home", DctHome);


