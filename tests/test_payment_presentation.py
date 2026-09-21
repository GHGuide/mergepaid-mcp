"""Local output-contract checks; no provider or backend connection."""

import unittest
from pathlib import Path
from unittest.mock import patch

from mergepaid_mcp import server


class PaymentPresentationTests(unittest.TestCase):
    def test_local_earnings_preserve_numbers_without_claiming_provider_movement(self):
        supplier = {"name": "Synthetic supplier", "balance_usd": 85, "pending_usd": 17, "paid_usd": 170}
        with patch.object(server, "TOKEN", "synthetic_fixture"), patch.object(server, "_call", return_value=supplier):
            result = server.my_earnings()
        self.assertEqual((result["available_usd"], result["pending_usd"], result["paid_usd"]), (85, 17, 170))
        self.assertIn("Local entitlement balance", result["summary"])
        self.assertIn("bank payout are unconfirmed", result["summary"])
        self.assertNotIn("Available:", result["summary"])
        self.assertIn("do not verify Stripe", result["payment_note"])

    def test_legacy_paid_state_is_local_entitlement(self):
        with patch.object(server, "_call", return_value={"id": "job_fixture", "state": "paid", "amount_usd": 100}):
            result = server.job_status("job_fixture")
        self.assertEqual(result["state"], "paid")
        self.assertEqual(result["net_payout_usd"], 85)
        self.assertIn("Local entitlement", result["summary"])
        self.assertIn("Stripe movement is not established", result["summary"])
        self.assertIn("do not verify Stripe", result["payment_note"])

    def test_no_lifecycle_state_claims_payment_release(self):
        for state in ["submitted", "merged", "paid", "rejected", "expired"]:
            with self.subTest(state=state):
                summary, _ = server._state_copy(state)
                self.assertNotIn("releases payment", summary)
                self.assertNotIn("Payment was not released", summary)
                self.assertTrue("entitlement" in summary.lower())

    def test_documented_pin_and_local_candidate_are_distinct(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
        self.assertIn("2e1913fe5b771a2d67fb7011304b18424908d83b#subdirectory=mcp", readme)
        self.assertIn("**not published**", readme)
        self.assertIn('uvx --from "$PWD/mcp"', readme)
        self.assertIn("legacy", readme)


if __name__ == "__main__":
    unittest.main()
