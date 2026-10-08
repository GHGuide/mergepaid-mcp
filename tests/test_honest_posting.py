"""The deadline and the funding label reach the agent; the poster's failed attempts do not."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from mergepaid_mcp import server

CARD = {"id": "job_x", "state": "open", "title": "Unreviewed funded job", "amount_usd": 100,
        "lanes": 1, "lanes_open": 1, "estimate": {"tokens_in": 1000, "tokens_out": 200, "attempts": 1},
        "deadline_at": "2026-10-07T12:00:00+00:00", "overdue": True, "unfunded": True,
        "referee": {"kind": "github_merge", "label": "Merged", "observed": True}}
JOB = {**CARD, "title": "Fix login", "description": "d", "criteria": "c",
       "failed_attempts": "Attempt 1: bumped the TTL; the tests broke."}


def backend(routes):
    def call(method, path, **kwargs):
        for suffix, value in routes.items():
            if path.endswith(suffix):
                return deepcopy(value(kwargs) if callable(value) else value)
        return {"error": "not needed here"}
    return call


class HonestPostingTests(unittest.TestCase):
    def test_find_work_cards_carry_the_deadline_and_say_unfunded(self):
        with patch.object(server, "TOKEN", "tok"), patch.object(server, "_call", side_effect=backend({"/api/discovery/jobs": [CARD]})):
            card = server.find_work()["recommendation"]
        self.assertEqual(card["deadline_at"], CARD["deadline_at"])
        self.assertTrue(card["overdue"] and card["unfunded"])
        self.assertIn("No provider funding is confirmed", card["funding_note"])
        self.assertIn("past its deadline", card["deadline_note"])

    def test_review_job_never_forwards_the_posters_private_attempts(self):
        routes = {"/api/jobs/job_x": JOB, "/execution-policy": {"default": "DENY"}}
        with patch.object(server, "TOKEN", "tok"), patch.object(server, "_call", side_effect=backend(routes)):
            review = server.review_job("job_x")
        # Even a backend that sent them: only the poster reads their attempts (ADR 116).
        self.assertNotIn("failed_attempts", review)
        self.assertNotIn("bumped the TTL", repr(review))
        self.assertIn("poster-authored data", review["instruction_boundary"])
        self.assertIn("uncalibrated", review["estimate_caveat"])
        self.assertTrue(review["unfunded"])

    def test_a_funded_job_on_time_carries_no_notes(self):
        with patch.object(server, "TOKEN", "tok"), patch.object(server, "_call", side_effect=backend(
                {"/api/discovery/jobs": [{**CARD, "overdue": False, "unfunded": False}]})):
            card = server.find_work()["recommendation"]
        self.assertNotIn("funding_note", card)
        self.assertNotIn("deadline_note", card)

    def test_submit_work_reports_tokens_used_and_refuses_nonsense(self):
        sent = {}

        def submit(kwargs):
            sent.update(kwargs["json"])
            return {"id": "job_x", "state": "submitted", "pr_url": kwargs["json"]["pr_url"]}

        routes = {"/credentials": {"credential": "op"}, "/submit": submit}
        with patch.object(server, "TOKEN", "tok"), patch.object(server, "_call", side_effect=backend(routes)):
            server.submit_work("job_x", "https://github.com/a/b/pull/1", tokens_used=41000)
            refused = server.submit_work("job_x", "https://github.com/a/b/pull/1", tokens_used=-3)
        self.assertEqual(sent["reported_tokens"], 41000)
        self.assertIn("tokens_used", refused["error"])


if __name__ == "__main__":
    unittest.main()
