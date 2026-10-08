"""TRUTH-1 (MCP half): a send-back relays revealed cases and the missed rubric item.

Active regressions check that job_status carries the work endpoint's row_ids,
rubric_index and held_out cases_file. The cases remain text within the MCP
untrusted-data fence. These tests have no expectedFailure marker.
"""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, JUDGING, run

CASES = '[{"input": "a+b@example.com", "output": 200}]\n'
WORK = {"job_id": "job_pack", "work": {"changes_open": True, "change_requests": [{
    "message": "Two things.", "requested_at": "t", "pr_url": "https://github.com/acme/widget/pull/17",
    "row_ids": ["MP-4", "MP-6"], "example_index": {}, "rubric_index": {"MP-4": 1},
    "held_out": {"row_id": "MP-6", "sha256": "a" * 64, "bytes": len(CASES), "cases_file": CASES}}]}}


def status():
    return run(server.job_status, "job_pack", job={**JOB, "state": "claimed"},
               routes={"/judging": JUDGING, "/work-status": HOLDER, "/work": WORK})[0]


class HeldOutRevealReachesTheRacer(unittest.TestCase):
    def test_the_rows_are_relayed_today(self):
        self.assertEqual(status()["change_request"]["row_ids"], ["MP-4", "MP-6"])

    def test_the_revealed_cases_reach_the_agent(self):
        # The cases file travels as text: json.dumps would escape its quotes (shape adjusted by R2-C).
        self.assertIn(CASES.strip(), status()["change_request"]["held_out"]["cases_file"])

    def test_the_rubric_item_reaches_the_agent(self):
        self.assertEqual(status()["change_request"].get("rubric_index"), {"MP-4": 1})


if __name__ == "__main__":
    unittest.main()
