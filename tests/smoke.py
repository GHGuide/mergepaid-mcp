"""Exercise the frozen intent-first MergePaid MCP contract over stdio."""

import asyncio
import json
import os
import sys

import httpx
from mcp import Client, StdioServerParameters, stdio_client

API = os.environ["MERGEPAID_API"]
TOKEN = os.environ["MERGEPAID_TOKEN"]
IS_STUB = os.environ.get("MERGEPAID_SMOKE_BACKEND") == "stub"
POSTER_TOKEN = "mpp_stub_poster"

TOOL_SPECS = {
    "find_work": ("Find paid work", {"max_total_tokens", "minimum_payout_usd"}),
    "review_job": ("Review job contract", {"job_id"}),
    "claim_job": ("Request human claim approval", {"job_id"}),
    "submit_work": ("Submit work", {"job_id", "pr_url", "execution_offer_id", "idempotency_key"}),
    "job_status": ("Check job status", {"job_id"}),
    "my_earnings": ("Check my earnings", set()),
}


def payload(result) -> dict:
    """Unwrap a CallToolResult into the returned JSON object."""
    assert result.content, "tool returned no content"
    return json.loads(result.content[0].text)


def assert_envelope(result: dict, *fields: str) -> None:
    for field in (*fields, "summary", "next_action"):
        assert field in result, f"missing {field}: {result}"
    assert isinstance(result["summary"], str) and result["summary"], result
    assert isinstance(result["next_action"], str) and result["next_action"], result


async def main() -> None:
    global POSTER_TOKEN
    if not IS_STUB:
        # Create a dedicated high-value API job so the smoke owns the separate
        # poster authority for the recommendation it will exercise.
        with httpx.Client(
            base_url=API,
            timeout=30,
            headers={"Origin": "http://localhost:8401"},
        ) as poster:
            created = poster.post(
                "/api/jobs",
                json={
                    "title": "MCP smoke: bounded claim authority",
                    "description": "Verify the six supplier tools against a live backend.",
                    "repo_url": "https://github.com/acme/mcp-smoke",
                    "criteria": "The focused smoke passes.",
                    "amount_usd": 10000,
                },
            )
            assert created.status_code == 200, created.text
            job = created.json()
            POSTER_TOKEN = job["poster_token"]
            funded = poster.post(
                f"/api/jobs/{job['id']}/fund",
                json={"poster_token": POSTER_TOKEN},
            )
            assert funded.status_code == 200, funded.text

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mergepaid_mcp.server"],
        env={**os.environ, "MERGEPAID_API": API, "MERGEPAID_TOKEN": TOKEN},
    )
    async with Client(stdio_client(params), raise_exceptions=True) as s:
        instructions = " ".join((s.instructions or "").lower().split())
        for phrase in (
            "never narrate tool names",
            "estimated total usage",
            "net payout",
            "why it fits",
            "one next action",
            "do not enumerate them unless the human asks",
            "local records or potential entitlements",
            "do not verify stripe",
        ):
            assert phrase in instructions, f"missing client presentation rule {phrase!r}: {instructions}"
        print("ok  client instructions present one human decision and hide MCP plumbing")

        tools = (await s.list_tools()).tools
        by_name = {tool.name: tool for tool in tools}
        assert set(by_name) == set(TOOL_SPECS), f"expected frozen six tools, got {sorted(by_name)}"
        for name, (title, properties) in TOOL_SPECS.items():
            tool = by_name[name]
            assert tool.title == title, f"{name} title: {tool.title!r}"
            description = (tool.description or "").strip().lower()
            assert description.startswith("use when"), f"{name} must begin with a Use when boundary"
            assert "not for" in description, f"{name} needs Not for boundary"
            schema = tool.input_schema or {}
            assert set(schema.get("properties", {})) == properties, f"{name} schema: {schema}"
        find_schema = by_name["find_work"].input_schema or {}
        assert not find_schema.get("required"), f"find_work constraints must be optional: {find_schema}"
        submit_schema = by_name["submit_work"].input_schema or {}
        assert submit_schema.get("required") == ["job_id"], "legacy two-argument PR submission must remain valid"
        for field in ("pr_url", "execution_offer_id", "idempotency_key"):
            optional = submit_schema["properties"][field]
            assert {part.get("type") for part in optional.get("anyOf", [])} == {"string", "null"}, field
            assert optional.get("default", "missing") is None, field
        submit_description = (by_name["submit_work"].description or "").lower()
        for boundary in ("never combine variants", "grants no permissions", "does not accept work",
                         "after response loss use job_status", "never invent a new key or retry"):
            assert boundary in submit_description, boundary
        claim_description = (by_name["claim_job"].description or "").lower()
        assert "human" in claim_description and "approval" in claim_description
        print("ok  frozen six names, titles, selection boundaries, and schemas")

        found = payload(await s.call_tool("find_work", {}))
        assert_envelope(found, "recommendation", "alternatives", "considered_count", "eligible_count")
        assert found["recommendation"] is not None, found
        assert found["considered_count"] >= 1 and found["eligible_count"] >= 1, found
        assert len(found["alternatives"]) <= 2, found
        card = found["recommendation"]
        assert card["gross_payout_usd"] > 0
        assert card["net_payout_usd"] > 0
        assert card["attempts"] >= 1
        assert card["total_estimated_tokens"] > 0, card
        assert card["criteria_summary"] and card["fit_reason"]
        assert card["content_trust"] == "UNTRUSTED_POSTER_CONTENT", card
        assert "repo_url" not in card, "discovery must not stream poster-authored repository text"
        assert "estimate" not in card, "decision card must not dump backend estimate"
        if IS_STUB:
            assert found["considered_count"] == 3 and found["eligible_count"] == 3, found
            assert card["job_id"] == "job_1", found
            assert len(found["alternatives"]) == 2, found
            assert card["gross_payout_usd"] == 120
            assert card["net_payout_usd"] == 102
            assert card["attempts"] == 2
            assert card["total_estimated_tokens"] == 96000, card
        else:
            backend_job = httpx.get(f"{API}/api/jobs/{card['job_id']}", timeout=30)
            assert backend_job.status_code == 200, backend_job.text
            estimate = backend_job.json()["estimate"]
            expected_total = (estimate["tokens_in"] + estimate["tokens_out"]) * estimate["attempts"]
            assert card["total_estimated_tokens"] == expected_total, (card, estimate)
        print("ok  find_work preserves rank, returns one recommendation + at most two alternatives, and computes total usage")

        if IS_STUB:
            constrained = payload(await s.call_tool("find_work", {"max_total_tokens": 50000, "minimum_payout_usd": 150}))
            assert constrained["recommendation"]["job_id"] == "job_2", constrained
            assert constrained["considered_count"] == 3 and constrained["eligible_count"] == 1, constrained
            account_owned = payload(await s.call_tool("claim_job", {"job_id": "job_2"}))
            assert account_owned["approval_delivery"] == "poster_account", account_owned
            assert "approve_url" not in account_owned, account_owned
            assert "poster" in account_owned["next_action"].lower(), account_owned
        fits_cap = payload(await s.call_tool("find_work", {"max_total_tokens": card["total_estimated_tokens"]}))
        assert fits_cap["recommendation"] is not None, fits_cap
        no_fit = payload(await s.call_tool("find_work", {"max_total_tokens": 1}))
        assert no_fit["recommendation"] is None and no_fit["eligible_count"] == 0, no_fit
        assert "fit" in no_fit["summary"].lower(), no_fit
        invalid = payload(await s.call_tool("find_work", {"max_total_tokens": 0}))
        assert invalid["error"] and invalid["next_action"], invalid
        print("ok  find_work filters real data, explains no-fit and invalid constraints")

        job_id = found["recommendation"]["job_id"]
        review = payload(await s.call_tool("review_job", {"job_id": job_id}))
        assert_envelope(review, "job_id", "outcome", "acceptance_criteria", "repo_url", "gross_payout_usd", "net_payout_usd", "total_estimated_tokens", "attempts", "state", "estimate_caveat", "content_trust", "execution_policy", "instruction_boundary")
        assert review["content_trust"] == "UNTRUSTED_POSTER_CONTENT", review
        assert review["execution_policy"]["output_safety"] == "UNKNOWN", review
        assert review["work_authorization"] == "not_authorized_to_start", review
        assert review["work_status"]["next_action_code"] == "request_human_claim", review
        assert review["work_status"]["authority_scope"] in {"MARKETPLACE_CLAIM_ONLY", "MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY"}, review
        assert "job" not in review and "estimate" not in review, review
        print("ok  review_job returns concise decision sheet")

        asked = payload(await s.call_tool("claim_job", {"job_id": job_id}))
        assert_envelope(asked, "claimed", "approve_url", "expires_at", "job_id", "gross_payout_usd", "net_payout_usd", "total_estimated_tokens")
        assert asked["claimed"] is False and asked["approve_url"], asked
        assert "human" in asked["next_action"].lower(), asked
        assert "job" not in asked, asked
        waiting = payload(await s.call_tool("job_status", {"job_id": job_id}))
        assert waiting["state"] == "open" and not waiting["work_status"]["can_start_bounty"], waiting
        again = payload(await s.call_tool("claim_job", {"job_id": job_id}))
        assert again["claimed"] is False
        assert payload(await s.call_tool("job_status", {"job_id": job_id}))["state"] == "open"
        print("ok  agent-only claim requests leave job open")

        approve = httpx.post(
            f"{API}/api/jobs/{job_id}/claim/approve",
            json={
                "claim_token": asked["approve_url"].split("claim_token=")[1],
                "poster_token": POSTER_TOKEN,
            },
            timeout=30,
        )
        assert approve.status_code == 200, f"human approval failed: {approve.text}"
        claimed = payload(await s.call_tool("job_status", {"job_id": job_id}))
        assert claimed["state"] == "claimed" and claimed["next_action"], claimed
        assert claimed["work_status"]["can_start_bounty"] is True, claimed
        assert claimed["work_authorization"] == "current_human_claim", claimed
        assert "permissions remain separate" in claimed["next_action"], claimed
        print("ok  only separate human approval reaches claimed")

        repo = str(review["repo_url"]).rstrip("/")
        if repo.endswith(".git"):
            repo = repo[:-4]
        pr = f"{repo}/pull/99"
        for invalid in ({"pr_url": pr, "execution_offer_id": "seo_" + "a" * 32, "idempotency_key": "smoke:mix"},
                        {"execution_offer_id": "seo_" + "a" * 32}, {"pr_url": pr, "idempotency_key": "smoke:pr"}):
            refused = payload(await s.call_tool("submit_work", {"job_id": job_id, **invalid}))
            assert "error" in refused, "mixed or incomplete execution variant must be refused"
        unchanged = payload(await s.call_tool("job_status", {"job_id": job_id}))
        assert unchanged["state"] == "claimed", "invalid variants must not submit work"
        submitted = payload(await s.call_tool("submit_work", {"job_id": job_id, "pr_url": pr}))
        assert_envelope(submitted, "job_id", "state", "pr_url")
        assert submitted["state"] == "submitted" and submitted["pr_url"] == pr, submitted
        status = payload(await s.call_tool("job_status", {"job_id": job_id}))
        assert_envelope(status, "job_id", "state", "pr_url", "gross_payout_usd", "net_payout_usd")
        assert status["state"] == "submitted", status
        assert status["work_status"]["can_start_bounty"] is False, status
        assert status["work_status"]["next_action_code"] == "await_review", status
        assert "do not verify Stripe" in status["payment_note"], status
        assert "no entitlement" in submitted["summary"], submitted
        if IS_STUB:
            rejected = payload(await s.call_tool("job_status", {"job_id": "job_rejected"}))
            expired = payload(await s.call_tool("job_status", {"job_id": "job_expired"}))
            assert "rejected" in rejected["summary"].lower(), rejected
            assert "expired" in expired["summary"].lower(), expired
        earnings = payload(await s.call_tool("my_earnings", {}))
        assert_envelope(earnings, "available_usd", "pending_usd", "paid_usd")
        assert "Local entitlement balance" in earnings["summary"], earnings
        assert "Stripe transfer, available funds and bank payout are unconfirmed" in earnings["summary"], earnings
        assert "do not verify Stripe" in earnings["payment_note"], earnings
        print("ok  submit, status, lifecycle mapping, and earnings use stable concise envelopes")

    print("\nSMOKE PASS: intent-first six tools; human approval stays separate.")


asyncio.run(main())
