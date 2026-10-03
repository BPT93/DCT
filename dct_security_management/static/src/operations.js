/** @odoo-module **/
import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";
import { serializeDateTime } from "@web/core/l10n/dates";
import { formatFloat, formatMonetary } from "@web/views/fields/formatters";
const { DateTime } = luxon;

class OperationsBase extends Component {
    static props = { ...standardActionServiceProps };
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: false, data: null,
            date_start: DateTime.local().startOf("month").toISODate(),
            date_end: DateTime.local().toISODate(), site_id: "", company_id: "" });
    }
    async load(method, options) {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call("dct.security.dashboard", method, [], options);
            if (this.state.data.company_id) this.state.company_id = String(this.state.data.company_id);
        } catch (error) {
            this.state.error = error.data?.message || _t("Operations data could not be loaded. Check your filters and access, then retry.");
        } finally {
            this.state.loading = false;
        }
    }
    openAction(action) { return this.action.doAction(action, { onClose: () => this.refresh() }); }
    formatAmount(value, currencyId) { return formatMonetary(value, { currencyId }); }
    formatHours(value) { return formatFloat(value, { digits: [16, 2] }); }
    async openRecord(model, id) {
        if (model === "hr.employee") {
            return this.openAction(await this.orm.call("dct.security.dashboard", "get_guard_form", [id]));
        }
        return this.openAction({ type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]], target: "current" });
    }
}

export class OperationsDashboard extends OperationsBase {
    static template = "dct_security_management.Dashboard";
    setup() { super.setup(); onWillStart(() => this.refresh()); }
    refresh() {
        return this.load("get_overview", { date_start: this.state.date_start, date_end: this.state.date_end,
            site_id: Number(this.state.site_id) || false, company_id: Number(this.state.company_id) || false });
    }
    changeCompany() { this.state.site_id = ""; return this.refresh(); }
}

export class WeeklyBoard extends OperationsBase {
    static template = "dct_security_management.WeeklyBoard";
    setup() {
        super.setup(); this.state.date_start = DateTime.local().startOf("week").toISODate();
        onWillStart(() => this.refresh());
    }
    refresh() { return this.load("get_week", { date_start: this.state.date_start, site_id: Number(this.state.site_id) || false, company_id: Number(this.state.company_id) || false }); }
    async previous() { this.state.date_start = DateTime.fromISO(this.state.date_start).minus({ days: 7 }).toISODate(); await this.refresh(); }
    async next() { this.state.date_start = DateTime.fromISO(this.state.date_start).plus({ days: 7 }).toISODate(); await this.refresh(); }
    addShift(guard, day) {
        const start = DateTime.fromISO(`${day}T08:00:00`, { zone: this.state.data.timezone });
        return this.openAction({ type: "ir.actions.act_window", name: _t("New draft shift"), res_model: "dct.security.shift",
            views: [[false, "form"]], target: "new", context: {
                default_company_id: this.state.data.company_id, default_site_id: Number(this.state.site_id) || false,
                default_start: serializeDateTime(start), default_end: serializeDateTime(start.plus({ hours: 8 })),
                default_assignment_ids: [[0, 0, { employee_id: guard.id }]],
            } });
    }
}

export class SiteMap extends OperationsBase {
    static template = "dct_security_management.SiteMap";
    setup() {
        super.setup(); this.mapRef = useRef("map"); this.map = null; this.state.tileError = false;
        onWillStart(() => this.refresh());
        useEffect(() => { this.drawMap(); return () => this.removeMap(); }, () => [this.state.data, this.mapRef.el]);
        onWillUnmount(() => this.removeMap());
    }
    refresh() { this.state.tileError = false; return this.load("get_map", { company_id: Number(this.state.company_id) || false }); }
    removeMap() { if (this.map) { this.map.remove(); this.map = null; } }
    drawMap() {
        this.removeMap();
        const data = this.state.data;
        if (!this.mapRef.el || !data?.tile_url || !window.L) return;
        this.map = window.L.map(this.mapRef.el).setView([33.3152, 44.3661], 6);
        const safeAttribution = document.createElement("span"); safeAttribution.textContent = data.attribution;
        window.L.tileLayer(data.tile_url, { attribution: safeAttribution.innerHTML, maxZoom: 19 })
            .on("tileerror", () => { this.state.tileError = true; }).addTo(this.map);
        const bounds = [];
        for (const site of data.sites) {
            if (!site.has_coordinates) continue;
            const label = document.createElement("div");
            const title = document.createElement("strong"); title.textContent = site.name; label.append(title);
            const details = document.createElement("p");
            details.textContent = _t("Required: %s · Assigned: %s", site.required, site.assigned); label.append(details);
            const button = document.createElement("button"); button.type = "button"; button.className = "btn btn-sm btn-primary";
            button.textContent = _t("Open site"); button.addEventListener("click", () => this.openRecord("dct.security.site", site.id)); label.append(button);
            window.L.circleMarker([site.latitude, site.longitude], { radius: 9, color: "#1577ff", fillOpacity: 0.8 }).addTo(this.map).bindPopup(label);
            bounds.push([site.latitude, site.longitude]);
        }
        if (bounds.length) this.map.fitBounds(bounds, { padding: [25, 25], maxZoom: 14 });
    }
}

registry.category("actions").add("dct_security_management.dashboard", OperationsDashboard);
registry.category("actions").add("dct_security_management.weekly_board", WeeklyBoard);
registry.category("actions").add("dct_security_management.site_map", SiteMap);
