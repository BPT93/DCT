from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDctDashboard(TransactionCase):

    def test_dashboard_payload_without_optional_apps(self):
        payload = self.env["dct.dashboard"].get_dashboard_data(period="month")

        self.assertEqual(payload["period"]["key"], "month")
        self.assertEqual(len(payload["metrics"]), 4)
        self.assertEqual(len(payload["revenue_trend"]), 6)
        self.assertIn("accounting", payload["availability"])

    def test_invalid_period_falls_back_to_month(self):
        payload = self.env["dct.dashboard"].get_dashboard_data(period="invalid")

        self.assertEqual(payload["period"]["key"], "month")
