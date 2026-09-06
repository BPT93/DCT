/** @odoo-module **/

import {onWillStart, useState} from "@odoo/owl";
import {user} from "@web/core/user";
import {useService} from "@web/core/utils/hooks";
import {patch} from "@web/core/utils/patch";
import {_t} from "@web/core/l10n/translation";
import {DashboardKanbanRecord} from "@account/views/account_dashboard_kanban/account_dashboard_kanban_record";
import {DashboardKanbanRenderer} from "@account/views/account_dashboard_kanban/account_dashboard_kanban_renderer";

const FEATURE_ACTIONS = {
    overview: "dct_accounting.action_dct_accounting_overview",
    reconcile: "account_reconcile_oca.account_account_reconcile_act_window",
    statements: "account_statement_import_file.account_statement_import_action",
    balanceSheet: "dct_accounting.action_dct_balance_sheet_interactive",
    assets: "account_asset_management.account_asset_action",
    budgets: "mis_builder_budget.mis_budget_by_account_act_window",
};

patch(DashboardKanbanRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.dctActionService = useService("action");
        this.dctPermissions = useState({
            canCreateInvoice: false,
            canPostEntries: false,
            canReadAccounting: false,
        });

        onWillStart(async () => {
            const [canCreateInvoice, canPostEntries, canReadAccounting] =
                await Promise.all([
                    user.hasGroup("account.group_account_invoice"),
                    user.hasGroup("account.group_account_user"),
                    user.hasGroup("account.group_account_readonly"),
                ]);
            this.dctPermissions.canCreateInvoice = canCreateInvoice;
            this.dctPermissions.canPostEntries = canPostEntries;
            this.dctPermissions.canReadAccounting = canReadAccounting;
        });
    },

    openDctFeature(feature) {
        return this.dctActionService.doAction(FEATURE_ACTIONS[feature]);
    },

    createDctMove(moveType) {
        const titles = {
            entry: _t("New Journal Entry"),
            in_invoice: _t("New Vendor Bill"),
            out_invoice: _t("New Customer Invoice"),
        };
        return this.dctActionService.doAction({
            type: "ir.actions.act_window",
            name: titles[moveType],
            res_model: "account.move",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_move_type: moveType,
            },
        });
    },
});

patch(DashboardKanbanRecord.prototype, {
    getRecordClasses() {
        const classes = super.getRecordClasses(...arguments);
        const journalType = this.props.record.data.type || "general";
        return `${classes} dcta_journal_card dcta_journal_${journalType}`;
    },
});
