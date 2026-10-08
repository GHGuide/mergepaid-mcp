"""submit_work after the final integration: collaboration's hand-back note (wave 3) and the
acceptance pack's check, evidence and honest exit (wave 4) on one tool. A note goes only
with a real submission: never with a check that records nothing, never with a blocker."""
import inspect
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import JOB, run

PR = "https://github.com/acme/widget/pull/17"


class SubmitWorkTakesBothWaves(unittest.TestCase):
    def test_one_tool_takes_the_note_the_check_and_the_blocker(self):
        params = set(inspect.signature(server.submit_work).parameters)
        self.assertEqual(params, {"job_id", "pr_url", "tokens_used", "message", "check_only", "evidence_urls",
                                  "blocker_code", "blocker_note", "evidence", "patch", "deliverable_url", "note"})
        self.assertEqual(inspect.getsource(server).count("@mcp.tool("), 8)

    def test_a_note_never_rides_a_check_that_records_nothing(self):
        result, calls = run(server.submit_work, "job_pack", PR, check_only=True, message="fixed the + case",
                            job={**JOB, "state": "claimed"})
        self.assertIn("error", result)
        self.assertIn("message", result["error"])
        self.assertFalse([c for c in calls if c[1].endswith(("/submit", "/submit/preflight", "/changes/messages"))])

    def test_a_note_never_rides_a_blocker(self):
        result, calls = run(server.submit_work, "job_pack", blocker_code="ambiguous", blocker_note="which input?",
                            message="fixed it", job={**JOB, "state": "claimed"})
        self.assertIn("error", result)
        self.assertFalse([c for c in calls if c[1].endswith(("/blockers", "/changes/messages"))])


class SubmittedWorkNeverPointsAtARefusedCall(unittest.TestCase):
    """Once the work is submitted, a blocker and check_only answer 403: a reading that is
    not ready says to push to the same pull request, as the top-level next_action does."""

    def test_a_grey_failed_unreadable_or_older_reading_after_submission(self):
        from tests.test_acceptance_loop import STATUS
        readings = ({**STATUS, "ready": False, "judge_intact": False, "judge_reasons": ["workflow_changed"]},
                    {**STATUS, "ready": False, "rows": [{"id": "MP-1", "status": "failed"}]},
                    {**STATUS, "ready": False, "rows": [{"id": "MP-1", "status": "cant_tell"}]},
                    {**STATUS, "current": False})
        for reading in readings:
            claimed = server._check_next(reading, "job_pack", "claimed")
            words = server._check_next(reading, "job_pack", "submitted")
            for refused in ("report ", "checks_not_running", "criteria_conflict", "environment_unreproducible",
                            "check_only=true"):
                self.assertNotIn(refused, words, reading)
            self.assertIn("same pull request" if "older" not in claimed else "current version", words)


if __name__ == "__main__":
    unittest.main()
