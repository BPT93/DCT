/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onWillUnmount } from "@odoo/owl";


export class DctHome extends Component {
    static template = "dct_dashboard.Home";
    static props = { ...standardActionServiceProps };

    setup() {
        this.menuService = useService("menu");
        this.commandService = useService("command");
        this.menuService.setCurrentMenu(this.menuService.getMenu("root"));
        this.openApp = this.openApp.bind(this);
        this.onGlobalKeydown = this.onGlobalKeydown.bind(this);
        onMounted(() => document.addEventListener("keydown", this.onGlobalKeydown));
        onWillUnmount(() => document.removeEventListener("keydown", this.onGlobalKeydown));
    }

    get allApps() {
        return this.menuService.getApps().filter((app) => this.getLaunchMenu(app));
    }

    onGlobalKeydown(event) {
        if (
            event.defaultPrevented ||
            event.isComposing ||
            event.ctrlKey ||
            event.altKey ||
            event.metaKey ||
            event.shiftKey ||
            event.code !== "Space" ||
            this.isInteractiveTarget(event.target)
        ) {
            return;
        }
        event.preventDefault();
        this.commandService.openMainPalette({ searchValue: "/" });
    }

    isInteractiveTarget(target) {
        return target instanceof Element && Boolean(
            target.closest(
                "input, textarea, select, button, a, [contenteditable='true'], [role='textbox']"
            )
        );
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
}

registry.category("actions").add("dct_dashboard.home", DctHome);


