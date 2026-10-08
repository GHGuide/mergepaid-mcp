"""GAP SURFACE9-4 (MCP half): a merge a restore's founders' item holds is relayed as a merge
waiting for its checks. The backend's hold (backend/tests/test_zgap9_surface9_4.py, read from a
real restore) is `merged_unverified_head`, `ruling: null`, `poster_can_confirm: false`, with the
restore's words; job_status keys its words on reason_code, so the racer's agent reads "the job's
checks on the merged version have not finished or did not pass … Wait: it settles on its own once
this version's checks pass, or when the poster confirms the merge." The checks already read ready,
the poster's confirm answers 409 restored_lost_window, and nothing settles until the founders rule.
"""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, JUDGING, run

RESTORED = ("MergePaid was restored from a backup that may have lost recent records on this job, so nothing on it "
            "pays, refunds or takes a new claim until the MergePaid founders check what happened.")
HOLD = {"status": "held", "reason_code": "merged_unverified_head", "reason": RESTORED, "next_action": RESTORED,
        "poster_can_confirm": False, "poster_can_reject": False, "ruling": None, "restored": True,
        "racer_next_action": "Nothing is needed from you: MergePaid was restored from a backup that may have lost "
                             "recent records on this job, and the MergePaid founders check what happened before "
                             "anything pays.",
        "waiting_on": "the MergePaid founders check what a restore from a backup lost on this job"}


class RestoredHoldWords(unittest.TestCase):
    def test_a_merge_a_restore_holds_is_not_said_to_settle_on_its_own(self):
        submitted = {**HOLDER, "job_state": "submitted", "next_action_code": "await_review",
                     "next_action": server.WORK_ACTIONS["await_review"], "can_start_bounty": False}
        status = run(server.job_status, "job_pack", job={**JOB, "state": "submitted", "acceptance_hold": HOLD},
                     routes={"/judging": JUDGING, "/work-status": submitted, "/work": {"job_id": "job_pack", "work": {}}})[0]
        said = " ".join((status["summary"], status["next_action"]))
        self.assertIn("acceptance_hold", status)
        self.assertNotIn("settles on its own", said)
        self.assertNotIn("poster confirms", said)
        self.assertIs(status["acceptance_hold"].get("restored"), True)


if __name__ == "__main__":
    unittest.main()
