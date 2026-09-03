/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillStart, useState } from "@odoo/owl";


const REPORT_TYPES = [
    ["profit_loss", "Profit & Loss"],
    ["balance_sheet", "Balance Sheet"],
    ["trial_balance", "Trial Balance"],
    ["general_ledger", "General Ledger"],
    ["partner_ledger", "Partner Ledger"],
    ["journal_ledger", "Journal Ledger"],
];

function toISO(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function currentMonth() {
    const today = new Date();
    return {
        dateFrom: toISO(new Date(today.getFullYear(), today.getMonth(), 1)),
        dateTo: toISO(today),
    };
}


export class DctInteractiveReport extends Component {
    static template = "dct_accounting.InteractiveReport";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const actionContext = this.props.action.context || {};
        const reportType = actionContext.report_type || actionContext.default_report_type || "profit_loss";
        const period = currentMonth();
        this.reportTypes = REPORT_TYPES;
        this.state = useState({
            loading: true,
            dateOpen: false,
            journalOpen: false,
            lineSearch: "",
            collapsed: {},
            periodPreset: "month",
            options: {
                wizard_id: false,
                report_type: reportType,
                date_from: period.dateFrom,
                date_to: period.dateTo,
                target_move: "posted",
                comparison: "none",
                journal_ids: [],
                show_zero: false,
            },
            data: {
                report_name: "",
                company_name: "",
                comparison: "none",
                comparison_label: "",
                currency: {},
                journals: [],
                lines: [],
            },
        });

        for (const method of [
            "loadReport",
            "applyFilters",
            "resetFilters",
            "toggleJournals",
            "onPeriodPresetChange",
            "onReportTypeChange",
            "onDateFromChange",
            "onDateToChange",
            "onTargetMoveChange",
            "onComparisonChange",
            "onShowZeroChange",
            "toggleJournal",
            "clearJournals",
            "toggleSection",
            "unfoldAll",
            "foldAll",
            "openLine",
            "printPdf",
            "exportXlsx",
        ]) {
            this[method] = this[method].bind(this);
        }
        onWillStart(() => this.loadReport());
    }

    get isStatement() {
        return ["profit_loss", "balance_sheet"].includes(this.state.data.report_type);
    }

    get hasComparison() {
        return this.state.data.comparison && this.state.data.comparison !== "none";
    }

    get periodLabel() {
        if (this.state.data.report_type === "balance_sheet") {
            return `${_t("As of")} ${this.formatDate(this.state.options.date_to)}`;
        }
        return `${this.formatDate(this.state.options.date_from)} – ${this.formatDate(this.state.options.date_to)}`;
    }

    get targetMoveLabel() {
        return this.state.options.target_move === "posted" ? _t("Posted Entries") : _t("All Entries");
    }

    get comparisonLabel() {
        const labels = {
            none: _t("No Comparison"),
            previous_period: _t("Previous Period"),
            previous_year: _t("Previous Year"),
        };
        return labels[this.state.options.comparison] || labels.none;
    }

    get journalLabel() {
        const count = this.state.options.journal_ids.length;
        if (!count) {
            return _t("All Journals");
        }
        if (count === 1) {
            const journal = this.state.data.journals.find(
                (item) => item.id === this.state.options.journal_ids[0]
            );
            return journal?.code || journal?.name || _t("1 Journal");
        }
        return _t("%s Journals", count);
    }

    get sectionKeys() {
        return this.state.data.lines
            .filter((line) => line.line_type === "section")
            .map((line) => line.section_key);
    }

    get visibleLines() {
        const query = this.state.lineSearch.trim().toLocaleLowerCase();
        const lines = this.state.data.lines;
        const matchingSections = new Set();
        if (query) {
            for (const line of lines) {
                if (`${line.code} ${line.name}`.toLocaleLowerCase().includes(query)) {
                    matchingSections.add(line.section_key);
                }
            }
        }
        return lines.filter((line) => {
            if (
                line.line_type === "account" &&
                line.section_key &&
                this.state.collapsed[line.section_key]
            ) {
                return false;
            }
            if (!query) {
                return true;
            }
            const matches = `${line.code} ${line.name}`.toLocaleLowerCase().includes(query);
            return matches || (line.line_type === "section" && matchingSections.has(line.section_key));
        });
    }

    async loadReport() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "dct.account.report.wizard",
                "get_report_data",
                [{ ...this.state.options }]
            );
            this.state.data = data;
            this.state.options.wizard_id = data.wizard_id;
            this.state.options.report_type = data.report_type;
            this.state.options.date_from = data.date_from;
            this.state.options.date_to = data.date_to;
            this.state.options.target_move = data.target_move;
            this.state.options.comparison = data.comparison;
            this.state.options.show_zero = data.show_zero;
            this.state.options.journal_ids = data.journals
                .filter((journal) => journal.selected)
                .map((journal) => journal.id);
        } catch (error) {
            this.notification.add(_t("The accounting report could not be loaded."), {
                type: "danger",
            });
            throw error;
        } finally {
            this.state.loading = false;
        }
    }

    async applyFilters() {
        this.state.dateOpen = false;
        this.state.journalOpen = false;
        await this.loadReport();
    }

    async resetFilters() {
        const period = currentMonth();
        Object.assign(this.state.options, {
            date_from: period.dateFrom,
            date_to: period.dateTo,
            target_move: "posted",
            comparison: "none",
            journal_ids: [],
            show_zero: false,
        });
        this.state.periodPreset = "month";
        await this.applyFilters();
    }

    toggleJournals() {
        this.state.journalOpen = !this.state.journalOpen;
        this.state.dateOpen = false;
    }

    async onPeriodPresetChange(event) {
        const preset = event.target.value;
        if (preset === "custom") {
            this.state.periodPreset = "custom";
            this.state.dateOpen = true;
            this.state.journalOpen = false;
            return;
        }
        await this.setPeriod(preset);
    }

    async setPeriod(preset) {
        const today = new Date();
        let dateFrom;
        let dateTo = today;
        if (preset === "month") {
            dateFrom = new Date(today.getFullYear(), today.getMonth(), 1);
        } else if (preset === "quarter") {
            const quarterMonth = Math.floor(today.getMonth() / 3) * 3;
            dateFrom = new Date(today.getFullYear(), quarterMonth, 1);
        } else if (preset === "year") {
            dateFrom = new Date(today.getFullYear(), 0, 1);
        } else if (preset === "last_month") {
            dateFrom = new Date(today.getFullYear(), today.getMonth() - 1, 1);
            dateTo = new Date(today.getFullYear(), today.getMonth(), 0);
        } else {
            this.state.periodPreset = "custom";
            return;
        }
        this.state.periodPreset = preset;
        this.state.options.date_from = toISO(dateFrom);
        this.state.options.date_to = toISO(dateTo);
        await this.applyFilters();
    }

    async onReportTypeChange(event) {
        this.state.options.report_type = event.target.value;
        this.state.options.wizard_id = false;
        this.state.collapsed = {};
        await this.loadReport();
    }

    onDateFromChange(event) {
        this.state.options.date_from = event.target.value;
        this.state.periodPreset = "custom";
    }

    onDateToChange(event) {
        this.state.options.date_to = event.target.value;
        this.state.periodPreset = "custom";
    }

    async onTargetMoveChange(event) {
        this.state.options.target_move = event.target.value;
        await this.loadReport();
    }

    async onComparisonChange(event) {
        this.state.options.comparison = event.target.value;
        await this.loadReport();
    }

    async onShowZeroChange(event) {
        this.state.options.show_zero = event.target.checked;
        await this.loadReport();
    }

    toggleJournal(journalId) {
        const selected = new Set(this.state.options.journal_ids);
        if (selected.has(journalId)) {
            selected.delete(journalId);
        } else {
            selected.add(journalId);
        }
        this.state.options.journal_ids = [...selected];
    }

    clearJournals() {
        this.state.options.journal_ids = [];
    }

    toggleSection(sectionKey) {
        this.state.collapsed[sectionKey] = !this.state.collapsed[sectionKey];
    }

    unfoldAll() {
        for (const sectionKey of this.sectionKeys) {
            this.state.collapsed[sectionKey] = false;
        }
    }

    foldAll() {
        for (const sectionKey of this.sectionKeys) {
            this.state.collapsed[sectionKey] = true;
        }
    }

    rowCurrentAmount(line) {
        return this.isStatement ? line.balance : line.ending_balance;
    }

    formatCurrency(value) {
        if (!value) {
            return "—";
        }
        const currency = this.state.data.currency;
        try {
            return new Intl.NumberFormat(undefined, {
                style: "currency",
                currency: currency.name,
                currencyDisplay: "symbol",
                minimumFractionDigits: currency.decimal_places,
                maximumFractionDigits: currency.decimal_places,
            }).format(value);
        } catch {
            const amount = new Intl.NumberFormat(undefined, {
                minimumFractionDigits: currency.decimal_places || 2,
                maximumFractionDigits: currency.decimal_places || 2,
            }).format(value);
            return currency.position === "after"
                ? `${amount} ${currency.symbol || currency.name}`
                : `${currency.symbol || currency.name} ${amount}`;
        }
    }

    formatDate(value) {
        if (!value) {
            return "";
        }
        return new Intl.DateTimeFormat(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
        }).format(new Date(`${value}T00:00:00`));
    }

    async openLine(line) {
        if (!line.can_drilldown) {
            return;
        }
        const action = await this.orm.call(
            "dct.account.report.line",
            "action_open_journal_items",
            [[line.id]]
        );
        await this.action.doAction(action);
    }

    async printPdf() {
        const action = await this.orm.call(
            "dct.account.report.wizard",
            "action_print_pdf",
            [[this.state.data.wizard_id]]
        );
        await this.action.doAction(action);
    }

    async exportXlsx() {
        const action = await this.orm.call(
            "dct.account.report.wizard",
            "action_export_xlsx",
            [[this.state.data.wizard_id]]
        );
        await this.action.doAction(action);
    }
}

registry.category("actions").add("dct_accounting.report", DctInteractiveReport);


