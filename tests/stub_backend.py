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

# claim_token -> {job_id, used}: the stub half of the two-step handshake
CLAIM_TOKENS: dict[str, dict] = {}
OPERATION_CREDENTIALS: dict[str, dict] = {}

JOBS = {
    "job_1": {
        "id": "job_1",
        "title": "Fix flaky retry in webhook handler",
        "description": "The retry loop double-fires on 5xx. Make it idempotent.",
        "repo_url": "https://github.com/acme/widgets",
        "issue_url": "https://github.com/acme/widgets/issues/42",
        "criteria": "Existing tests pass; new test covers the double-fire case.",
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
        if u.path == "/api/discovery/jobs":
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401, {"detail": "bad supplier_token"})
            cards = []
            for job in JOBS.values():
                if job["state"] != "open":
                    continue
                cards.append({
                    "id": job["id"],
                    "title": "Unreviewed funded job",
                    "amount_usd": job["amount_usd"],
                    "fee_pct": job["fee_pct"],
                    "state": job["state"],
                    "created_at": job["created_at"],
                    "estimate": job["estimate"],
                    "provider_hint": "github",
                    "content_trust": "UNTRUSTED_POSTER_CONTENT",
                    "content_exposure": "WITHHELD_UNTIL_EXPLICIT_REVIEW",
                    "criteria_summary": "Poster-authored criteria withheld until explicit review.",
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

        # step two is the human's; it carries a claim_token, never a supplier_token
        if parts[3:] == ["claim", "approve"]:
            token = body.get("claim_token")
            if token not in CLAIM_TOKENS or CLAIM_TOKENS[token]["job_id"] != parts[2]:
                return self._send(404, {"detail": "unknown claim token for this job"})
            if CLAIM_TOKENS[token]["used"]:
                return self._send(409, {"detail": "this approval link has already been used"})
            if body.get("poster_token") != POSTER_TOKEN:
                return self._send(403, {"detail": "poster_token does not match this job"})
            CLAIM_TOKENS[token]["used"] = True
            job.update(state="claimed", claimed_by=SUPPLIER["id"],
                       claim_expires_at="2026-07-31T10:00:00Z")
            return self._send(200, job)

        operation = OPERATION_CREDENTIALS.get(bearer)
        expected_scope = "claim:request" if parts[3] == "claim" else "submit"
        scoped = operation == {"job_id": parts[2], "scope": expected_scope}
        if body.get("supplier_token") != TOKEN and not scoped:
            return self._send(401, {"detail": "bad supplier_token"})

        if parts[3] == "claim":  # /claim and /claim/request both only ASK
            token = f"mpc_stub_{len(CLAIM_TOKENS)}"
            CLAIM_TOKENS[token] = {"job_id": parts[2], "used": False}
            if parts[2] == "job_2":
                return self._send(200, {
                    "claimed": False,
                    "job_id": parts[2],
                    "approval_delivery": "poster_account",
                    "approval_request_id": "crq_stub_owned",
                    "expires_at": "2026-07-31T10:05:00Z",
                })
            return self._send(200 if parts[3:] == ["claim", "request"] else 202, {
                "claimed": False,
                "job_id": parts[2],
                "approval_delivery": "poster_capability",
                "claim_token": token,
                "approve_url": f"http://127.0.0.1:{PORT}/api/jobs/{parts[2]}/approve?claim_token={token}",
                "expires_at": "2026-07-31T10:05:00Z",
            })
        if parts[3] == "submit":
            if not body.get("pr_url"):
                return self._send(400, {"detail": "pr_url required"})
            job.update(state="submitted", pr_url=body["pr_url"])
            return self._send(200, job)
        self._send(404, {"detail": "not found"})


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8400
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
