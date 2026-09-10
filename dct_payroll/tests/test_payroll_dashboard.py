from datetime import date

from odoo.tests.common import TransactionCase


class TestDctPayrollDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dashboard = cls.env["dct.payroll.dashboard"]

    def test_period_bounds(self):
        today = date(2026, 9, 6)
        self.assertEqual(
            self.dashboard._period_bounds("month", today),
            (date(2026, 9, 1), today),
        )
        self.assertEqual(
            self.dashboard._period_bounds("quarter", today),
            (date(2026, 7, 1), today),
        )
        self.assertEqual(
            self.dashboard._period_bounds("year", today),
            (date(2026, 1, 1), today),
        )

    def test_dashboard_contract(self):
        data = self.dashboard.get_dashboard_data(period="month")
        self.assertEqual(data["period"]["key"], "month")
        self.assertEqual(len(data["metrics"]), 4)
        self.assertEqual(len(data["states"]), 4)
        self.assertIn("readiness", data)
        self.assertIn("cost_trend", data)
        self.assertIn("warnings", data)
        self.assertIn("batches", data)
        self.assertIn("statistics", data)
        self.assertIn("monthly", data["statistics"]["employer_cost"])
        self.assertIn("yearly", data["statistics"]["employee_trends"])
        self.assertIn("notes", data)

    def test_payroll_note_company(self):
        note = self.env["dct.payroll.note"].create(
            {"name": "Month end", "memo": "Review the payroll batch."}
        )
        self.assertEqual(note.company_id, self.env.company)
        self.assertEqual(note.name, "Month end")

    def test_payslip_search_has_enterprise_filter_scope(self):
        arch = self.env.ref("payroll.hr_payslip_view_search").get_combined_arch()

        self.assertIn("group_by_structure", arch)
        self.assertIn("group_by_department", arch)
        self.assertIn("last_365_days", arch)
        self.assertIn("company_id", arch)
