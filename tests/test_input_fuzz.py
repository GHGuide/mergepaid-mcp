"""Seeded MCP argument fuzzing using only the standard library and fake API replies."""
import json
import os
import random
import unittest
from unittest.mock import patch

from mergepaid_mcp import server
from test_racer import JOB, run


LONG = os.environ.get("MERGEPAID_H6_LONG") == "1"
PRIVATE = "h6-mcp-private-marker-do-not-disclose"


def value(rng, depth=0):
    if depth < 3:
        choice = rng.randrange(5)
        if choice == 0:
            return [value(rng, depth + 1) for _ in range(rng.randrange(5))]
        if choice == 1:
            return {rng.choice(["row", "url", "code", "token"]): value(rng, depth + 1)
                    for _ in range(rng.randrange(5))}
    return rng.choice([None, True, False, -1, 0, 1, 1.5, 10**40, "", "job_fit", "bad id!",
                       "\x00\n", "\ud800", "é汉字🚲", "../a?token=x", "x" * 4001])


class InputFuzzTests(unittest.TestCase):
    def check(self, result, calls):
        self.assertIsInstance(result, dict)
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertTrue(result.get("summary") or result.get("error"))
        if "error" in result:
            self.assertIsInstance(result.get("next_action"), str)
            self.assertTrue(result["next_action"])
            if "status" in result:
                self.assertGreaterEqual(result["status"], 400)
                self.assertLess(result["status"], 500)
        self.assertFalse(any(path.endswith(("/claim/take", "/claim/approve")) for _, path, _ in calls))

    def test_seeded_arguments_to_all_eight_supplier_tools(self):
        routes = {"/api/discovery/jobs": [], "/api/suppliers/me": {"id": "sup_fixture", "pending_usd": 0,
                  "paid_usd": 0, "balance_usd": 0, "api_token": PRIVATE},
                  "/credentials": {"error": "Refused", "status": 403, "detail": "No current human claim"},
                  "/work-status": {"error": "Refused", "status": 403, "detail": "No current human claim"}}
        fields = {
            server.find_work: ["max_total_tokens", "minimum_payout_usd", "languages"],
            server.review_job: ["job_id"],
            server.claim_job: ["job_id"],
            server.submit_work: ["job_id", "pr_url", "tokens_used", "message", "check_only", "evidence_urls",
                                 "blocker_code", "blocker_note", "evidence", "patch"],
            server.job_status: ["job_id", "wait_seconds", "reply"],
            server.my_earnings: [],
            server.read_messages: ["since"],
            server.send_message: ["conversation_id", "text", "on_behalf_of_owner"],
        }
        for seed in range(48 if LONG else 6):
            rng = random.Random(seed)
            for tool, names in fields.items():
                for case in range(256 if LONG else 48):
                    with self.subTest(seed=seed, tool=tool.__name__, case=case):
                        args = {"job_id": "job_fit"} if "job_id" in names else {}
                        if tool is server.send_message:
                            args.update(conversation_id="direct_1", text="Hello")
                        if names:
                            args[rng.choice(names)] = value(rng)
                        # Refused status replies do not poll. The sleep mock is a
                        # backstop against a future pending fixture lengthening the run.
                        with patch.object(server.time, "sleep", side_effect=AssertionError("Unexpected poll")):
                            result, calls = run(tool, routes=routes, job=JOB, **args)
                        self.check(result, calls)

    def test_argument_refusal_has_a_reason_code(self):
        # H1 owns stable refusal codes; retain a precise regression until integrated.
        result, _ = run(server.review_job, "bad id!")
        self.assertIsInstance(result.get("code"), str)
        self.assertTrue(result["code"])
