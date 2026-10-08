"""TRUTH-5 (MCP half, round 3): a merge the founders settled with the racer by hand never
pays through MergePaid again (R2-A, ATTRIB-9: the hold stays for good, POST /merged answers
409 settled_by_hand, `acceptance_hold.poster_can_confirm` is false). job_status keys its
words on `reason_code` alone, so the racer's agent reads "Wait: it settles on its own once
this version's checks pass, when the poster confirms the merge, or at the end of the
poster's review time": none of the three can happen, and pending_usd keeps the payout.

Fixed (R3-A): the hold carries the founders' `ruling`, and the words follow it.
"""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, JUDGING, run

SETTLED = {"status": "held", "reason_code": "merged_unverified_head",
           "reason": "GitHub reported the merge, but the checks on the merged version have not finished or did not pass.",
           "next_action": "The MergePaid founders settled this merge with the racer by hand, so it never pays through "
                          "MergePaid again.",
           "poster_can_confirm": False, "poster_can_reject": False, "ruling": "settled_by_hand"}


class SettledByHandWords(unittest.TestCase):
    def test_a_merge_settled_by_hand_is_not_said_to_settle_on_its_own(self):
        submitted = {**HOLDER, "job_state": "submitted", "next_action_code": "await_review",
                     "next_action": server.WORK_ACTIONS["await_review"], "can_start_bounty": False}
        status = run(server.job_status, "job_pack", job={**JOB, "state": "submitted", "acceptance_hold": SETTLED},
                     routes={"/judging": JUDGING, "/work-status": submitted, "/work": {"job_id": "job_pack", "work": {}}})[0]
        said = " ".join((status["summary"], status["next_action"]))
        self.assertIn("acceptance_hold", status)
        self.assertNotIn("settles on its own", said)


if __name__ == "__main__":
    unittest.main()
