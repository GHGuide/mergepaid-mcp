"""SURFACE10-3: SURFACE4-3's relay excludes pinned_file_differs from the poster's base.

The backend-produced version is in backend/tests/test_zgap10_surface_3.py.
"""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, JUDGING, STATUS, run


class BaseSidePackDrift(unittest.TestCase):
    def test_submitted_status_keeps_the_posters_restore_action(self):
        reading = {**STATUS, "judge_intact": False, "ready": False,
                   "judge_reasons": ["pinned_file_differs:mergepaid/job_pack/helper.py"],
                   "next_action": (
                       "The job's checks on the base branch are not the ones the poster funded, so these results "
                       "don't count. Your changes did not cause this, and no push can: ask the poster to restore "
                       "the job's checks on the default branch, or report checks_not_running.")}
        holder = {**HOLDER, "job_state": "submitted", "can_start_bounty": False,
                  "next_action_code": "await_review", "next_action": server.WORK_ACTIONS["await_review"]}
        result, _calls = run(server.job_status, "job_pack", job={**JOB, "state": "submitted"}, routes={
            "/work-status": holder, "/judging": {**JUDGING, "acceptance_status": reading},
            "/work": {"work": {"next_action": "Wait for the poster's review."}}})
        told = result["acceptance_status"]["next_action"]
        self.assertNotIn("push any fix", told)
        self.assertIn("ask the poster to restore", told)
        self.assertNotIn("checks_not_running", told)

    def test_a_pinned_difference_caused_by_the_racer_is_not_relabelled_as_base_only(self):
        status = {**STATUS, "judge_intact": False, "ready": False,
                  "judge_reasons": ["pinned_file_differs:mergepaid/job_pack/helper.py"]}
        told = server._check_next_plain(status, "job_pack", "submitted", "Undo your changes to the job's checks.")
        self.assertIn("push any fix", told)
        self.assertNotIn("ask the poster to restore", told)


if __name__ == "__main__":
    unittest.main()
