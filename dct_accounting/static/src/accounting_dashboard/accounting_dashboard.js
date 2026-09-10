/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { getPreferredTheme } from "@dct_accounting/theme/theme";


export class DctAccountingDashboard extends Component {
    static template = "dct_accounting.Dashboard";
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
                "dct.accounting.dashboard",
                "get_dashboard_data",
                [],
                { period: this.state.period }
            );
        } catch (error) {
            this.state.error = true;
            this.notification.add(_t("The accounting dashboard could not be loaded."), { type: "danger" });
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
        this.state.theme = getPreferredTheme();
    }

    async openAction(xmlid) {
        await this.action.doAction(xmlid);
    }

    async openMove(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
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

    metricTone(metric) {
        if (metric.change === null || metric.change === 0) {
            return "is-neutral";
        }
        const improved = metric.id === "expenses" ? metric.change < 0 : metric.change > 0;
        return improved ? "is-positive" : "is-negative";
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

    get profitBars() {
        const rows = this.state.data.profit_trend;
        const maximum = Math.max(
            ...rows.flatMap((row) => [Math.abs(row.revenue), Math.abs(row.expenses)]),
            1
        );
        return rows.map((row) => ({
            ...row,
            revenueHeight: row.revenue ? Math.max(5, (Math.abs(row.revenue) / maximum) * 100) : 2,
            expenseHeight: row.expenses ? Math.max(5, (Math.abs(row.expenses) / maximum) * 100) : 2,
        }));
    }

    agingRows(kind) {
        const rows = kind === "receivable"
            ? this.state.data.receivable_aging
            : this.state.data.payable_aging;
        const maximum = Math.max(...rows.map((row) => row.value), 1);
        return rows.map((row) => ({
            ...row,
            width: row.value ? Math.max(2, (row.value / maximum) * 100) : 0,
        }));
    }
}

registry.category("actions").add("dct_accounting.Dashboard", DctAccountingDashboard);



