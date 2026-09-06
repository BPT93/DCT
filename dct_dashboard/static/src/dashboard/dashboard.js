/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { getPreferredTheme } from "@dct_dashboard/theme/theme";


export class DctDashboard extends Component {
    static template = "dct_dashboard.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.colorScheme = useService("color_scheme");
        this.state = useState({
            period: "month",
            theme: getPreferredTheme(),
            loading: true,
            data: null,
            error: false,
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "dct.dashboard",
                "get_dashboard_data",
                [],
                { period: this.state.period }
            );
        } catch (error) {
            this.state.error = true;
            this.notification.add(_t("The dashboard could not be loaded."), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    onPeriodChange(event) {
        this.state.period = event.target.value;
        return this.loadData();
    }

    async toggleTheme() {
        await this.colorScheme.switchColorScheme();
    }

    async openAction(xmlid) {
        await this.action.doAction(xmlid);
    }

    async openInvoice(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    formatMetric(metric) {
        return metric.kind === "currency"
            ? this.formatCurrency(metric.value)
            : this.formatNumber(metric.value);
    }

    formatCurrency(value) {
        const currency = this.state.data.company.currency;
        const numericValue = Number(value || 0);
        try {
            return new Intl.NumberFormat(undefined, {
                style: "currency",
                currency: currency.code,
                minimumFractionDigits: currency.digits,
                maximumFractionDigits: currency.digits,
            }).format(numericValue);
        } catch {
            const amount = this.formatNumber(numericValue, currency.digits);
            return currency.position === "after"
                ? `${amount} ${currency.symbol}`
                : `${currency.symbol} ${amount}`;
        }
    }

    formatNumber(value, digits = 0) {
        return new Intl.NumberFormat(undefined, {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        }).format(Number(value || 0));
    }

    changeClass(metric) {
        if (metric.change > 0) {
            return "is-positive";
        }
        if (metric.change < 0) {
            return "is-negative";
        }
        return "is-neutral";
    }

    changeIcon(metric) {
        if (metric.change > 0) {
            return "fa-arrow-up";
        }
        if (metric.change < 0) {
            return "fa-arrow-down";
        }
        return "fa-minus";
    }

    get revenueBars() {
        const rows = this.state.data.revenue_trend;
        const maximum = Math.max(...rows.map((row) => Math.abs(row.value)), 1);
        return rows.map((row) => ({
            ...row,
            height: row.value ? Math.max(6, (Math.abs(row.value) / maximum) * 100) : 2,
        }));
    }

    get pipelineRows() {
        const rows = this.state.data.sales_pipeline;
        const total = rows.reduce((sum, row) => sum + row.count, 0);
        return rows.map((row) => ({
            ...row,
            share: total ? (row.count / total) * 100 : 0,
        }));
    }
}

registry.category("actions").add("dct_dashboard.Dashboard", DctDashboard);



