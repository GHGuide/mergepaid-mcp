"""SURFACE11-2: a superseded reading asks for a retry, not changes to the app."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, JUDGING, STATUS, run


class ChangedRecordedFacts(unittest.TestCase):
    def test_job_status_preserves_the_recorded_facts_retry(self):
        reading = {**STATUS, "judge_intact": None, "ready": None, "commits_by_racer": None,
                   "reason_codes": ["recorded_facts_changed"], "retry_after": 60,
                   "rows": [{"id": "MP-1", "status": "cant_tell", "solid": False, "limit": None}],
                   "next_action": "Recorded facts changed while these checks were read; check again in a minute."}
        holder = {**HOLDER, "job_state": "submitted", "can_start_bounty": False,
                  "next_action_code": "await_review", "next_action": server.WORK_ACTIONS["await_review"]}
        result, _calls = run(server.job_status, "job_pack", job={**JOB, "state": "submitted"}, routes={
            "/work-status": holder, "/judging": {**JUDGING, "acceptance_status": reading},
            "/work": {"work": {"next_action": "Wait for the poster's review."}}})
        told = result["acceptance_status"]["next_action"]
        self.assertIn("check again", told.lower())
        self.assertNotIn("push", told.lower())
