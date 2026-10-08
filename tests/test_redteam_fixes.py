"""The red-team findings on the integrated acceptance branch that reach the eight tools:
counts the backend does not keep are never shown as 0 (ops 24); a cancelled or unreadable
check is never called a failure (ui 27); an unattributed commit and a shadowing module
name their cause (ops 17, ui 28); a pack job's delivery names the branch prefix and
--no-maintainer-edit (ui 29); the done line follows the referee (ui 26)."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import ACCEPTANCE, JOB, JUDGING, STATUS, run


def next_action(**status):
    return server._acceptance_status({**STATUS, **status}, "job_pack")["next_action"]


class RedTeamFixes(unittest.TestCase):
    def test_a_count_the_backend_did_not_send_is_left_out_never_zero(self):
        counts = server._poster_counts({"poster_record": {"posted": 3, "accepted": 1, "rejected": 0, "cancelled": 0}})
        self.assertEqual(counts, {"known": True, "posted": 3, "accepted": 1, "rejected": 0, "cancelled": 0})
        self.assertNotIn("rejected_while_ready", counts)

    def test_a_cancelled_run_is_not_a_failure(self):
        words = next_action(ready=False, rows=[{"id": "MP-1", "status": "cancelled"}])
        self.assertNotIn("did not pass", words)
        self.assertIn("cancelled", words)

    def test_a_check_that_could_not_report_points_at_the_reproduce_steps(self):
        words = next_action(ready=False, rows=[{"id": "MP-1", "status": "cant_tell"}])
        self.assertNotIn("did not pass", words)
        self.assertIn("environment_unreproducible", words)

    def test_a_failure_still_says_fix_it(self):
        words = next_action(ready=False, rows=[{"id": "MP-1", "status": "failed"}, {"id": "MP-2", "status": "cancelled"}])
        self.assertEqual(words, server._CHECK_NOT_YET)

    def test_an_unattributed_commit_names_the_email(self):
        words = next_action(commits_by_racer=False, reason_codes=["not_racer_authored"])
        self.assertIn("email", words)
        self.assertNotIn("Someone else pushed", words)

    def test_a_new_module_where_python_looks_first_is_named_as_the_cause(self):
        # With no words of the backend's own for the reading, the MCP names the cause itself.
        words = next_action(judge_intact=False, ready=False, judge_reasons=["shadow_name:tests/helpers.py"],
                            next_action=None)
        self.assertIn("new module", words)
        self.assertNotIn("checks_not_running", words)

    def test_a_pack_jobs_delivery_names_the_branch_prefix_and_no_maintainer_edit(self):
        result, _ = run(server.review_job, "job_pack", routes={"/judging": JUDGING})
        steps = " ".join(result["delivery"]["steps"])
        self.assertIn("mp-job_pack-", steps)
        self.assertIn("--no-maintainer-edit", steps)
        plain, _ = run(server.review_job, "job_pack", routes={"/judging": {**JUDGING, "acceptance": None}})
        self.assertNotIn("mp-job_pack-", " ".join(plain["delivery"]["steps"]))

    def test_a_pack_with_no_check_row_never_says_every_check_passed(self):
        words = next_action(ready=True, rows=[])
        self.assertNotIn("Every check passed", words)
        self.assertIn("no machine check", words)

    def test_the_done_line_follows_the_referee(self):
        asked = {"requested": True, "claimed": False, "approval_request_id": "req_1", "status": "pending"}
        poster = {**JOB, "owner": {"handle": "p"}, "referee": {**JOB["referee"], "kind": "poster_asserted"}}
        result, _ = run(server.claim_job, "job_pack", job=poster, routes={"/claim/request": asked})
        self.assertNotIn("poster merges", result.get("done", ""))


if __name__ == "__main__":
    unittest.main()
