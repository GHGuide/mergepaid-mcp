"""Local output-contract checks; no provider or backend connection."""

import re
import unittest
from pathlib import Path
from unittest.mock import patch

from mergepaid_mcp import server


class PaymentPresentationTests(unittest.TestCase):
    def test_local_earnings_preserve_numbers_without_claiming_provider_movement(self):
        supplier = {"name": "Synthetic supplier", "handle": "agentPorto", "balance_usd": 85, "pending_usd": 17, "paid_usd": 170}
        with patch.object(server, "TOKEN", "synthetic_fixture"), patch.object(server, "_call", return_value=supplier):
            result = server.my_earnings()
        self.assertEqual((result["available_usd"], result["pending_usd"], result["paid_usd"]), (85, 17, 170))
        self.assertEqual(result["racer_handle"], "agentPorto")
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

    def test_documented_pin_installs_without_mergepaid_repo_access(self):
        # A supplier must be able to install the connector without read access to
        # the MergePaid repository, so the documented source is this connector's
        # own public repo, pinned to a full commit rather than a moving branch.
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
        pins = re.findall(
            r"git\+https://github\.com/GHGuide/([A-Za-z0-9_.-]+?)\.git@([0-9a-f]+)", readme)
        self.assertTrue(pins, "README documents no install source")
        for repo, commit in pins:
            self.assertEqual(repo, "mergepaid-mcp")
            self.assertEqual(len(commit), 40)
        self.assertIn('uvx --from "$PWD/mcp"', readme)  # the local-checkout route stays

    def test_readme_never_claims_provider_movement(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
        self.assertIn("entitlement", readme)
        self.assertNotIn("proves provider movement.\n\nStripe transfer", readme)


if __name__ == "__main__":
    unittest.main()
