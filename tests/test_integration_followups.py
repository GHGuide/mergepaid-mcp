"""Acceptance audit round 1 › P6: the words the eight tools say for what P1-P4 built. A
base that is not the default branch, a report that went missing, a run that timed out and
a read across a push each say what happened; runs waiting on the poster say the racer may
submit (FAIR-13), and never to work already submitted; a version someone else pushed says
so; a job a dispute holds says why no claim is taken (FAIR-15); an in-process green is
nameable (JUDGE-4); the stub lists the backend's four reproduce steps (P3)."""
import unittest

from mergepaid_mcp import server
from tests import stub_backend
from tests.test_acceptance_loop import STATUS, run

FAILED = {"ready": False, "rows": [{"id": "MP-1", "status": "failed", "solid": False, "limit": None}]}


def words(state="claimed", **status):
    return server._acceptance_status({**STATUS, **status}, "job_pack", state=state)["next_action"]


class P6IntegrationFollowUps(unittest.TestCase):
    def test_runs_waiting_on_the_poster_say_the_racer_may_submit_now(self):
        waiting = {"ready": False, "reason_codes": ["awaiting_approval"],
                   "rows": [{"id": "MP-1", "status": "awaiting_approval"}]}
        for state in ("claimed", "open", None):
            said = words(state, **waiting)
            self.assertIn("submit it now with submit_work", said, state)
            self.assertIn("never counts as your failure", said)
        for state in ("submitted", "merged", "paid"):
            said = words(state, **waiting)
            self.assertNotIn("submit it now", said, state)
            self.assertIn("approves the runs", said)

    def test_a_version_someone_else_pushed_says_so(self):
        said = words(commits_by_racer=False, reason_codes=["not_racer_authored"])
        self.assertIn("someone else pushed this version", said)
        self.assertIn("email", said)

    def test_a_pull_request_on_another_base_says_to_change_its_base(self):
        grey = {"ready": False, "judge_intact": False,
                "judge_reasons": ["base_not_default_branch", "pinned_file_differs:mergepaid/job_pack/examples.json"],
                "next_action": None}
        said = words(**grey)
        self.assertIn("default branch", said)
        self.assertNotIn("changed the job's checks", said)
        submitted = words("submitted", **grey)
        self.assertIn("default branch", submitted)
        for refused in ("check_only=true", "report ", "changed the job's checks"):
            self.assertNotIn(refused, submitted)

    def test_a_grey_the_racers_pull_request_caused_without_changing_a_check_names_its_cause(self):
        for reason, cause in (("files_incomplete", "did not list every file"),
                              ("run_base_unknown", "disagree about which base")):
            grey = {"ready": False, "judge_intact": False, "judge_reasons": [reason], "next_action": None}
            for state in ("claimed", "submitted"):
                said = words(state, **grey)
                self.assertIn(cause, said, (reason, state))
                self.assertNotIn("changed the job's checks", said)
            self.assertIn("same pull request", words("submitted", **grey))

    def test_a_read_across_a_push_judges_nothing(self):
        moved = {"ready": False, "judge_intact": False, "judge_reasons": ["head_moved"], "next_action": None}
        self.assertEqual(words(**moved), server._CHECK_MOVED)
        self.assertNotIn("changed the job's checks", words(**moved))
        self.assertNotIn("check_only=true", words("submitted", **moved))

    def test_a_lost_report_or_a_timeout_is_a_failure_named_as_such(self):
        for code in ("report_lost", "run_timed_out"):
            self.assertEqual(words(**FAILED, reason_codes=[code]), server._CHECK_LOST, code)
            submitted = words("submitted", **FAILED, reason_codes=[code])
            self.assertIn("counts as a failure", submitted)
            self.assertIn("same pull request", submitted)
            self.assertNotIn("check_only=true", submitted)
        # A success already seen on the head stands: a code with every row passed is no failure.
        self.assertEqual(words(reason_codes=["report_lost"]), server._CHECK_READY_RECORDED)
        # Still running comes first, as the backend says.
        running = {"ready": False, "reason_codes": ["report_lost"],
                   "rows": [{"id": "MP-1", "status": "failed"}, {"id": "MP-2", "status": "running"}]}
        self.assertEqual(words(**running), server._CHECK_RUNNING)

    def test_a_job_a_dispute_holds_says_why_no_claim_is_taken(self):
        held = {"error": "MergePaid refused this (409).", "status": 409, "code": "dispute_holds_job",
                "detail": "A dispute on this job is with the MergePaid founders, so it takes no new claim until "
                          "they close it."}
        result, _ = run(server.claim_job, "job_pack", routes={"/claim/request": held, "/work-status": {"error": "x"}})
        self.assertEqual((result["code"], result["next_action"]),
                         ("dispute_holds_job", server._CODE_ACTIONS["dispute_holds_job"]))
        self.assertIn("find_work", result["next_action"])
        self.assertEqual(result["refusal_reason"], held["detail"])

    def test_the_send_back_rule_names_an_in_process_green(self):
        self.assertIn("not independently verified", server._CODE_ACTIONS["rejection_needs_failing_row"])

    def test_the_stub_lists_the_backends_four_reproduce_steps(self):
        reproduce = stub_backend.ACCEPTANCE["reproduce"]
        self.assertEqual(reproduce["steps"], ["prepare", "setup", "row", "verify"])
        self.assertEqual([c.rsplit(" ", 1)[1] for c in reproduce["commands"]], reproduce["steps"])


if __name__ == "__main__":
    unittest.main()
