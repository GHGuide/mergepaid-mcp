"""Exercise the connector work functions over the real seeded HTTP app, no ports."""
from pathlib import Path
import os
import sys
import json
import subprocess
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mergepaid_mcp import server


class LocalSeedTools(unittest.TestCase):
    def test_work_tools_use_real_seed_and_cannot_approve_a_lane(self):
        process = subprocess.Popen([str(ROOT / ".venv/bin/python"), str(ROOT / "mcp/tests/local_seed_backend.py")],
                                   cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True,
                                   env={"PATH": os.environ.get("PATH", os.defpath), "PYTHONDONTWRITEBYTECODE": "1"})
        try:
            world = json.loads(process.stdout.readline())
            real_client = httpx.Client

            def dispatch(request):
                process.stdin.write(json.dumps({"method": request.method, "path": request.url.raw_path.decode(),
                                                "body": request.content.decode(), "headers": dict(request.headers)}) + "\n")
                process.stdin.flush()
                response = json.loads(process.stdout.readline())
                return httpx.Response(response["status"], content=response["body"].encode(), headers=response["headers"])

            def factory(**kwargs):
                return real_client(transport=httpx.MockTransport(dispatch), **kwargs)

            with patch.object(server, "TOKEN", world["demo_token"]), patch.object(server.httpx, "Client", side_effect=factory):
                found = server.find_work()
                card = found["recommendation"]
                self.assertTrue(card["launch_pool"])
                self.assertTrue(card["synthetic"])
                self.assertEqual(card["net_payout_usd"], card["gross_payout_usd"] * .85)
                self.assertIn("Launch Pool", found["summary"])
                jid = card["job_id"]
                reviewed = server.review_job(jid)
                self.assertTrue(reviewed["launch_pool"])
                self.assertIn("Launch Pool", reviewed["summary"])
                before = reviewed["lanes"]["open"]
                requested = server.claim_job(jid)
                self.assertFalse(requested["claimed"])
                self.assertEqual(requested["request_status"], "pending")
                self.assertEqual(server.review_job(jid)["lanes"]["open"], before)
                self.assertFalse(server.job_status(jid)["work_status"]["can_start_bounty"])
                held_id = world["racer_jobs"]["racing"]
                held = server.job_status(held_id)
                self.assertTrue(held["work_status"]["can_start_bounty"])
                review = server.job_status(world["racer_jobs"]["review"])
                self.assertEqual(review["state"], "submitted")
                earned = server.my_earnings()
                supplier = server._call("GET", "/api/suppliers/me", headers=server._auth())
                self.assertEqual(earned["paid_usd"], supplier["paid_usd"])
                refused = server.submit_work(jid, "https://github.com/mergepaid/agent-ledger/pull/9999")
                self.assertFalse(refused.get("work_status", {}).get("can_start_bounty", False))
                self.assertNotEqual(server.job_status(jid)["state"], "paid")
                held_repo = server.review_job(held_id)["repo_url"]
                submitted = server.submit_work(held_id, held_repo + "/pull/9998")
                self.assertEqual(submitted["state"], "submitted")
                self.assertEqual(server.job_status(held_id)["state"], "submitted")
                self.assertEqual(server.my_earnings()["paid_usd"], earned["paid_usd"])
        finally:
            process.stdin.close()
            process.wait(timeout=30)
            stderr = process.stderr.read()
            process.stdout.close()
            process.stderr.close()
            self.assertEqual(process.returncode, 0, stderr)
