"""SURFACE5-1 (MCP half, round 5): a pull request into the default branch the poster moved to
after funding reads `base_retargeted`, and the MCP says someone else moved its base.

The backend's reading carries the right words (acceptance.GREY_DEFAULT_MOVED: "The repository's
default branch is not the one this job was funded on (funded_default_branch in /judging) …
Target the funded branch if it still exists; otherwise ask the poster to restore it."). The MCP
maps every `base_retargeted` to _CHECK_RETARGETED_BY_OTHER ("Someone other than you moved this
pull request's base off the repository's default branch … Change its base back to the default
branch on GitHub.") and relays the backend's words only for _CHECK_GREY/_CHECK_SHADOW, so R4-A's
"a submitted version greyed only by the base (workflow_differs_on_base, base_retargeted) relays
the backend's words" never runs for base_retargeted. Nobody moved the pull request's base, it
already targets the default branch, and the one step that helps (the funded branch) is dropped.
"""
import unittest

from mergepaid_mcp import server

GREY_DEFAULT_MOVED = ("The repository's default branch is not the one this job was funded on (funded_default_branch "
                      "in /judging), so these results don't count on their own: the MergePaid founders weigh them "
                      "before anything is counted or paid. Your changes did not cause this. Target the funded branch "
                      "if it still exists; otherwise ask the poster to restore it.")
READING = {"receipt_id": "evr_1", "source": "preflight", "recorded_at": "2026-09-27T10:00:00+00:00",
           "pull_request": 17, "head_commit": "a" * 40, "base_commit": "b" * 40, "judge_intact": False,
           "judge_reasons": ["base_retargeted"], "caution": [], "commits_by_racer": True,
           "rows": [{"id": "MP-1", "status": "passed", "solid": False, "limit": None}],
           "house_rules": [], "ready": False, "reason_codes": [], "retry_after": None,
           "next_action": GREY_DEFAULT_MOVED}


class DefaultMovedSinceFunding(unittest.TestCase):
    def test_the_racer_is_told_to_target_the_funded_branch_not_that_someone_moved_its_base(self):
        for state in ("claimed", "submitted"):
            said = server._acceptance_status(READING, "job_pack", head="a" * 40, state=state)["next_action"]
            self.assertNotIn("Someone other than you moved", said, state)
            self.assertIn("funded", said, state)


if __name__ == "__main__":
    unittest.main()
