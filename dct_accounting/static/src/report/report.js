/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { fuzzyLookup } from "@web/core/utils/search";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillStart, useState } from "@odoo/owl";


const REPORT_TYPES = [
    ["balance_sheet", "Balance Sheet"],
    ["profit_loss", "Profit & Loss"],
    ["executive_summary", "Executive Summary"],
    ["cash_flow", "Cash Flow Statement"],
    ["general_ledger", "General Ledger"],
    ["trial_balance", "Trial Balance"],
    ["journal_ledger", "Journal Audit"],
    ["partner_ledger", "Partner Ledger"],
    ["aged_receivable", "Aged Receivable"],
    ["aged_payable", "Aged Payable"],
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
        const startsAsOf = ["balance_sheet", "aged_receivable", "aged_payable"].includes(reportType);
        const period = currentMonth();
        this.reportTypes = REPORT_TYPES;
        this.state = useState({
            loading: true,
            dateOpen: false,
            journalOpen: false,
            accountOpen: false,
            partnerOpen: false,
            optionsOpen: false,
            accountQuery: "",
            partnerQuery: "",
            collapsed: {},
            periodPreset: startsAsOf ? "today" : "month",
            options: {
                wizard_id: false,
                report_type: reportType,
                date_from: startsAsOf ? period.dateTo : period.dateFrom,
                date_to: period.dateTo,
                target_move: "posted",
                comparison: "none",
                journal_ids: [],
                account_ids: [],
                partner_ids: [],
                show_zero: false,
            },
            data: {
                report_name: "",
                company_name: "",
                comparison: "none",
                comparison_label: "",
                currency: {},
                journals: [],
                accounts: [],
                partners: [],
                lines: [],
            },
        });

        for (const method of [
            "loadReport",
            "applyFilters",
            "resetFilters",
            "toggleJournals",
            "toggleAccounts",
            "togglePartners",
            "toggleOptions",
            "onPeriodPresetChange",
            "onReportTypeChange",
            "onDateFromChange",
            "onDateToChange",
            "onTargetMoveChange",
            "onComparisonChange",
            "onShowZeroChange",
            "toggleJournal",
            "clearJournals",
            "onAccountQueryInput",
            "toggleAccount",
            "clearAccounts",
            "onPartnerQueryInput",
            "togglePartner",
            "clearPartners",
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
        return ["profit_loss", "balance_sheet", "executive_summary"].includes(
            this.state.options.report_type
        );
    }

    get isAgedReport() {
        return ["aged_receivable", "aged_payable"].includes(this.state.options.report_type);
    }

    get isCashFlow() {
        return this.state.options.report_type === "cash_flow";
    }

    get isAsOfReport() {
        return ["balance_sheet", "aged_receivable", "aged_payable"].includes(
            this.state.options.report_type
        );
    }

    get supportsComparison() {
        return [
            "balance_sheet",
            "profit_loss",
            "executive_summary",
            "cash_flow",
            "trial_balance",
        ].includes(this.state.options.report_type);
    }

    get hasComparison() {
        return this.supportsComparison &&
            this.state.data.comparison &&
            this.state.data.comparison !== "none";
    }

    get periodLabel() {
        if (this.isAsOfReport) {
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

    get accountLabel() {
        const count = this.state.options.account_ids.length;
        if (!count) {
            return _t("All Accounts");
        }
        if (count === 1) {
            const account = this.state.data.accounts.find(
                (item) => item.id === this.state.options.account_ids[0]
            );
            return account?.code || account?.name || _t("1 Account");
        }
        return _t("%s Accounts", count);
    }

    get partnerLabel() {
        const count = this.state.options.partner_ids.length;
        if (!count) {
            return _t("All Partners");
        }
        if (count === 1) {
            const partner = this.state.data.partners.find(
                (item) => item.id === this.state.options.partner_ids[0]
            );
            return partner?.name || _t("1 Partner");
        }
        return _t("%s Partners", count);
    }

    get showPartnerFilter() {
        return ["partner_ledger", "aged_receivable", "aged_payable"].includes(
            this.state.options.report_type
        );
    }

    get isDetailedReport() {
        return ["general_ledger", "partner_ledger", "journal_ledger"].includes(
            this.state.options.report_type
        );
    }

    get filteredAccounts() {
        if (!this.state.accountQuery.trim()) {
            return this.state.data.accounts;
        }
        return fuzzyLookup(
            this.state.accountQuery,
            this.state.data.accounts,
            (account) => `${account.code} ${account.name}`
        );
    }

    get filteredPartners() {
        if (!this.state.partnerQuery.trim()) {
            return this.state.data.partners;
        }
        return fuzzyLookup(
            this.state.partnerQuery,
            this.state.data.partners,
            (partner) => partner.name
        );
    }

    get lineNameLabel() {
        if (this.isAgedReport || this.state.options.report_type === "partner_ledger") {
            return _t("Partner");
        }
        if (this.state.options.report_type === "journal_ledger") {
            return _t("Journal");
        }
        return _t("Account");
    }

    get reportVariantLabel() {
        const country = this.state.data.company_country_code;
        const suffix = country ? ` (${country})` : "";
        return `${_t("Report:")} ${this.state.data.report_name || _t("Financial Report")}${suffix}`;
    }

    get currencyLabel() {
        const currency = this.state.data.currency || {};
        return `${_t("In")} ${currency.symbol || currency.name || ""}`.trim();
    }

    get periodColumnLabel() {
        return this.periodLabel;
    }

    get sectionKeys() {
        return this.state.data.lines
            .filter((line) => line.foldable && line.line_key)
            .map((line) => line.line_key);
    }

    get visibleLines() {
        const lines = this.state.data.lines;
        const byKey = new Map(lines.map((line) => [line.line_key, line]));
        return lines.filter((line) => {
            let parentKey = line.parent_key;
            while (parentKey) {
                if (this.state.collapsed[parentKey]) {
                    return false;
                }
                parentKey = byKey.get(parentKey)?.parent_key;
            }
            return true;
        });
    }

    async loadReport() {
        if (
            !this.isAsOfReport &&
            this.state.options.date_from &&
            this.state.options.date_to &&
            this.state.options.date_from > this.state.options.date_to
        ) {
            this.state.dateOpen = true;
            this.notification.add(_t("The start date must be before the end date."), {
                type: "warning",
            });
            return;
        }
        const defaultFold = !this.state.options.wizard_id && this.isDetailedReport;
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "dct.account.report.wizard",
                "get_report_data",
                [{ ...this.state.options }]
            );
            this.state.data = {
                journals: [],
                accounts: [],
                partners: [],
                lines: [],
                ...data,
            };
            this.state.options.wizard_id = data.wizard_id;
            this.state.options.report_type = data.report_type;
            this.state.options.date_from = data.date_from;
            this.state.options.date_to = data.date_to;
            this.state.options.target_move = data.target_move;
            this.state.options.comparison = data.comparison;
            this.state.options.show_zero = data.show_zero;
            this.state.options.journal_ids = this.state.data.journals
                .filter((journal) => journal.selected)
                .map((journal) => journal.id);
            this.state.options.account_ids = this.state.data.accounts
                .filter((account) => account.selected)
                .map((account) => account.id);
            this.state.options.partner_ids = this.state.data.partners
                .filter((partner) => partner.selected)
                .map((partner) => partner.id);
            if (defaultFold) {
                this.state.collapsed = Object.fromEntries(
                    this.state.data.lines
                        .filter((line) => line.foldable && line.line_key)
                        .map((line) => [line.line_key, true])
                );
            }
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
        this.state.accountOpen = false;
        this.state.partnerOpen = false;
        this.state.optionsOpen = false;
        await this.loadReport();
    }

    async resetFilters() {
        const period = currentMonth();
        const asOf = ["balance_sheet", "aged_receivable", "aged_payable"].includes(
            this.state.options.report_type
        );
        Object.assign(this.state.options, {
            date_from: asOf ? period.dateTo : period.dateFrom,
            date_to: period.dateTo,
            target_move: "posted",
            comparison: "none",
            journal_ids: [],
            account_ids: [],
            partner_ids: [],
            show_zero: false,
        });
        this.state.periodPreset = asOf ? "today" : "month";
        await this.applyFilters();
    }

    toggleJournals() {
        this.state.journalOpen = !this.state.journalOpen;
        this.state.dateOpen = false;
        this.state.accountOpen = false;
        this.state.partnerOpen = false;
        this.state.optionsOpen = false;
    }

    toggleAccounts() {
        this.state.accountOpen = !this.state.accountOpen;
        this.state.dateOpen = false;
        this.state.journalOpen = false;
        this.state.partnerOpen = false;
        this.state.optionsOpen = false;
    }

    togglePartners() {
        this.state.partnerOpen = !this.state.partnerOpen;
        this.state.dateOpen = false;
        this.state.journalOpen = false;
        this.state.accountOpen = false;
        this.state.optionsOpen = false;
    }

    toggleOptions() {
        this.state.optionsOpen = !this.state.optionsOpen;
        this.state.dateOpen = false;
        this.state.journalOpen = false;
        this.state.accountOpen = false;
        this.state.partnerOpen = false;
    }

    async onPeriodPresetChange(event) {
        const preset = event.target.value;
        if (preset === "custom") {
            this.state.periodPreset = "custom";
            this.state.dateOpen = true;
            this.state.journalOpen = false;
            this.state.accountOpen = false;
            this.state.partnerOpen = false;
            this.state.optionsOpen = false;
            return;
        }
        await this.setPeriod(preset);
    }

    async setPeriod(preset) {
        const today = new Date();
        let dateFrom;
        let dateTo = today;
        if (preset === "today") {
            dateFrom = today;
        } else if (preset === "last_month_end") {
            dateTo = new Date(today.getFullYear(), today.getMonth(), 0);
            dateFrom = dateTo;
        } else if (preset === "last_year_end") {
            dateTo = new Date(today.getFullYear() - 1, 11, 31);
            dateFrom = dateTo;
        } else if (preset === "month") {
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
        const wasAsOf = this.isAsOfReport;
        this.state.options.report_type = event.target.value;
        this.state.options.wizard_id = false;
        if (![
            "balance_sheet",
            "profit_loss",
            "executive_summary",
            "cash_flow",
            "trial_balance",
        ].includes(event.target.value)) {
            this.state.options.comparison = "none";
        }
        if (!["partner_ledger", "aged_receivable", "aged_payable"].includes(event.target.value)) {
            this.state.options.partner_ids = [];
        }
        if (wasAsOf !== this.isAsOfReport) {
            this.state.periodPreset = "custom";
        }
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

    onAccountQueryInput(event) {
        this.state.accountQuery = event.target.value;
    }

    toggleAccount(accountId) {
        const selected = new Set(this.state.options.account_ids);
        selected.has(accountId) ? selected.delete(accountId) : selected.add(accountId);
        this.state.options.account_ids = [...selected];
    }

    clearAccounts() {
        this.state.options.account_ids = [];
        this.state.accountQuery = "";
    }

    onPartnerQueryInput(event) {
        this.state.partnerQuery = event.target.value;
    }

    togglePartner(partnerId) {
        const selected = new Set(this.state.options.partner_ids);
        selected.has(partnerId) ? selected.delete(partnerId) : selected.add(partnerId);
        this.state.options.partner_ids = [...selected];
    }

    clearPartners() {
        this.state.options.partner_ids = [];
        this.state.partnerQuery = "";
    }

    toggleSection(lineKey) {
        this.state.collapsed[lineKey] = !this.state.collapsed[lineKey];
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
        const currency = this.state.data.currency;
        try {
            return new Intl.NumberFormat(undefined, {
                minimumFractionDigits: currency.decimal_places,
                maximumFractionDigits: currency.decimal_places,
            }).format(value);
        } catch {
            return new Intl.NumberFormat(undefined, {
                minimumFractionDigits: currency.decimal_places || 2,
                maximumFractionDigits: currency.decimal_places || 2,
            }).format(value);
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


