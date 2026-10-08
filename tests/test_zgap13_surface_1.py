"""SURFACE13-1: keep the backend's recorded-pot warning across MCP reads."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import JOB, run


# This v2 response is exercised through the real backend in
# backend/tests/test_zgap13_surface_1.py, after a signed charge.refunded delivery.
UNFUNDED = {
    "schema": "supplier-job-work-v2", "job_id": "job_pack", "job_state": "submitted",
    "assignment": "you", "project": {"status": "standalone", "dependencies": "not_applicable"},
    "claim": {"status": "closed"}, "can_start_bounty": False,
    "next_action_code": "wait_for_owner",
    "next_action": "The recorded pot is unavailable. Wait for the MergePaid founders to reconcile it; choose another job.",
    "authority_scope": "MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY",
    "functional_completion": {"status": "none", "authority": None},
    "can_submit_pr": False, "submission_authority": "NONE",
}


class RecordedPotLoss(unittest.TestCase):
    def read(self, tool):
        answer, _ = run(tool, "job_pack", job={**JOB, "state": "submitted", "pot_unavailable": True}, routes={
            "/work-status": UNFUNDED, "/work": {"job_id": "job_pack", "work": None}, "/judging": {},
        })
        self.assertIsNotNone(answer["work_status"], answer["next_action"])
        self.assertEqual(answer["work_authorization"], "not_authorized_to_start")
        self.assertIn("pot", answer["next_action"].lower())
        self.assertIn("founders", answer["next_action"].lower())

    def test_review_retains_the_recorded_funding_loss(self):
        self.read(server.review_job)

    def test_status_retains_the_recorded_funding_loss(self):
        self.read(server.job_status)


class RecordedPotContract(unittest.TestCase):
    def test_warning_cannot_grant_work_or_skip_submission_authority_validation(self):
        from unittest.mock import patch
        variants = [
            {**UNFUNDED, "can_start_bounty": True},
            {**UNFUNDED, "next_action": UNFUNDED["next_action"] + " Do extra work."},
            {**UNFUNDED, "can_submit_pr": True},
        ]
        for value in variants:
            with self.subTest(value=value), patch.object(server, "TOKEN", "test-racer"), \
                    patch.object(server, "_call", return_value=value):
                self.assertIsNone(server._work_status("job_pack", "submitted"))

    def test_warning_preserves_existing_submission_authority(self):
        from unittest.mock import patch
        for authority, status, claim in [("CURRENT_HUMAN_CLAIM", "none", "active_for_you"),
                                         ("ACCEPTED_RESULT_HANDOFF", "accepted", "expired")]:
            value = {**UNFUNDED, "job_state": "claimed", "claim": {"status": claim},
                     "functional_completion": {"status": status, "authority":
                                               "OWNER_ACCEPTANCE_TESTIMONY" if status == "accepted" else None},
                     "can_submit_pr": True, "submission_authority": authority}
            with self.subTest(authority=authority), patch.object(server, "TOKEN", "test-racer"), \
                    patch.object(server, "_call", return_value=value):
                self.assertEqual(server._work_status("job_pack", "claimed")["work_status"], value)


if __name__ == "__main__":
    unittest.main()
