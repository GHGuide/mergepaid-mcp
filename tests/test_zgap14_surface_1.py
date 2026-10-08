"""SURFACE14-1: sealed status must still honor current work authorization."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import JOB, run
from tests.test_zgap13_surface_1 import UNFUNDED


class SealedWorkStop(unittest.TestCase):
    def test_sealed_status_preserves_recorded_pot_loss(self):
        job = {**JOB, "sealed": True, "state": "claimed", "pot_unavailable": True}
        work = {**UNFUNDED, "job_state": "claimed", "claim": {"status": "active_for_you"},
                "can_submit_pr": True, "submission_authority": "CURRENT_HUMAN_CLAIM"}
        answer, _ = run(server.job_status, "job_pack", job=job, routes={"/work-status": work})
        self.assertIn("pot is unavailable", answer["next_action"])
        self.assertIn("founders", answer["next_action"])

    def test_sealed_status_does_not_assign_someone_elses_claim(self):
        work = {**UNFUNDED, "job_state": "claimed", "assignment": "other",
                "claim": {"status": "other"}, "next_action_code": "assigned_elsewhere",
                "next_action": server.WORK_ACTIONS["assigned_elsewhere"]}
        job = {**JOB, "sealed": True, "state": "claimed", "claimed_by": "sup_other"}
        answer, _ = run(server.job_status, "job_pack", job=job, routes={"/work-status": work})
        self.assertEqual(answer["next_action"], server.WORK_ACTIONS["assigned_elsewhere"])


if __name__ == "__main__":
    unittest.main()
