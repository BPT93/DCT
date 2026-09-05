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
            lambda line: line.name == "Net Profit / Loss"
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

        assets = wizard.line_ids.filtered(lambda line: line.name == "TOTAL ASSETS")
        liabilities_equity = wizard.line_ids.filtered(
            lambda line: line.name == "TOTAL LIABILITIES & EQUITY"
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
            "Net Profit / Loss",
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
            line for line in payload["lines"] if line["name"] == "Net Profit / Loss"
        )
        self.assertAlmostEqual(net_profit["variance"], 1000.0, places=2)

    def test_accounting_report_menus_use_interactive_client_actions(self):
        action = self.env.ref("dct_accounting.action_dct_profit_loss_interactive")
        self.assertEqual(action.type, "ir.actions.client")
        self.assertEqual(action.tag, "dct_accounting.report")

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


