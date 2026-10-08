"""TRUTH-2 (MCP half): completion and rejection guidance name the held-out row.

Active regressions check find_work's held_out count, claim_job's one-line
"Done =" guidance and rejection_needs_failing_row wording. Both guidance paths
name held-out work; these tests have no expectedFailure marker.
"""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import JOB, SUMMARY, run

HELD = {**JOB, "acceptance_summary": {**SUMMARY, "held_out": 1}}


class DoneNamesTheHeldOutRow(unittest.TestCase):
    def test_find_work_counts_it_today(self):
        found, _ = run(server.find_work, routes={"/api/discovery/jobs": [HELD]})
        self.assertEqual(found["recommendation"]["acceptance_summary"]["held_out"], 1)

    def test_claim_jobs_done_line_names_the_held_out_row(self):
        claimed, _ = run(server.claim_job, "job_pack", job=HELD, routes={
            "/claim/request": {"claimed": False, "approval_delivery": "poster_account", "expires_at": "x"}})
        self.assertRegex(claimed["done"].lower(), r"held[- ]out")

    def test_what_the_poster_may_name_includes_a_revealed_held_out_row(self):
        self.assertRegex(server._CODE_ACTIONS["rejection_needs_failing_row"].lower(), r"held[- ]out")


if __name__ == "__main__":
    unittest.main()
