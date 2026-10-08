"""FX-P2: review and status agree on whether a claim request is still relevant."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import JOB
from tests.test_fx_e_qa import result, view


class ReviewRequestTests(unittest.TestCase):
    def test_ended_work_hides_stale_approved_requests_in_review_and_status(self):
        request = {"job_id": JOB["id"], "status": "approved", "expires_at": "2099-01-01"}
        for why in ("the poster sent it back", "the claim ran out", "another lane won",
                    "the poster ended your lane: No progress"):
            for tool in (server.review_job, server.job_status):
                with self.subTest(why=why, tool=tool.__name__):
                    mine = {"status": "lost", "lost_because": why,
                            "next_action": "Find other work on the Market."}
                    reply = result(tool, routes={"/claim-request": request,
                                   "/work": {"job_id": JOB["id"], "work": mine}})
                    self.assertIsNone(reply.get("claim_request"))
                    self.assertEqual(reply["next_action"], mine["next_action"])
                    self.assertFalse(reply["work_status"]["can_start_bounty"])
                    self.assertEqual(reply["work_authorization"], "not_authorized_to_start")

    def test_review_keeps_a_declined_request_and_its_bounded_poster_reason(self):
        request = {"job_id": JOB["id"], "status": "declined", "expires_at": "2099-01-01",
                   "reason": "Not this time. " * 100}
        mine = {"status": "lost", "lost_because": "the poster declined the request",
                "next_action": "Find other work on the Market."}
        for tool in (server.review_job, server.job_status):
            with self.subTest(tool=tool.__name__):
                reply = result(tool, routes={"/claim-request": request,
                               "/work": {"job_id": JOB["id"], "work": mine}})
                self.assertEqual(reply["claim_request"]["status"], "declined")
                self.assertEqual(reply["claim_request"]["poster_reason"], request["reason"][:500])
                self.assertEqual(reply["next_action"], mine["next_action"])

    def test_review_keeps_the_current_pending_request_after_an_ended_claim(self):
        request = {"job_id": JOB["id"], "status": "pending", "expires_at": "2099-01-01"}
        mine = {"status": "requested", "next_action": "Wait for the poster to approve or decline your request."}
        reply = result(server.review_job, routes={"/claim-request": request,
                       "/work-status": view(action="await_claim_decision"),
                       "/work": {"job_id": JOB["id"], "work": mine}})
        self.assertEqual(reply["claim_request"]["status"], "pending")
        self.assertEqual(reply["next_action"], server.REQUEST_ACTIONS["pending"])
        self.assertFalse(reply["work_status"]["can_start_bounty"])


if __name__ == "__main__":
    unittest.main()
