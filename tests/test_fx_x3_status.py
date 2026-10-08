"""FX-X3: job_status prefers the racer's fresh work result to its submit receipt."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import JOB, JUDGING, STATUS, run
from tests.test_fx_e_qa import view


class LiveWorkStatusTests(unittest.TestCase):
    def test_status_uses_live_failure_after_a_running_submission(self):
        stale = {**STATUS, "source": "submit", "ready": False,
                 "rows": [{"id": "MP-1", "status": "running", "solid": False}]}
        live = {**stale, "source": "live", "receipt_id": None,
                "rows": [{"id": "MP-1", "status": "failed", "solid": False}]}
        mine = {"status": "submitted", "acceptance_status": live,
                "next_action": "Fix the failing check and push; the poster reviews after."}
        reply = run(server.job_status, JOB["id"], job={**JOB, "state": "submitted"}, routes={
            "/work-status": view("submitted", "you", "await_review"),
            "/judging": {**JUDGING, "acceptance_status": stale},
            "/work": {"job_id": JOB["id"], "work": mine},
        })[0]
        self.assertEqual(reply["acceptance_status"]["source"], "live")
        self.assertEqual(reply["acceptance_status"]["rows"][0]["status"], "failed")
        self.assertEqual(reply["next_action"], mine["next_action"])
        self.assertEqual(reply["work_status"]["next_action"], reply["next_action"])
        self.assertFalse(reply["work_status"]["can_start_bounty"])

    def test_status_uses_the_live_head_instead_of_an_older_failed_receipt(self):
        stale = {**STATUS, "source": "submit", "ready": False,
                 "rows": [{"id": "MP-1", "status": "failed", "solid": False}]}
        live = {**STATUS, "source": "live", "receipt_id": None, "head_commit": "c" * 40}
        mine = {"status": "submitted", "acceptance_status": live,
                "next_action": "Wait for the poster's review."}
        reply = run(server.job_status, JOB["id"], job={**JOB, "state": "submitted"}, routes={
            "/work-status": view("submitted", "you", "await_review"),
            "/judging": {**JUDGING, "acceptance_status": stale,
                         "your_submission": {"head_commit": stale["head_commit"]}},
            "/work": {"job_id": JOB["id"], "work": mine},
        })[0]
        self.assertEqual(reply["acceptance_status"]["head_commit"], live["head_commit"])
        self.assertTrue(reply["acceptance_status"]["current"])
        self.assertTrue(reply["acceptance_status"]["ready"])
        self.assertNotIn("Fix the failing", reply["next_action"])
        self.assertEqual(reply["work_status"]["next_action"], reply["next_action"])


if __name__ == "__main__":
    unittest.main()
