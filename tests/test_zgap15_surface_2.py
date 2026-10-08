"""SURFACE15-2: sealed MCP reads must preserve a spent pot's fixed warning.

The real two-racer backend sequence is in backend/tests/test_zgap15_surface_2.py.
"""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, run


WORDS = ("The MergePaid founders settled an earlier racer's claim on this job by hand, "
         "so a merge of your work cannot pay through MergePaid. Ask them before you go on.")


class SealedSettlementWords(unittest.TestCase):
    def check_tool(self, tool):
        job = {**JOB, "sealed": True, "state": "claimed"}
        own = {"job_id": JOB["id"], "work": {
            "status": "holding", "pot_settled_by_hand": True,
            "can_dispute": True, "next_action": WORDS}}
        result, _ = run(tool, JOB["id"], job=job, routes={
            "/work-status": HOLDER, "/work": own, "/bundle": {"files": []}})
        self.assertIn("by hand", result["next_action"])
        self.assertIn("open a dispute from your lane", result["next_action"])
        self.assertIs(result["pot_settled_by_hand"], True)
        self.assertNotEqual("Review your bundle and submit a patch.", result["next_action"])

    def test_review_warns_that_the_sealed_pot_was_settled_elsewhere(self):
        """GAP SURFACE15-2: review loses the existing hand-settlement warning."""
        self.check_tool(server.review_job)

    def test_status_warns_that_the_sealed_pot_was_settled_elsewhere(self):
        """GAP SURFACE15-2: status loses the existing hand-settlement warning."""
        self.check_tool(server.job_status)

    def test_funding_loss_keeps_hand_settlement_but_stops_unfinished_work(self):
        job = {**JOB, "sealed": True, "state": "claimed"}
        unavailable = {**HOLDER, "can_start_bounty": False,
                       "next_action_code": "wait_for_owner", "next_action": server._POT_UNAVAILABLE}
        mine_settled = "Nothing more is needed from you: the MergePaid founders settled this work with you by hand."
        cases = [
            ({"pot_settled_by_hand": True, "next_action": WORDS}, WORDS),
            ({"next_action": mine_settled}, mine_settled),
            ({"next_action": "Review your bundle and submit a patch."}, server._POT_UNAVAILABLE),
            ({"next_action": "MergePaid was restored from a backup; wait for the founders."}, server._POT_UNAVAILABLE),
        ]
        for tool in (server.review_job, server.job_status):
            for mine, expected in cases:
                with self.subTest(tool=tool.__name__, mine=mine):
                    result, calls = run(tool, JOB["id"], job=job, routes={
                        "/work-status": unavailable,
                        "/work": {"job_id": JOB["id"], "work": {"status": "holding", **mine}},
                    })
                    self.assertEqual(result["next_action"], expected)
                    self.assertEqual(result["work_authorization"], "not_authorized_to_start")
                    self.assertFalse(any(path.endswith("/bundle") for _, path, _ in calls))

    def test_minimized_hold_and_restore_guidance_survives_both_tools(self):
        job = {**JOB, "sealed": True, "state": "claimed"}
        for tool in (server.review_job, server.job_status):
            for words in (
                "MergePaid was restored from a backup; retry the same patch and idempotency key.",
                "The MergePaid founders are deciding whether this pot is owed to an earlier racer. Wait for them.",
            ):
                with self.subTest(tool=tool.__name__, words=words):
                    result, _ = run(tool, JOB["id"], job=job, routes={
                        "/work-status": HOLDER, "/bundle": {"files": []},
                        "/work": {"job_id": JOB["id"], "work": {"status": "holding", "next_action": words}},
                    })
                    self.assertEqual(result["next_action"], words)

    def test_missing_work_status_never_inherits_permission_from_own_work(self):
        job = {**JOB, "sealed": True, "state": "claimed"}
        for tool in (server.review_job, server.job_status):
            with self.subTest(tool=tool.__name__):
                result, calls = run(tool, JOB["id"], job=job, routes={
                    "/work-status": {},
                    "/work": {"job_id": JOB["id"], "work": {
                        "status": "holding", "next_action": "Review your bundle and submit a patch."}},
                })
                self.assertEqual(result["work_authorization"], "unknown")
                self.assertNotEqual(result["next_action"], "Review your bundle and submit a patch.")
                self.assertFalse(any(path.endswith("/bundle") for _, path, _ in calls))


if __name__ == "__main__":
    unittest.main()
