"""job_status tells the agent where its own claim request stands."""

import unittest
from unittest.mock import patch

from mergepaid_mcp import server

JOB = {"id": "job_fixture", "state": "open", "title": "Authored public task", "amount_usd": 100,
       "estimate": {"tokens_in": 1, "tokens_out": 1, "attempts": 1}}
WORK = {"schema": "supplier-job-work-v1", "job_id": "job_fixture", "job_state": "open",
        "assignment": "unassigned", "project": {"status": "standalone", "dependencies": "not_applicable"},
        "claim": {"status": "none"}, "can_start_bounty": False, "next_action_code": "request_human_claim",
        "next_action": server.WORK_ACTIONS["request_human_claim"], "authority_scope": "MARKETPLACE_CLAIM_ONLY"}


def status_with(request):
    def backend(method, path, **kwargs):
        if path.endswith("/work-status"):
            return dict(WORK)
        if path.endswith("/claim-request"):
            return request
        return dict(JOB)

    with patch.object(server, "TOKEN", "fixture"), patch.object(server, "_call", side_effect=backend):
        return server.job_status("job_fixture")


class ClaimRequestStatusTests(unittest.TestCase):
    def test_a_pending_request_never_asks_to_request_again(self):
        result = status_with({"job_id": "job_fixture", "status": "pending", "expires_at": "2026-09-26T12:00:00+00:00"})
        self.assertEqual(result["claim_request"]["status"], "pending")
        self.assertNotEqual(result["next_action"], server.WORK_ACTIONS["request_human_claim"])
        self.assertIn("waiting for the poster", result["next_action"].lower())

    def test_declined_and_expired_are_reported_with_the_reason_as_data(self):
        declined = status_with({"job_id": "job_fixture", "status": "declined", "expires_at": "x",
                                "decided_at": "y", "reason": "Needs a Rust specialist"})
        self.assertEqual(declined["claim_request"]["poster_reason"], "Needs a Rust specialist")
        self.assertIn("declined", declined["next_action"])
        expired = status_with({"job_id": "job_fixture", "status": "expired", "expires_at": "x"})
        self.assertIn("expired", expired["next_action"])

    def test_no_request_or_an_unreadable_one_leaves_the_work_status_action(self):
        for request in ({"error": "MergePaid returned 404."}, {"job_id": "other", "status": "pending", "expires_at": "x"},
                        {"job_id": "job_fixture", "status": "made_up", "expires_at": "x"}):
            result = status_with(request)
            self.assertIsNone(result["claim_request"])
            self.assertEqual(result["next_action"], server.WORK_ACTIONS["request_human_claim"])


if __name__ == "__main__":
    unittest.main()
