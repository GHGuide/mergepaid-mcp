"""SURFACE4-3 (MCP half, round 4): a submitted version whose results don't count only because the
poster changed the job's checks on the default branch.

The backend's reading says so (acceptance.GREY_BY_BASE: "Your changes did not cause this, and
no push can: ask the poster to restore the job's checks on the default branch, or report
checks_not_running"). `_check_next_plain` relays the backend's words only while the job is
open or claimed; once submitted it answers with _CHECK_GREY's submitted form: "it changed the
job's checks, CI or test setup, or the base branch's checks differ … push any fix to the same
pull request, and the poster reviews that version". The agent is told to push a fix no push
can make, and a pushed head that then fails a check is read ahead of the ready version it
submitted (design §6.5 "Which version": the newest judged head since the submit stands).
"""
import unittest

from mergepaid_mcp import server

GREY_BY_BASE = ("The job's checks on the base branch are not the ones the poster funded, so these results don't "
                "count. Your changes did not cause this, and no push can: ask the poster to restore the job's "
                "checks on the default branch, or report checks_not_running.")
READING = {"receipt_id": "evr_1", "source": "review", "recorded_at": "2026-09-27T10:00:00+00:00",
           "pull_request": 17, "head_commit": "a" * 40, "base_commit": "b" * 40, "judge_intact": False,
           "judge_reasons": ["workflow_differs_on_base"], "caution": [], "commits_by_racer": True,
           "rows": [{"id": "MP-1", "status": "passed", "solid": False, "limit": "this version changed your checks"}],
           "house_rules": [], "ready": False, "reason_codes": [], "retry_after": None, "next_action": GREY_BY_BASE}


class SubmittedGreyByBase(unittest.TestCase):
    def test_a_submitted_racer_is_not_told_to_push_a_fix_for_the_posters_base_change(self):
        claimed = server._acceptance_status(READING, "job_pack", head="a" * 40, state="claimed")
        self.assertIn("no push can", claimed["next_action"])  # the backend's own words, relayed
        submitted = server._acceptance_status(READING, "job_pack", head="a" * 40, state="submitted")
        self.assertNotIn("push any fix", submitted["next_action"])


if __name__ == "__main__":
    unittest.main()
