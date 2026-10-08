"""Sealed payload extensions preserve the eight tools and private handoff."""
import json
import unittest
from unittest.mock import patch

from mergepaid_mcp import server
from test_race_lanes import WORK

JOB = {"id": "job_sealed", "sealed": True, "tier": "bundle", "state": "claimed", "amount_usd": 100,
       "repo_url": "", "pr_url": None, "title": "Sealed coding task"}
DIFF = "--- a/p.py\n+++ b/p.py\n@@ -1 +1 @@\n-x=0\n+x=1\n"


class SealedTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.active = True
        self.mint_refused = False
        self.claim = 1
        self.job = dict(JOB)
        self.bundle = {"job_id": "job_sealed", "files": [{"path": "p.py", "source": "stub", "content": "x=0\n", "sha256": "a"*64}], "receipt_id": 1}
        self.token = patch.object(server, "TOKEN", "secret-bootstrap"); self.token.start()
        self.api = patch.object(server, "_call", side_effect=self.backend); self.api.start()
        self.addCleanup(self.token.stop); self.addCleanup(self.api.stop)

    def backend(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith("/work"):
            return {"job_id": "job_sealed", "work": {"claimed_event_id": self.claim, "status": "holding"}}
        if path.endswith("/work-status"):
            return dict(WORK, job_id="job_sealed", job_state=self.job["state"], can_start_bounty=self.active)
        if path.endswith("/bundle"): return self.bundle
        if path.endswith("/credentials"):
            return {"error": "already submitted", "status": 403} if self.mint_refused else {"credential": "secret-operation"}
        if path.endswith("/submit"): return {**self.job, "state": "submitted"}
        return self.job

    def test_review_only_holder_gets_bundle(self):
        view = server.review_job("job_sealed")
        self.assertEqual(view["bundle"], self.bundle)
        self.assertEqual(len([c for c in self.calls if c[1].endswith("/bundle")]), 1)
        self.active = False; self.calls.clear()
        self.assertNotIn("bundle", server.review_job("job_sealed"))
        self.assertFalse(any(c[1].endswith("/bundle") for c in self.calls))
        self.assertNotIn("secret-", json.dumps(view))
        self.assertNotIn("repo_url", view)

    def test_patch_submission_and_stable_retry_key(self):
        first = server.submit_work("job_sealed", patch=DIFF, tokens_used=123)
        call = next(c for c in self.calls if c[1].endswith("/submit"))
        self.assertEqual(call[2]["json"], {"patch": DIFF, "reported_tokens": 123})
        self.assertEqual(call[2]["headers"]["Authorization"], "Bearer secret-operation")
        self.assertEqual(first["state"], "submitted")
        self.assertNotIn("pr_url", first)
        self.assertNotIn("secret-", json.dumps(first))
        self.mint_refused = True
        self.assertEqual(server.submit_work("job_sealed", patch=DIFF, tokens_used=123), first)
        last = self.calls[-1]
        self.assertEqual(last[2]["headers"]["Idempotency-Key"], call[2]["headers"]["Idempotency-Key"])
        self.assertEqual(last[2]["json"]["supplier_token"], "secret-bootstrap")

    def test_review_keeps_common_envelope_before_and_after_claim(self):
        for state, active in (("open", False), ("claimed", True)):
            with self.subTest(state=state):
                self.job["state"], self.active = state, active
                view = server.review_job("job_sealed")
                for field in ("summary", "next_action"):
                    self.assertIsInstance(view.get(field), str)
                    self.assertTrue(view[field])

    def test_new_approval_gets_new_patch_key(self):
        server.submit_work("job_sealed", patch=DIFF)
        first = self.calls[-1][2]["headers"]["Idempotency-Key"]
        self.claim = 2
        server.submit_work("job_sealed", patch=DIFF)
        self.assertNotEqual(self.calls[-1][2]["headers"]["Idempotency-Key"], first)

    def test_missing_claim_identity_refuses_submission(self):
        self.claim = None
        self.assertIn("error", server.submit_work("job_sealed", patch=DIFF))
        self.assertFalse(any(c[1].endswith("/submit") for c in self.calls))

    def test_patch_excludes_pr_check_only_and_messages(self):
        for kwargs in ({"pr_url": "https://example.com/pull/1"}, {"check_only": True}, {"message": "fix"}, {"evidence_urls": []}, {"blocker_code": "ambiguous"}):
            self.assertIn("error", server.submit_work("job_sealed", patch=DIFF, **kwargs))
        self.assertFalse(self.calls)

    def test_coarse_status_does_not_expose_pr(self):
        # Defense at the connector too: no repository fields escape even if a
        # misconfigured backend adds private fields to a sealed job response.
        self.job.update(repo_url="https://github.com/private/repo", pr_url="https://github.com/private/repo/pull/3", owner_id="private-owner")
        result = server.job_status("job_sealed")
        self.assertNotIn("private", json.dumps(result))

    def test_find_work_card_omits_repository_owner_and_pr(self):
        card = dict(JOB, state="open", repo_url="https://github.com/private/repo",
                    pr_url="https://github.com/private/repo/pull/3", owner_id="private-owner")
        with patch.object(server, "_call", return_value=[card]):
            result = server.find_work()
        self.assertEqual(result["recommendation"]["job_id"], "job_sealed")
        self.assertNotIn("private", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
