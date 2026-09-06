from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestDctAccountReports(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.invoice = cls._create_invoice_one_line(
            price_unit=1000.0,
            account_id=cls.company_data["default_account_revenue"],
            tax_ids=[],
            invoice_date=cls.today,
            post=True,
        )

    def _wizard(self, report_type):
        return self.env["dct.account.report.wizard"].create({
            "report_type": report_type,
            "company_id": self.env.company.id,
            "date_from": self.today.replace(day=1),
            "date_to": self.today,
            "target_move": "posted",
        })

    def test_profit_and_loss_uses_posted_invoice_entries(self):
        wizard = self._wizard("profit_loss")
        wizard._generate_lines()

        net_profit = wizard.line_ids.filtered(
            lambda line: line.name == "Net Income"
        )
        self.assertEqual(len(net_profit), 1)
        self.assertAlmostEqual(net_profit.balance, 1000.0, places=2)

    def test_partner_ledger_links_invoice_partner(self):
        wizard = self._wizard("partner_ledger")
        wizard._generate_lines()

        partner_line = wizard.line_ids.filtered(
            lambda line: line.partner_id == self.partner_a
        )
        self.assertTrue(partner_line)
        self.assertAlmostEqual(partner_line.ending_balance, 1000.0, places=2)

    def test_balance_sheet_includes_current_period_earnings(self):
        wizard = self._wizard("balance_sheet")
        wizard._generate_lines()

        assets = wizard.line_ids.filtered(lambda line: line.name == "Total Assets")
        liabilities_equity = wizard.line_ids.filtered(
            lambda line: line.name == "Total Liabilities & Equity"
        )
        self.assertAlmostEqual(assets.balance, liabilities_equity.balance, places=2)

    def test_interactive_report_payload_is_generated_immediately(self):
        payload = self.env["dct.account.report.wizard"].get_report_data({
            "report_type": "profit_loss",
            "date_from": self.today.replace(day=1).isoformat(),
            "date_to": self.today.isoformat(),
            "target_move": "posted",
            "comparison": "none",
        })

        self.assertEqual(payload["report_name"], "Profit & Loss")
        self.assertTrue(payload["wizard_id"])
        self.assertTrue(payload["lines"])
        self.assertIn(
            "Net Income",
            {line["name"] for line in payload["lines"]},
        )

    def test_previous_year_comparison_adds_variance(self):
        payload = self.env["dct.account.report.wizard"].get_report_data({
            "report_type": "profit_loss",
            "date_from": self.today.replace(day=1).isoformat(),
            "date_to": self.today.isoformat(),
            "target_move": "posted",
            "comparison": "previous_year",
        })

        self.assertEqual(payload["comparison"], "previous_year")
        self.assertTrue(payload["comparison_date_from"])
        net_profit = next(
            line for line in payload["lines"] if line["name"] == "Net Income"
        )
        self.assertAlmostEqual(net_profit["variance"], 1000.0, places=2)

    def test_accounting_report_menus_use_interactive_client_actions(self):
        menu = self.env.ref("dct_accounting.menu_dct_profit_loss")
        action = self.env.ref("dct_accounting.action_dct_profit_loss_interactive")

        self.assertEqual(menu.action, action)
        self.assertEqual(action.type, "ir.actions.client")
        self.assertEqual(action.tag, "dct_accounting.report")

    def test_enterprise_style_reporting_menu_sequence(self):
        reports = self.env.ref("account.menu_finance_reports")
        expected = [
            (10, "Financial Reports"),
            (20, "Audit"),
            (30, "Partner Reports"),
            (40, "Taxes & Fiscal"),
            (50, "Management"),
        ]
        actual = [
            (menu.sequence, menu.name)
            for menu in reports.child_id.filtered("active").sorted(
                key=lambda menu: (menu.sequence, menu.id)
            )
            if menu.name in {name for _sequence, name in expected}
        ]
        self.assertEqual(actual, expected)

    def test_enterprise_style_asset_menu_ownership(self):
        finance_root = self.env.ref("account.menu_finance")
        accounting_menu = self.env.ref("account.menu_finance_entries")
        review_menu = self.env.ref("account.account_audit_menu")
        asset_menu = self.env.ref("account_asset_management.menu_finance_assets")
        depreciation_menu = self.env.ref(
            "account_asset_management.account_asset_report_menu"
        )

        self.assertEqual(asset_menu.parent_id, accounting_menu)
        self.assertEqual(depreciation_menu.parent_id, review_menu)
        self.assertNotIn(asset_menu, finance_root.child_id)
        self.assertEqual(
            [
                menu.name
                for menu in finance_root.child_id.filtered("active").sorted(
                    key=lambda menu: (menu.sequence, menu.id)
                )
            ],
            [
                "Dashboard",
                "Customers",
                "Vendors",
                "Accounting",
                "Review",
                "Reporting",
                "Configuration",
            ],
        )

    def test_executive_summary_reports_core_metrics(self):
        wizard = self._wizard("executive_summary")
        wizard._generate_lines()

        net_profit = wizard.line_ids.filtered(
            lambda line: line.name == "Net Income"
        )
        self.assertEqual(len(net_profit), 1)
        self.assertAlmostEqual(net_profit.balance, 1000.0, places=2)

    def test_cash_flow_has_opening_and_closing_total(self):
        wizard = self._wizard("cash_flow")
        wizard._generate_lines()

        total = wizard.line_ids.filtered(
            lambda line: line.name == "Net Cash and Cash Equivalents"
        )
        self.assertEqual(len(total), 1)
        self.assertAlmostEqual(
            total.ending_balance,
            total.opening_balance + total.balance,
            places=2,
        )

    def test_aged_receivable_has_partner_buckets(self):
        wizard = self._wizard("aged_receivable")
        wizard._generate_lines()

        partner_line = wizard.line_ids.filtered(
            lambda line: line.partner_id == self.partner_a
        )
        self.assertTrue(partner_line)
        self.assertAlmostEqual(partner_line.ending_balance, 1000.0, places=2)
        self.assertAlmostEqual(
            partner_line.ending_balance,
            partner_line.bucket_current
            + partner_line.bucket_1_30
            + partner_line.bucket_31_60
            + partner_line.bucket_61_90
            + partner_line.bucket_older,
            places=2,
        )

    def test_accounting_administrator_inherits_full_accounting(self):
        manager = self.env.ref("account.group_account_manager")
        accountant = self.env.ref("account.group_account_user")
        self.assertIn(accountant, manager.implied_ids)

    def test_accounting_dashboard_payload(self):
        payload = self.env["dct.accounting.dashboard"].get_dashboard_data("month")

        self.assertEqual(payload["period"]["key"], "month")
        self.assertEqual(len(payload["metrics"]), 4)
        self.assertEqual(len(payload["profit_trend"]), 6)
        self.assertEqual(len(payload["receivable_aging"]), 5)
        self.assertEqual(payload["company"]["id"], self.env.company.id)
        self.assertEqual(
            payload["company"]["logo_url"],
            f"/web/image/res.company/{self.env.company.id}/logo_web",
        )

    def test_enterprise_style_journal_dashboard_is_composed(self):
        dashboard = self.env.ref("account.account_journal_dashboard_kanban_view")
        arch = dashboard.get_combined_arch()

        self.assertIn("dcta_enterprise_dashboard", arch)
        self.assertIn("dcta_journal_card_header", arch)
        self.assertIn("dcta_journal_icon", arch)

    def test_financial_overview_is_available_from_management_reports(self):
        action = self.env.ref("dct_accounting.action_dct_accounting_overview")
        menu = self.env.ref("dct_accounting.menu_dct_accounting_overview")

        self.assertEqual(action.type, "ir.actions.client")
        self.assertEqual(action.tag, "dct_accounting.Dashboard")
        self.assertEqual(
            menu.parent_id,
            self.env.ref("account.account_reports_management_menu"),
        )

    def test_native_accounting_workspace_is_used(self):
        action_xmlids = [
            "account.action_move_out_refund_type_non_legacy",
            "account.action_move_in_refund_type",
            "account.action_account_moves_all",
            "account.action_account_invoice_report_all",
            "account.action_tax_form",
            "account.action_account_fiscal_position_form",
            "account.action_payment_term_form",
            "analytic.action_analytic_distribution_model",
            "account_financial_report.action_general_ledger_wizard",
            "account_financial_report.action_aged_partner_balance_wizard",
            "account_asset_management.account_asset_action",
            "account_reconcile_oca.action_bank_statement_line_reconcile",
            "mis_builder.mis_report_instance_view_action",
            "mis_builder_budget.mis_budget_act_window",
        ]
        for xmlid in action_xmlids:
            self.assertTrue(self.env.ref(xmlid, raise_if_not_found=False), xmlid)

        native_root = self.env.ref("account.menu_finance")
        native_dashboard = self.env.ref("account.menu_board_journal_1")
        legacy_root = self.env.ref("dct_accounting.menu_dct_accounting_root")

        self.assertEqual(native_root.name, "Accounting")
        self.assertEqual(native_dashboard.parent_id, native_root)
        self.assertFalse(legacy_root.active)
        self.assertEqual(
            self.env.ref("dct_accounting.menu_dct_balance_sheet").parent_id,
            self.env.ref("account.account_reports_legal_statements_menu"),
        )
        self.assertFalse(
            self.env.ref("account_financial_report.menu_general_ledger_wizard").active
        )
        self.assertEqual(
            self.env.ref("dct_accounting.menu_dct_general_ledger_interactive").parent_id,
            self.env.ref("dct_accounting.menu_dct_audit_reports"),
        )
        self.assertFalse(
            self.env.ref("account_financial_report.menu_oca_reports").active
        )


