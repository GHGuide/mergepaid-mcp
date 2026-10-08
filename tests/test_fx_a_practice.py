"""Explicit practice metadata reaches both decision tools without a pot."""
import json
import unittest
from unittest.mock import patch
from mergepaid_mcp import server

JOB = {"id": "job_practice", "title": "Practice job: no payout", "state": "open", "practice": True,
       "amount_usd": 0, "fee_pct": 15, "repo_url": "https://github.com/sample/parser"}

class PracticeTools(unittest.TestCase):
    def backend(self, method, path, **kwargs):
        if path == "/api/discovery/jobs":
            return [JOB]
        if path == "/api/jobs/job_practice":
            return JOB
        return {}

    def test_practice_find_and_review_have_no_dollar_figures(self):
        with patch.object(server, "TOKEN", "fixture"), patch.object(server, "_call", side_effect=self.backend):
            found = server.find_work()
            reviewed = server.review_job(JOB["id"])
        for value in (found, reviewed):
            self.assertTrue(value["summary"].startswith("Practice job: no payout"))
            self.assertNotIn("$", json.dumps(value))
        self.assertTrue(found["recommendation"]["practice"])
        self.assertIsNone(found["recommendation"]["net_payout_usd"])
        self.assertTrue(reviewed["practice"])
        self.assertIsNone(reviewed["gross_payout_usd"])

    def test_local_test_pots_are_not_practice(self):
        card = server._decision_card({**JOB, "practice": False, "synthetic": True, "unfunded": True, "amount_usd": 100})
        self.assertFalse(card["practice"])
        self.assertEqual(card["net_payout_usd"], 85)
        with patch.object(server, "TOKEN", "fixture"), patch.object(server, "_call", side_effect=self.backend):
            self.assertIsNone(server.find_work(minimum_payout_usd=1)["recommendation"])
