/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, useState } from "@odoo/owl";
import { imageUrl } from "@web/core/utils/urls";
import { getPreferredTheme } from "@dct_dashboard/theme/theme";


export class DctHome extends Component {
    static template = "dct_dashboard.Home";
    static props = { ...standardActionServiceProps };

    setup() {
        this.menuService = useService("menu");
        this.colorScheme = useService("color_scheme");
        this.menuService.setCurrentMenu(this.menuService.getMenu("root"));
        this.state = useState({ theme: getPreferredTheme() });
        this.openApp = this.openApp.bind(this);
        this.toggleTheme = this.toggleTheme.bind(this);
    }

    get companyName() {
        return user.activeCompany?.name || _t("Company");
    }

    get companyLogoUrl() {
        return imageUrl("res.company", user.activeCompany.id, "logo_web");
    }

    get allApps() {
        return this.menuService.getApps().filter((app) => this.getLaunchMenu(app));
    }

    get apps() {
        return this.allApps;
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

    async openApp(app) {
        const target = this.getLaunchMenu(app);
        if (target) {
            await this.menuService.selectMenu(target);
        }
    }

    async toggleTheme() {
        await this.colorScheme.switchColorScheme();
    }
}

registry.category("actions").add("dct_dashboard.home", DctHome);


