/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";


export class DctPayrollDashboard extends Component {
    static template = "dct_payroll.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            error: false,
            data: null,
            statsPeriod: "monthly",
            activeNoteId: null,
            noteName: "",
            noteMemo: "",
            savingNote: false,
        });
        onWillStart(() => this.loadData());
    }

    async loadData() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const activeNoteId = this.state.activeNoteId;
            this.state.data = await this.orm.call(
                "dct.payroll.dashboard",
                "get_dashboard_data",
                [],
                { period: "month" }
            );
            const notes = this.state.data.notes || [];
            const activeNote =
                notes.find((note) => note.id === activeNoteId) || notes[0];
            this.setActiveNote(activeNote);
        } catch {
            this.state.error = true;
            this.notification.add(_t("The payroll dashboard could not be loaded."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    setActiveNote(note) {
        this.state.activeNoteId = note?.id || null;
        this.state.noteName = note?.name || "";
        this.state.noteMemo = note?.memo || "";
    }

    get activeNote() {
        return (this.state.data?.notes || []).find(
            (note) => note.id === this.state.activeNoteId
        );
    }

    async selectNote(note) {
        if (note.id === this.state.activeNoteId) {
            return;
        }
        await this.saveNote(false);
        this.setActiveNote(note);
    }

    async createNote() {
        await this.saveNote(false);
        const [id] = await this.orm.create("dct.payroll.note", [
            {
                name: _t("Untitled"),
                memo: "",
                company_id: this.state.data.company.id,
            },
        ]);
        const note = { id, name: _t("Untitled"), memo: "", sequence: 10 };
        this.state.data.notes.push(note);
        this.setActiveNote(note);
    }

    async saveNote(notify = true) {
        const note = this.activeNote;
        if (!note || this.state.savingNote) {
            return;
        }
        const name = this.state.noteName.trim() || _t("Untitled");
        if (name === note.name && this.state.noteMemo === (note.memo || "")) {
            return;
        }
        this.state.savingNote = true;
        try {
            await this.orm.write("dct.payroll.note", [note.id], {
                name,
                memo: this.state.noteMemo,
            });
            note.name = name;
            note.memo = this.state.noteMemo;
            this.state.noteName = name;
            if (notify) {
                this.notification.add(_t("Payroll note saved."), {
                    type: "success",
                });
            }
        } finally {
            this.state.savingNote = false;
        }
    }

    deleteNote() {
        const note = this.activeNote;
        if (!note) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete payroll note?"),
            body: _t("This note and its content will be permanently deleted."),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                await this.orm.unlink("dct.payroll.note", [note.id]);
                this.state.data.notes = this.state.data.notes.filter(
                    (item) => item.id !== note.id
                );
                this.setActiveNote(this.state.data.notes[0]);
            },
        });
    }

    onNoteNameInput(event) {
        this.state.noteName = event.target.value;
    }

    onNoteMemoInput(event) {
        this.state.noteMemo = event.target.value;
    }

    toggleStatsPeriod() {
        this.state.statsPeriod =
            this.state.statsPeriod === "monthly" ? "yearly" : "monthly";
    }

    async openAction(action) {
        await this.action.doAction(action);
    }

    async openBatch(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Payslip Batch"),
            res_model: "hr.payslip.run",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    formatCurrency(value) {
        const currency = this.state.data.company.currency;
        try {
            return new Intl.NumberFormat(undefined, {
                style: "currency",
                currency: currency.code,
                minimumFractionDigits: currency.digits,
                maximumFractionDigits: currency.digits,
            }).format(Number(value || 0));
        } catch {
            return `${currency.symbol}${Number(value || 0).toFixed(currency.digits)}`;
        }
    }

    get employerBars() {
        const rows =
            this.state.data.statistics.employer_cost[this.state.statsPeriod];
        const maximum = Math.max(
            ...rows.flatMap((row) => [Math.abs(row.gross), Math.abs(row.net)]),
            1
        );
        return rows.map((row) => ({
            ...row,
            grossHeight: row.gross ? Math.max(5, (Math.abs(row.gross) / maximum) * 100) : 0,
            netHeight: row.net ? Math.max(5, (Math.abs(row.net) / maximum) * 100) : 0,
        }));
    }

    get employeeBars() {
        const rows =
            this.state.data.statistics.employee_trends[this.state.statsPeriod];
        const maximum = Math.max(...rows.map((row) => row.value), 1);
        return rows.map((row) => ({
            ...row,
            height: row.value ? Math.max(7, (row.value / maximum) * 100) : 0,
        }));
    }

    batchTone(state) {
        return state === "close" ? "text-bg-success" : "text-bg-secondary";
    }
}

registry.category("actions").add("dct_payroll.Dashboard", DctPayrollDashboard);
