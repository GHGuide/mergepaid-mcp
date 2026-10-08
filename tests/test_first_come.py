"""First-come presentation never turns an agent request into a human seat."""
import json
import unittest

from mergepaid_mcp import server
from test_racer import JOB, run


class FirstComeTests(unittest.TestCase):
    def job(self, **extra):
        return {**JOB, "approval_mode": "racer", "attempts_left": 1,
                "funded_usd": 200, "auto_raise": {"ceiling_usd": 200}, "pot_raises": [], **extra}

    def work_status(self, *, state="claimed", action="assigned_elsewhere"):
        waiting = state == "open"
        packet = {"schema": "supplier-job-work-v2", "job_id": "job_fit", "job_state": state,
                "assignment": "unassigned" if waiting else "other",
                "project": {"status": "standalone", "dependencies": "not_applicable"},
                "claim": {"status": "none" if waiting else "other"}, "can_start_bounty": False,
                "next_action_code": action, "next_action": server.WORK_ACTIONS[action],
                "authority_scope": "MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY",
                "functional_completion": {"status": "none", "authority": None},
                "can_submit_pr": False, "submission_authority": "NONE"}
        return {"work_status": packet, "approval_mode": "racer", "attempts_left": 1}

    def test_claim_requests_human_take_and_first_tap_without_a_link(self):
        link = server.API + "/api/jobs/job_fit/approve?request_id=crq_fixture"
        result, calls = run(server.claim_job, "job_fit", job=self.job(), routes={
            "/credentials": {"credential": "operation-secret"},
            "/claim/request": {"claimed": False, "approval_delivery": "racer_owner_account",
                               "approve_url": link, "claim_token": "must-not-leak"}})
        self.assertFalse(result["claimed"])
        self.assertIn("Take it", result["summary"])
        self.assertIn("first tap wins", result["summary"])
        self.assertNotIn("approve_url", result)
        self.assertEqual(result["next_action"],
                         "Ask your human to open MergePaid (Inbox or the job page) and tap Take it.")
        self.assertEqual(result["attempts_left"], 1)
        for secret in ("operation-secret", "must-not-leak", "funded_usd", "auto_raise", "pot_raises"):
            self.assertNotIn(secret, json.dumps(result))
        self.assertFalse(any(path.endswith(("/claim/take", "/claim/approve")) for _, path, _ in calls))

    def test_claim_drops_a_capability_url(self):
        result, _ = run(server.claim_job, "job_fit", job=self.job(), routes={
            "/credentials": {"credential": "operation-secret"},
            "/claim/request": {"approval_delivery": "racer_owner_account",
                               "approve_url": server.API + "/api/jobs/job_fit/approve?request_id=x&token=secret"}})
        self.assertNotIn("approve_url", result)

    def test_claim_null_link_uses_the_same_exact_human_instruction(self):
        result, _ = run(server.claim_job, "job_fit", job=self.job(), routes={
            "/credentials": {"credential": "operation-secret"},
            "/claim/request": {"approval_delivery": "racer_owner_account", "approve_url": None}})
        self.assertNotIn("approve_url", result)
        self.assertEqual(result["next_action"],
                         "Ask your human to open MergePaid (Inbox or the job page) and tap Take it.")

    def test_poster_mode_legacy_approval_link_is_unchanged(self):
        link = server.API + "/api/jobs/job_fit/approve?request_id=crq_fixture"
        result, _ = run(server.claim_job, "job_fit", job=self.job(approval_mode="poster"), routes={
            "/credentials": {"credential": "operation-secret"},
            "/claim/request": {"approval_delivery": "poster_capability", "approve_url": link}})
        self.assertEqual(result["approve_url"], link)

    def test_review_status_and_discovery_show_current_pot_and_attempts_only(self):
        job = self.job()
        for tool in (server.review_job, server.job_status):
            result, _ = run(tool, "job_fit", job=job)
            self.assertEqual(result["gross_payout_usd"], 100)
            self.assertEqual(result["claim_rule"], "first come")
            self.assertEqual(result["attempts_left"], 1)
            self.assertFalse({"auto_raise", "funded_usd", "pot_raises"} & set(result))
        card = server._decision_card(job)
        self.assertEqual(card["claim_rule"], "first come")
        self.assertEqual(card["attempts_left"], 1)
        self.assertNotIn("attempts_left", server._decision_card(self.job(attempts_left=2)))
        self.assertEqual(server._decision_card(self.job(approval_mode="poster"))["claim_rule"],
                         "the poster approves each racer")

    def test_lost_last_lane_has_one_clear_next_action(self):
        routes = {
            "/work-status": self.work_status(),
            "/work": {"job_id": "job_fit", "attempts_left": 1,
                      "work": {"status": "lost", "lost_because": "someone else took the job",
                               "next_action": "Find other work on the Market."}},
            "/claim-request": {"job_id": "job_fit", "status": "superseded", "reason_code": "lanes_full",
                               "expires_at": "2026-10-01T12:00:00+00:00"}}
        for tool in (server.review_job, server.job_status):
            with self.subTest(tool=tool.__name__):
                result, calls = run(tool, "job_fit", job=self.job(state="claimed"), routes=routes)
                self.assertEqual(result["next_action"], "Another racer took the last lane. Find other work.")
                self.assertEqual(result["claim_request"]["reason_code"], "lanes_full")
                self.assertEqual(result["work_status"]["next_action"], result["next_action"])
                self.assertFalse(result["work_status"]["can_start_bounty"])
                self.assertFalse(result["work_status"]["can_submit_pr"])
                self.assertTrue(any(path.endswith("/work") for _, path, _ in calls))
                if tool is server.job_status:
                    self.assertEqual(result["summary"], result["next_action"])

    def test_pending_take_never_says_the_poster_decides(self):
        routes = {
            "/work-status": self.work_status(state="open", action="await_claim_decision"),
            "/work": {"job_id": "job_fit", "work": {"status": "requested",
                      "next_action": "Wait for the poster to approve or decline your request."}},
            "/claim-request": {"job_id": "job_fit", "status": "pending",
                               "expires_at": "2026-10-01T12:00:00+00:00"}}
        for tool in (server.review_job, server.job_status):
            with self.subTest(tool=tool.__name__):
                result, _ = run(tool, "job_fit", job=self.job(), routes=routes)
                self.assertIn("Take it", result["next_action"])
                self.assertIn("first tap wins", result["next_action"])
                self.assertNotIn("poster", result["next_action"])
                self.assertFalse(result["work_status"]["can_start_bounty"])
                if tool is server.job_status:
                    self.assertIn("Take it", result["summary"])
                    self.assertNotIn("poster", result["summary"])
