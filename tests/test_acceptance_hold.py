"""A merge GitHub reported that has not settled: job_status says why and what next."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from mergepaid_mcp import server

JOB = {"id": "job_held", "state": "submitted", "title": "Fix", "amount_usd": 100, "lanes": 1,
       "pr_url": "https://github.com/acme/api/pull/7",
       "acceptance_hold": {"status": "held", "reason_code": "authorization_missing",
                           "reason": "poster-side words", "next_action": "Authorize the repository",
                           "poster_can_confirm": True}}


def status(job):
    def backend(method, path, **kwargs):
        if path.endswith("/work-status"):
            return {"error": "not needed here"}
        return deepcopy(job)

    with patch.object(server, "TOKEN", "sup_token"), patch.object(server, "_call", side_effect=backend):
        return server.job_status(job["id"])


class AcceptanceHoldTests(unittest.TestCase):
    def test_a_held_merge_surfaces_its_reason_and_one_next_action(self):
        result = status(JOB)
        hold = result["acceptance_hold"]
        self.assertEqual(hold["reason_code"], "authorization_missing")
        self.assertIn("has not settled", hold["reason"])
        self.assertEqual(result["summary"], hold["reason"])
        self.assertEqual(result["next_action"], hold["next_action"])
        self.assertIn("poster", result["next_action"])
        # The backend's own words never cross into the agent's channel.
        self.assertNotIn("poster-side words", repr(result))

    def test_a_merge_before_the_submission_says_the_poster_decides(self):
        held = {**JOB["acceptance_hold"], "reason_code": "merged_before_submission", "poster_can_reject": True}
        result = status({**JOB, "acceptance_hold": held})
        self.assertEqual(result["acceptance_hold"]["reason_code"], "merged_before_submission")
        self.assertIn("before it was submitted", result["summary"])
        self.assertIn("send the work back", result["next_action"])

    def test_a_head_another_job_holds_says_the_poster_decides(self):
        held = {**JOB["acceptance_hold"], "reason_code": "shared_head", "poster_can_reject": True}
        result = status({**JOB, "acceptance_hold": held})
        self.assertEqual(result["acceptance_hold"]["reason_code"], "shared_head")
        self.assertIn("same head commit", result["summary"])
        self.assertIn("send the work back", result["next_action"])

    def test_a_copy_check_github_has_not_answered_says_it_waits(self):
        held = {**JOB["acceptance_hold"], "reason_code": "copy_check_pending", "poster_can_reject": True}
        result = status({**JOB, "acceptance_hold": held})
        self.assertEqual(result["acceptance_hold"]["reason_code"], "copy_check_pending")
        self.assertIn("has not yet confirmed", result["summary"])
        self.assertIn("nothing is needed from you", result["next_action"])

    def test_an_authorship_mismatch_tells_the_racer_whose_account_github_named(self):
        held = {**JOB["acceptance_hold"], "reason_code": "authorship_mismatch", "poster_can_reject": True}
        result = status({**JOB, "acceptance_hold": held})
        self.assertEqual(result["acceptance_hold"]["reason_code"], "authorship_mismatch")
        self.assertIn("author", result["summary"])
        self.assertIn("GitHub account your racer belongs to", result["next_action"])

    def test_a_ruled_copy_never_reads_as_a_ruling_for_the_racer(self):
        # SURFACE7-2: a copy item ruled anything but not_a_copy (its for_racer is the earlier racer's).
        for code in ("prior_work_overlap", "version_unread"):
            held = {**JOB["acceptance_hold"], "reason_code": code, "poster_can_confirm": False, "ruling": "copy"}
            result = status({**JOB, "acceptance_hold": held})
            self.assertEqual(result["acceptance_hold"]["ruling"], "copy")
            self.assertIn("not paid through MergePaid", result["summary"])
            self.assertNotIn("for you", result["summary"])
            self.assertNotIn("Wait for the founders", result["next_action"])

    def test_a_copy_review_before_any_merge_relays_the_backends_words(self):
        # SURFACE7-2: a copy item holds the holder's submitted version; /work says what a merge does.
        from tests.test_acceptance_loop import HOLDER, JOB as PACK_JOB, JUDGING, STATUS, run
        told = ("The MergePaid founders compare this version with an earlier racer's ready work by hand before a "
                "merge of it can pay. Nothing is needed from you.")
        submitted = {**HOLDER, "job_state": "submitted", "next_action_code": "await_review",
                     "next_action": server.WORK_ACTIONS["await_review"], "can_start_bounty": False}
        result = run(server.job_status, "job_pack", job={**PACK_JOB, "state": "submitted"},
                     routes={"/judging": {**JUDGING, "acceptance_status": {**STATUS, "ready": False,
                                 "rows": [{**STATUS["rows"][0], "status": "failed"}]}}, "/work-status": submitted,
                             "/work": {"job_id": "job_pack", "work": {"next_action": told}}})[0]
        self.assertEqual(result["next_action"], told)

    def test_a_failed_check_does_not_restart_work_on_a_pot_settled_by_hand(self):
        from tests.test_acceptance_loop import HOLDER, JOB as PACK_JOB, JUDGING, STATUS, run
        failed = {**STATUS, "ready": False, "rows": [{**STATUS["rows"][0], "status": "failed"}]}
        submitted = {**HOLDER, "job_state": "submitted", "next_action_code": "await_review",
                     "next_action": server.WORK_ACTIONS["await_review"], "can_start_bounty": False}
        result = run(server.job_status, "job_pack", job={**PACK_JOB, "state": "submitted"},
                     routes={"/judging": {**JUDGING, "acceptance_status": failed}, "/work-status": submitted,
                             "/work": {"job_id": "job_pack", "work": {"pot_settled_by_hand": True}}})[0]
        self.assertEqual(result["next_action"], server._POT_SETTLED[1])
        self.assertEqual(result["summary"], server._POT_SETTLED[0])

    def test_no_hold_or_an_unknown_code_changes_nothing(self):
        for hold in (None, {"reason_code": "something new"}):
            result = status({**JOB, "acceptance_hold": hold})
            self.assertNotIn("acceptance_hold", result)
        self.assertNotIn("acceptance_hold", status({**JOB, "state": "paid"}))

    def test_unknown_legacy_order_keeps_its_actual_remedy(self):
        for ruling in (None, "for_racer"):
            held = {**JOB["acceptance_hold"], "reason_code": "merged_unverified_head",
                    "legacy_order_unknown": True, "ruling": ruling,
                    "reason": "Passing checks cannot establish the missing history.",
                    "racer_next_action": "Wait for the founders to resolve the older record."}
            result = status({**JOB, "acceptance_hold": held})
            self.assertEqual(result["summary"], held["reason"])
            self.assertEqual(result["next_action"], held["racer_next_action"])
            self.assertTrue(result["acceptance_hold"]["legacy_order_unknown"])


if __name__ == "__main__":
    unittest.main()
