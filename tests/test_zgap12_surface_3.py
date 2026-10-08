"""SURFACE12-3: an unfunded-pot refusal sends the agent back to claim advice."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, run


class UnfundedPotAdvice(unittest.TestCase):
    def test_claim_refusal_directs_the_agent_away_from_the_unfunded_job(self):
        # This is the current work-status response proved by the backend half.
        available = {**HOLDER, "job_state": "open", "assignment": "unassigned",
                     "claim": {"status": "none"}, "can_start_bounty": False,
                     "next_action_code": "request_human_claim",
                     "next_action": server.WORK_ACTIONS["request_human_claim"]}
        result, _ = run(server.claim_job, "job_pack", job=JOB, routes={
            "/work-status": available,
            "/claim/request": {
                "error": "MergePaid refused this (409).", "status": 409, "code": "pot_unfunded",
                "detail": "Stripe no longer holds this job's whole pot (its payment was refunded, disputed or already "
                          "transferred), so it takes no claim; the MergePaid founders have been alerted.",
            },
        })
        self.assertEqual(result["status"], 409)
        self.assertEqual(result["code"], "pot_unfunded")
        self.assertIn("no longer holds", result["refusal_reason"])
        # Current generic 409 advice says job_status, whose current answer above
        # asks for a claim again. This needs the specific choose-other-work remedy.
        self.assertIn("find_work", result["next_action"])


if __name__ == "__main__":
    unittest.main()
