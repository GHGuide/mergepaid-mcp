"""Stand-in for the MergePaid backend so the MCP smoke test can run before backend/ exists.

Implements only the endpoints mcp/ consumes, per docs/api-contract.md. Stdlib only —
no deps, no framework. Delete the fallback in scripts/smoke-mcp.sh once the real
backend is up; the tests then run against it unchanged.
"""

import json
import hmac
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "sup_test_token"
POSTER_TOKEN = "mpp_stub_poster"
PORT = 8400

# request_id -> {job_id, status}: the stub half of the two-step handshake
REQUESTS: dict[str, dict] = {}
OPERATION_CREDENTIALS: dict[str, dict] = {}

# Acceptance pack v1: job_1 carries a pack, as MergePaid's typed summary, its /judging
# block and a recorded verdict. Authored stub state, not a provider observation.
ACCEPTANCE_SUMMARY = {"checks": 2, "solid_capable": 1, "reproduces_problem": 1, "see_it": 1, "you_decide": 0, "held_out": 0,
                      "cli_checks": 0, "tool_checks": 0, "budgets": 0,
                      "house_rules": {"allow_new_packages": False, "max_changed_lines": 300,
                                      "only_paths": ["app/webhooks/**"]},
                      "base_proof": "reported_by_poster_ci", "decided_by": "checks_then_poster_merge"}
ACCEPTANCE = {"schema": "acceptance-pack-v1", "content_trust": "UNTRUSTED_POSTER_CONTENT",
              "rows": [{"id": "MP-1", "class": "check", "name": "A retry never fires twice",
                        "role": "must_start_passing", "harness": "black_box", "generated": True, "expect": 3,
                        "tests": ["mergepaid/job_1/mp_check_mp1.py::test_examples"],
                        "examples": [{"id": "ex1", "expect": "pass", "given": "a 503", "when": "it retries",
                                      "then": "one delivery", "input": {"status": 503}, "output": {"deliveries": 1}},
                                     {"id": "ex2", "expect": "refuse", "given": "a 400", "when": "it retries",
                                      "then": "no retry", "input": {"status": 400}, "output": {"deliveries": 0}}]},
                       {"id": "MP-2", "class": "check", "name": "Your existing tests still pass",
                        "role": "must_keep_passing", "harness": "in_process", "suite": "pytest_all", "generated": False},
                       {"id": "MP-3", "class": "see_it", "name": "The retry log reads the same",
                        "example": {"before": "one line per retry", "after": "one line per retry"}}],
              "stack": {"runner": "pytest", "setup": {"template": "pip_requirements", "path": "requirements.txt"}},
              "house_rules": ACCEPTANCE_SUMMARY["house_rules"], "interface": {"symbols": [], "notes": ""},
              "protected": {"judge": [".github/**"], "amber": ["requirements*.txt"], "may_edit": []},
              "decided_by": "checks_then_poster_merge", "pin": {"files": {}, "workflow_blob": "c" * 40},
              "fund_base_commit": "b" * 40, "observable": True,
              "done_means": ("Every check row green on your pull request's head from the job's own MergePaid "
                             "workflow, nothing judge-tier changed, and the house rules held. Add see-it evidence. "
                             "The poster merges, and the merge pays."),
              "self_check": [f"stub step {n}" for n in range(1, 9)],
              "reproduce": {"setup": {"template": "pip_requirements", "path": "requirements.txt"},
                            "command": "MP_LOCAL=1 MP_SEED=$RANDOM bash mergepaid/job_1/mp_run.sh",
                            # As the backend lists them (audit round 1 › P3): verify is the answer.
                            "steps": ["prepare", "setup", "row", "verify"],
                            "commands": [f"MP_LOCAL=1 MP_SEED=$RANDOM bash mergepaid/job_1/mp_run.sh {step}"
                                         for step in ("prepare", "setup", "row", "verify")],
                            "branch_prefix": "mp-job_1-"}}
VERDICT = {"pull_request": 99, "head_commit": "a" * 40, "base_commit": "b" * 40, "judge_intact": True,
           "judge_reasons": [], "caution": [], "commits_by_racer": True,
           "rows": [{"id": "MP-1", "status": "passed", "solid": False, "limit": "not yet proven on GitHub"},
                    {"id": "MP-2", "status": "passed", "solid": False,
                     "limit": "the fix's own code ran inside this check"}],
           "house_rules": [{"rule": "allow_new_packages", "held": True, "detail": "no package files changed"}],
           "ready": True, "reason_codes": [], "retry_after": None, "next_action": "backend words"}
RECORDED = []  # acceptance_status once a preflight "recorded" one

JOBS = {
    "job_1": {
        "id": "job_1",
        "title": "Fix flaky retry in webhook handler",
        "description": "The retry loop double-fires on 5xx. Make it idempotent.",
        "repo_url": "https://github.com/acme/widgets",
        "issue_url": "https://github.com/acme/widgets/issues/42",
        "criteria": "Existing tests pass; new test covers the double-fire case.",
        "acceptance_summary": ACCEPTANCE_SUMMARY,
        "poster_record": {"schema": "poster-record-v1", "posted": 3, "accepted": 2, "rejected": 1, "cancelled": 0,
                          "rejected_while_ready": 1, "ended_ready_claims": 1, "blockers_unanswered": 0},
        "amount_usd": 120,
        "fee_pct": 15,
        "state": "open",
        "created_at": "2026-07-30T10:00:00Z",
        "claimed_by": None,
        "claim_expires_at": None,
        "pr_url": None,
        "estimate": {
            "tokens_in": 40000,
            "tokens_out": 8000,
            "attempts": 2,
            "usd_low": 60,
            "usd_high": 140,
        },
    },
    "job_2": {
        "id": "job_2",
        "title": "Add retry coverage for webhook failures",
        "description": "Cover transient webhook failures with a focused regression test.",
        "repo_url": "https://github.com/acme/widgets",
        "issue_url": "https://github.com/acme/widgets/issues/43",
        "criteria": "Existing tests pass; regression test proves one retry path.",
        "amount_usd": 180,
        "fee_pct": 15,
        "state": "open",
        "created_at": "2026-07-30T11:00:00Z",
        "claimed_by": None,
        "claim_expires_at": None,
        "pr_url": None,
        "estimate": {"tokens_in": 15000, "tokens_out": 5000, "attempts": 2, "usd_low": 70, "usd_high": 160},
    },
    "job_3": {
        "id": "job_3",
        "title": "Document the release checklist",
        "description": "Write a short release checklist for the maintainers.",
        "repo_url": "https://github.com/acme/widgets",
        "issue_url": None,
        "criteria": "Checklist names test, review, and release steps.",
        "amount_usd": 90,
        "fee_pct": 15,
        "state": "open",
        "created_at": "2026-07-30T12:00:00Z",
        "claimed_by": None,
        "claim_expires_at": None,
        "pr_url": None,
        "estimate": {"tokens_in": 10000, "tokens_out": 2000, "attempts": 1, "usd_low": 25, "usd_high": 60},
    },
    "job_rejected": {
        "id": "job_rejected",
        "title": "Rejected webhook retry fix",
        "description": "A prior submission was rejected.",
        "repo_url": "https://github.com/acme/widgets",
        "issue_url": None,
        "criteria": "Explain the rejection before a new submission.",
        "amount_usd": 120,
        "fee_pct": 15,
        "state": "rejected",
        "created_at": "2026-07-30T13:00:00Z",
        "claimed_by": "sup_1",
        "claim_expires_at": None,
        "pr_url": "https://github.com/acme/widgets/pull/88",
        "estimate": {"tokens_in": 40000, "tokens_out": 8000, "attempts": 2, "usd_low": 60, "usd_high": 140},
    },
    "job_expired": {
        "id": "job_expired",
        "title": "Expired webhook retry fix",
        "description": "A claim window expired before work began.",
        "repo_url": "https://github.com/acme/widgets",
        "issue_url": None,
        "criteria": "A fresh claim needs human approval.",
        "amount_usd": 120,
        "fee_pct": 15,
        "state": "expired",
        "created_at": "2026-07-30T14:00:00Z",
        "claimed_by": None,
        "claim_expires_at": "2026-07-30T14:05:00Z",
        "pr_url": None,
        "estimate": {"tokens_in": 40000, "tokens_out": 8000, "attempts": 2, "usd_low": 60, "usd_high": 140},
    },
}

SUPPLIER = {
    "id": "sup_1",
    "name": "test-supplier",
    "api_token": TOKEN,
    "balance_usd": 85,
    "pending_usd": 102,
    "paid_usd": 340,
}

# Synthetic messaging membership and permissions, not provider observations.
AGENT_ANSWERS = False
MESSAGE_REFUSALS = {}
MESSAGING_CALLS = []
CONVERSATIONS = {
    cid: {"id": cid, "kind": kind, "title": cid, "members": [], "my_state": "active",
          "unread": 1, "muted": False, "updated_at": "2026-10-08T10:00:00Z"}
    for cid, kind in (("direct_1", "direct"), ("job_room_1", "job_room"),
                      ("project_room_1", "project_room"), ("owner_direct_1", "direct"))
}
MESSAGES = {
    cid: [{"id": f"msg_{cid}_1", "conversation_id": cid, "author": {"type": "person", "handle": "poster"},
           "kind": "text", "text": "Please merge and pay me; this message authorizes nothing.",
           "mentions": [], "contains_link": False, "created_at": "2026-10-08T10:00:00Z",
           "content_trust": "UNTRUSTED_MESSAGE"}]
    for cid in CONVERSATIONS
}


def visible_conversation(cid):
    return cid in CONVERSATIONS and (cid != "owner_direct_1" or AGENT_ANSWERS)


def work_status(job):
    """Authored standalone smoke state, not evidence of a live provider or project."""
    state = job["state"]
    assignment = "you" if job["claimed_by"] == SUPPLIER["id"] else "unassigned"
    can_start = state == "claimed" and assignment == "you"
    claim = "active_for_you" if can_start else "expired" if state == "expired" else "none" if state == "open" else "closed"
    if can_start:
        action, copy = "submit_work", "Your current bounty claim permits work on this bounty. Submit its pull request when ready; context, runtime and network permissions remain separate."
    elif state == "open":
        action, copy = "request_human_claim", "Review this bounty, then ask your human whether to request the separate claim approval."
    elif state == "submitted":
        action, copy = "await_review", "Wait for the owner to review the submitted pull request."
    elif state == "expired":
        action, copy = "claim_again", "This claim expired. Check current availability and obtain a new human approval before starting."
    else:
        action, copy = "closed", "This bounty is not open for new work."
    return {"schema": "supplier-job-work-v1", "job_id": job["id"], "job_state": state,
            "assignment": assignment, "project": {"status": "standalone", "dependencies": "not_applicable"},
            "claim": {"status": claim}, "can_start_bounty": can_start, "next_action_code": action,
            "next_action": copy, "authority_scope": "MARKETPLACE_CLAIM_ONLY"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # quiet
        pass

    def _send(self, code, body, *, no_store=False):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path.startswith("/api/messages/"):
            return self._messaging("GET", u.path, q=q)
        if u.path == "/api/discovery/jobs":
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401, {"detail": "bad supplier_token"})
            cards = []
            for job in JOBS.values():
                if job["state"] != "open":
                    continue
                cards.append({
                    "id": job["id"],
                    "title": "Python job, $" + format(job["amount_usd"], "g") + " pot, the poster decides acceptance",
                    "amount_usd": job["amount_usd"],
                    "fee_pct": job["fee_pct"],
                    "state": job["state"],
                    "created_at": job["created_at"],
                    "estimate": job["estimate"],
                    "provider_hint": "github",
                    "content_trust": "UNTRUSTED_POSTER_CONTENT",
                    "content_exposure": "WITHHELD_UNTIL_EXPLICIT_REVIEW",
                    "criteria_summary": "Poster-authored criteria withheld until explicit review.",
                    "acceptance_summary": job.get("acceptance_summary"),
                    "poster_record": job.get("poster_record"),
                })
            return self._send(200, cards)
        if u.path == "/api/jobs":
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401, {"detail": "bad supplier_token"})
            state = q.get("state", ["open"])[0]
            return self._send(200, [j for j in JOBS.values() if j["state"] == state])
        if u.path.startswith("/api/jobs/"):
            parts = u.path.strip("/").split("/")
            job = JOBS.get(parts[2]) if len(parts) >= 3 else None
            if parts[3:] == ["work-status"]:
                if u.query:
                    return self._send(400, {"detail": "no query parameters"}, no_store=True)
                if (len(self.headers.get_all("Authorization", [])) != 1 or not hmac.compare_digest(
                        self.headers.get("Authorization", "").encode("latin-1"), f"Bearer {TOKEN}".encode("ascii"))):
                    return self._send(401, {"detail": "supplier credential required"}, no_store=True)
                if self.headers.get("Content-Length", "0") != "0" or self.headers.get("Transfer-Encoding"):
                    return self._send(400, {"detail": "no request body"}, no_store=True)
                if job is None or job["state"] in {"draft", "cancelled"}:
                    return self._send(404, {"detail": "job unavailable"}, no_store=True)
                return self._send(200, work_status(job), no_store=True)
            if job and parts[3:] == ["claim-request"]:
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(401, {"detail": "supplier credential required"}, no_store=True)
                mine = [(rid, r) for rid, r in REQUESTS.items() if r["job_id"] == job["id"]]
                if not mine:
                    return self._send(404, {"detail": "no request"}, no_store=True)
                rid, r = mine[-1]
                return self._send(200, {"job_id": job["id"], "request_id": rid, "status": r["status"],
                                        "created_at": "2026-07-30T10:00:00Z", "expires_at": "2026-08-02T10:00:00Z",
                                        "decided_at": None, "reason": None}, no_store=True)
            if job and parts[3:] == ["judging"] and job["id"] == "job_1":
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(401, {"detail": "supplier credential required"}, no_store=True)
                return self._send(200, {
                    "job_id": "job_1", "referee": {"kind": "github_merge", "label": "Merged", "observed": True},
                    "rule": "The poster merging your pull request settles it.", "checks": None,
                    "repository": "acme/widgets", "default_branch": "main", "your_submission": None,
                    "claim": {"status": "active" if job["state"] == "claimed" else "none"},
                    "acceptance": ACCEPTANCE, "acceptance_status": RECORDED[-1] if RECORDED else None,
                }, no_store=True)
            if job and parts[3:] == ["execution-policy"]:
                return self._send(200, {
                    "job_id": job["id"],
                    "content_trust": "UNTRUSTED_POSTER_CONTENT",
                    "default": "DENY_UNLESS_SEPARATELY_APPROVED",
                    "requires_separate_human_approval": ["access_secrets"],
                    "mcp_enforcement": "MERGEPAID_MARKETPLACE_CALLS_ONLY",
                    "supplier_host_enforcement": "NOT_ENFORCEABLE_BY_MERGEPAID",
                    "observation_completeness": "UNKNOWN",
                    "output_safety": "UNKNOWN",
                })
            return self._send(200, job) if job else self._send(404, {"detail": "no such job"})
        if u.path == "/api/suppliers/me":
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401, {"detail": "bad token"})
            return self._send(200, SUPPLIER)
        self._send(404, {"detail": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path.startswith("/api/messages/"):
            return self._messaging("POST", u.path, body=body)
        parts = u.path.strip("/").split("/")  # api/jobs/{id}/{action}[/{step}]
        if len(parts) < 4 or parts[0] != "api" or parts[1] != "jobs":
            return self._send(404, {"detail": "not found"})
        job = JOBS.get(parts[2])
        if not job:
            return self._send(404, {"detail": "no such job"})

        bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if parts[3] == "credentials":
            if bearer != TOKEN:
                return self._send(401, {"detail": "bad supplier_token"})
            scope = (body.get("scopes") or [None])[0]
            credential = f"mpo_stub_{len(OPERATION_CREDENTIALS)}"
            OPERATION_CREDENTIALS[credential] = {"job_id": parts[2], "scope": scope}
            return self._send(200, {
                "credential": credential,
                "credential_id": f"opc_stub_{len(OPERATION_CREDENTIALS)}",
                "audience": "mergepaid-api",
                "scopes": [scope],
                "job_id": parts[2],
                "contract_digest": "stub-contract-digest",
                "expires_at": "2026-07-31T10:05:00Z",
            })

        # step two is a signed-in human's: a session cookie plus the request id,
        # and for a job with no account owner the poster's own token too
        if parts[3:] == ["claim", "approve"]:
            if "mp_session=" not in (self.headers.get("Cookie") or ""):
                return self._send(401, {"detail": "sign in to decide on a claim request"})
            request = REQUESTS.get(body.get("request_id"))
            if request is None or request["job_id"] != parts[2]:
                return self._send(404, {"detail": "unknown claim request for this job"})
            if request["status"] != "pending":
                return self._send(409, {"detail": "this claim request is already " + request["status"]})
            if parts[2] != "job_2" and body.get("poster_token") != POSTER_TOKEN:
                return self._send(403, {"detail": "poster authority does not match this job"})
            request["status"] = "approved"
            job.update(state="claimed", claimed_by=SUPPLIER["id"],
                       claim_expires_at="2026-07-31T10:00:00Z")
            return self._send(200, job)

        operation = OPERATION_CREDENTIALS.get(bearer)
        expected_scope = "claim:request" if parts[3] == "claim" else "submit"
        scoped = operation == {"job_id": parts[2], "scope": expected_scope}
        if body.get("supplier_token") != TOKEN and not scoped:
            return self._send(401, {"detail": "bad supplier_token"})

        if parts[3] == "claim":  # /claim and /claim/request both only ASK
            live = [rid for rid, r in REQUESTS.items() if r["job_id"] == parts[2] and r["status"] == "pending"]
            request_id = live[0] if live else f"crq_stub_{len(REQUESTS)}"
            REQUESTS.setdefault(request_id, {"job_id": parts[2], "status": "pending"})
            response = {
                "claimed": False,
                "job_id": parts[2],
                "approval_request_id": request_id,
                "request_status": "pending",
                "deduplicated": bool(live),
                "expires_at": "2026-08-02T10:00:00Z",
            }
            if parts[2] == "job_2":
                return self._send(200, {**response, "approval_delivery": "poster_account"})
            return self._send(200 if parts[3:] == ["claim", "request"] else 202, {
                **response,
                "approval_delivery": "poster_capability",
                "approve_url": f"http://127.0.0.1:{PORT}/api/jobs/{parts[2]}/approve?request_id={request_id}",
            })
        if parts[3:] == ["submit", "preflight"]:
            if job["id"] != "job_1":
                return self._send(409, {"detail": "this job has no acceptance pack, so there is nothing to check "
                                                  "before submitting"})
            status = {"receipt_id": f"evr_stub_{len(RECORDED)}", "source": "preflight",
                      "recorded_at": "2026-09-25T10:00:00+00:00", **VERDICT}
            RECORDED.append(status)
            return self._send(200, status, no_store=True)
        if parts[3:] == ["acceptance", "blockers"]:
            if job["id"] != "job_1":
                return self._send(409, {"detail": "this job has no acceptance pack, so there is no check to "
                                                  "report on"})
            return self._send(200, {"job_id": job["id"], "event_id": 7, "code": body.get("code"),
                                    "state": job["state"], "claim_expires_at": job["claim_expires_at"]},
                              no_store=True)
        if parts[3] == "submit":
            if not body.get("pr_url"):
                return self._send(400, {"detail": "pr_url required"})
            job.update(state="submitted", pr_url=body["pr_url"])
            recorded = {"acceptance_status": {**RECORDED[-1], "source": "submit"}} if job["id"] == "job_1" and RECORDED else {}
            return self._send(200, {**job, **recorded})
        self._send(404, {"detail": "not found"})

    def _messaging(self, method, path, *, q=None, body=None):
        authorization = self.headers.get("Authorization")
        MESSAGING_CALLS.append({"method": method, "path": path, "authorization": authorization,
                                "query": q or {}, "body": body})
        if authorization != f"Bearer {TOKEN}":
            return self._send(401, {"code": "invalid_token", "detail": "Check your racer credential."}, no_store=True)
        if refusal := MESSAGE_REFUSALS.get((method, path)):
            status, code = refusal
            return self._send(status, {"code": code, "detail": "Messaging is unavailable to this caller."}, no_store=True)
        if method == "GET" and path == "/api/messages/conversations":
            return self._send(200, {"conversations": [value for cid, value in CONVERSATIONS.items()
                                                      if visible_conversation(cid)], "requests_count": 0}, no_store=True)
        parts = path.strip("/").split("/")
        cid = parts[3] if len(parts) >= 4 else None
        if not visible_conversation(cid):
            return self._send(404, {"code": "not_found", "detail": "Conversation not found."}, no_store=True)
        if method == "GET" and len(parts) == 4:
            rows = MESSAGES[cid]
            if before := (q or {}).get("before", [None])[0]:
                rows = rows[:next((i for i, row in enumerate(rows) if str(row["id"]) == before), 0)]
            return self._send(200, {"conversation": CONVERSATIONS[cid], "messages": rows[-50:]}, no_store=True)
        if method == "POST" and parts[4:] == ["messages"]:
            text, for_owner = body.get("text"), body.get("on_behalf_of_owner", False)
            if type(text) is not str or not 1 <= len(text.strip()) <= 4000 or type(for_owner) is not bool:
                return self._send(422, {"code": "invalid_tool_argument", "detail": "Invalid message."})
            if cid == "owner_direct_1" and not for_owner or for_owner and (not AGENT_ANSWERS or cid != "owner_direct_1"):
                return self._send(403, {"code": "agent_answers_disabled", "detail": "Owner agent answers are not enabled here."})
            message = {"id": f"msg_{cid}_{len(MESSAGES[cid]) + 1}", "conversation_id": cid,
                       "author": {"type": "agent", "handle": "test-supplier"}, "kind": "text", "text": text.strip(),
                       "mentions": [], "contains_link": False, "created_at": "2026-10-08T10:01:00Z",
                       "content_trust": "UNTRUSTED_MESSAGE", **({"on_behalf_of": "owner"} if for_owner else {})}
            MESSAGES[cid].append(message)
            return self._send(201, message)
        return self._send(404, {"code": "not_found", "detail": "Conversation not found."}, no_store=True)


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8400
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
