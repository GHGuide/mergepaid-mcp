"""Fixed supplier projection presentation; no network, processes or providers."""
from copy import deepcopy
import inspect
import json
import unittest
from unittest.mock import patch

from mergepaid_mcp import server


JOB = {"id": "job_fixture", "state": "claimed", "title": "Authored public task",
       "description": "Public outcome", "criteria": "Public criteria", "amount_usd": 100,
       "repo_url": "https://github.com/fixture/public", "estimate": {"attempts": 1}}
POLICY = {"default": "DENY_UNLESS_SEPARATELY_APPROVED", "output_safety": "UNKNOWN"}


def projection(*, state="claimed", assignment="you", project="current", dependencies="ready",
               claim="active_for_you", can_start=True, action="submit_work"):
    return {"schema": "supplier-job-work-v1", "job_id": JOB["id"], "job_state": state,
            "assignment": assignment, "project": {"status": project, "dependencies": dependencies},
            "claim": {"status": claim}, "can_start_bounty": can_start,
            "next_action_code": action, "next_action": server.WORK_ACTIONS[action],
            "authority_scope": "MARKETPLACE_CLAIM_ONLY"}


def call_tool(tool, value, *, state="claimed", token="authored_supplier_fixture", job_extra=None):
    calls = []

    def backend(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/work-status"):
            return deepcopy(value)
        if path.endswith("/execution-policy"):
            return deepcopy(POLICY)
        return {**JOB, "state": state, **(job_extra or {})}

    with patch.object(server, "TOKEN", token), patch.object(server, "_call", side_effect=backend):
        result = tool(JOB["id"])
    return result, calls


class SupplierWorkPresentationTests(unittest.TestCase):
    def test_review_and_status_use_current_assignment_without_new_authority(self):
        for tool in (server.review_job, server.job_status):
            with self.subTest(tool=tool.__name__):
                result, calls = call_tool(tool, projection())
                self.assertTrue(result["work_status"]["can_start_bounty"])
                self.assertEqual(result["work_authorization"], "current_human_claim")
                self.assertIn("context, runtime and network permissions remain separate", result["next_action"])
                self.assertIn("do not verify Stripe", result["payment_note"])
                self.assertEqual(result["net_payout_usd"], 85)
                status_calls = [item for item in calls if item[1].endswith("/work-status")]
                self.assertEqual(status_calls, [("GET", "/api/jobs/job_fixture/work-status", {
                    "headers": {"Authorization": "Bearer authored_supplier_fixture"}})])
                self.assertTrue(all(method == "GET" for method, _, _ in calls))
                # The holder's own reads (the review loop's /work too) carry its bearer and nothing else; every other read is anonymous.
                holder_reads = ("/work-status", "/work", "/judging", "/context", "/claim-request")
                self.assertTrue(all(kwargs == {"headers": {"Authorization": "Bearer authored_supplier_fixture"}}
                                    for _, path, kwargs in calls if path.endswith(holder_reads)))
                self.assertTrue(all(not kwargs for _, path, kwargs in calls if not path.endswith(holder_reads)))

    def test_preclaim_and_other_supplier_cannot_start(self):
        cases = [
            (projection(state="open", assignment="unassigned", claim="none", can_start=False,
                        action="request_human_claim"), "open"),
            (projection(assignment="other", claim="other", can_start=False, action="assigned_elsewhere"), "claimed"),
        ]
        for value, state in cases:
            for tool in (server.review_job, server.job_status):
                with self.subTest(action=value["next_action_code"], tool=tool.__name__):
                    result, _ = call_tool(tool, value, state=state)
                    self.assertFalse(result["work_status"]["can_start_bounty"])
                    self.assertEqual(result["work_authorization"], "not_authorized_to_start")
                    self.assertEqual(result["next_action"], value["next_action"])

    def test_stale_blocked_expired_and_unknown_work_never_instruct_start(self):
        cases = [
            projection(project="stale", dependencies="unknown", can_start=False, action="wait_for_owner"),
            projection(dependencies="blocked", can_start=False, action="wait_for_owner"),
            projection(claim="expired", can_start=False, action="claim_again"),
            projection(project="unavailable", dependencies="unknown", can_start=False, action="authorization_unknown"),
        ]
        for value in cases:
            for tool in (server.review_job, server.job_status):
                with self.subTest(value=value["next_action_code"], tool=tool.__name__):
                    result, _ = call_tool(tool, value)
                    self.assertFalse(result["work_status"]["can_start_bounty"])
                    self.assertNotEqual(result["work_authorization"], "current_human_claim")
                    self.assertNotIn("Complete the work", result["next_action"])
                    self.assertEqual(result["next_action"], value["next_action"])
                    if value["next_action_code"] == "authorization_unknown":
                        self.assertEqual(result["work_authorization"], "unknown")

    def test_no_token_keeps_public_information_and_authorization_unknown(self):
        for tool in (server.review_job, server.job_status):
            result, calls = call_tool(tool, projection(), token="")
            self.assertIsNone(result["work_status"])
            self.assertEqual(result["work_authorization"], "unknown")
            self.assertEqual(result["next_action"], server.WORK_ACTIONS["authorization_unknown"])
            self.assertEqual(result["state"], "claimed")
            self.assertEqual(result["net_payout_usd"], 85)
            self.assertFalse(any(path.endswith("/work-status") for _, path, _ in calls))

    def test_missing_unavailable_or_mixed_read_is_unknown_without_retry(self):
        cases = [None, [], {"error": "Authored unavailable response"}, {"detail": "missing"},
                 projection(state="open", assignment="unassigned", claim="none", can_start=False, action="request_human_claim")]
        for value in cases:
            for tool in (server.review_job, server.job_status):
                with self.subTest(value=value, tool=tool.__name__):
                    result, calls = call_tool(tool, value)
                    self.assertEqual(result["work_authorization"], "unknown")
                    self.assertIsNone(result["work_status"])
                    self.assertEqual(result["next_action"], server.WORK_ACTIONS["authorization_unknown"])
                    self.assertEqual(sum(path.endswith("/work-status") for _, path, _ in calls), 1)

    def test_only_fixed_allowlisted_projection_is_presented(self):
        cases = []
        for key in ("brief", "source", "grant", "sibling_ids", "owner_id"):
            value = projection(); value[key] = "private_projection_marker"; cases.append(value)
        value = projection(); value["project"]["id"] = "private_projection_marker"; cases.append(value)
        value = projection(); value["claim"]["approval_url"] = "private_projection_marker"; cases.append(value)
        value = projection(); value["next_action"] = "private_projection_marker"; cases.append(value)
        for value in cases:
            for tool in (server.review_job, server.job_status):
                result, _ = call_tool(tool, value)
                self.assertEqual(result["work_authorization"], "unknown")
                self.assertNotIn("private_projection_marker", json.dumps(result))

    def test_typed_identity_and_authority_inconsistencies_are_not_permissions(self):
        cases = []
        for key, replacement in [("job_id", "job_other"), ("schema", "different"), ("authority_scope", "RUNTIME_ACCESS"),
                                 ("assignment", []), ("can_start_bounty", 1), ("next_action_code", {}), ("job_state", None)]:
            value = projection(); value[key] = replacement; cases.append(value)
        cases.extend([projection(assignment="other"), projection(project="stale"),
                      projection(dependencies="blocked"), projection(claim="expired"),
                      projection(can_start=False)])
        for value in cases:
            result, _ = call_tool(server.job_status, value)
            self.assertEqual(result["work_authorization"], "unknown")
            self.assertIsNone(result["work_status"])

    def test_standalone_claim_preserves_existing_workflow(self):
        value = projection(project="standalone", dependencies="not_applicable")
        result, _ = call_tool(server.job_status, value)
        self.assertTrue(result["work_status"]["can_start_bounty"])
        self.assertEqual(result["work_authorization"], "current_human_claim")

    def test_submitted_and_paid_copy_retains_payment_limits(self):
        for state, action in (("submitted", "await_review"), ("paid", "check_payment_record")):
            value = projection(state=state, claim="closed", can_start=False, action=action)
            result, _ = call_tool(server.job_status, value, state=state)
            self.assertFalse(result["work_status"]["can_start_bounty"])
            self.assertEqual(result["next_action"], server.WORK_ACTIONS[action])
            self.assertIn("do not verify Stripe", result["payment_note"])
        self.assertIn("Local entitlement", result["summary"])

    def test_invalid_job_reference_never_constructs_a_request(self):
        for value in (None, [], "", "x" * 129, "ordinary label with spaces"):
            with patch.object(server, "_call") as call:
                for tool in (server.review_job, server.job_status):
                    result = tool(value)
                    self.assertIn("error", result)
                    self.assertEqual(result["next_action"], "Check the job ID.")
                call.assert_not_called()

    def test_eight_tools_and_their_arguments(self):
        # The demo-only execution variant is gone from the published surface.
        expected = {"find_work": {"max_total_tokens", "minimum_payout_usd", "languages"}, "review_job": {"job_id"},
                    "claim_job": {"job_id"},
                    # Acceptance pack v1 (proposed ADR A4): the check, the evidence and the honest
                    # exit; the change-request thread's note (collaboration) rides along.
                    # acceptance-pack-v2: evidence bound to see-it rows (DEF-11).
                    "submit_work": {"job_id", "pr_url", "tokens_used", "message", "check_only", "evidence_urls",
                                    "blocker_code", "blocker_note", "evidence", "patch", "deliverable_url", "note"},
                    "job_status": {"job_id", "wait_seconds", "reply", "since"}, "my_earnings": set(),
                    "read_messages": {"since"},
                    "send_message": {"conversation_id", "text", "on_behalf_of_owner"}}
        self.assertEqual(inspect.getsource(server).count("@mcp.tool("), 8)
        self.assertNotIn("local-supplier-execution", inspect.getsource(server))
        for name, fields in expected.items():
            self.assertEqual(set(inspect.signature(getattr(server, name)).parameters), fields)


if __name__ == "__main__":
    unittest.main()

class FunctionalWorkV2Tests(unittest.TestCase):
    def packet(self):
        value = projection(dependencies='blocked', claim='expired', can_start=False, action='submit_accepted_work')
        value.update(schema='supplier-job-work-v2', authority_scope='MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY',
                     functional_completion={'status': 'accepted', 'authority': 'OWNER_ACCEPTANCE_TESTIMONY'},
                     can_submit_pr=True, submission_authority='ACCEPTED_RESULT_HANDOFF')
        return value

    def test_accepted_handoff_is_visible_without_start_permission(self):
        for tool in (server.job_status, server.review_job):
            result, _ = call_tool(tool, self.packet())
            self.assertEqual(result['work_authorization'], 'not_authorized_to_start')
            self.assertTrue(result['work_status']['can_submit_pr'])
            self.assertIn('existing pull request', result['next_action'])

    def test_accepted_other_supplier_requires_assigned_elsewhere_priority(self):
        for project in ({'status': 'current', 'dependencies': 'blocked'},
                        {'status': 'unavailable', 'dependencies': 'unknown'}):
            for tool in (server.job_status, server.review_job):
                value = self.packet()
                value.update(assignment='other', project=project, can_submit_pr=False, submission_authority='NONE',
                             next_action_code='assigned_elsewhere', next_action=server.WORK_ACTIONS['assigned_elsewhere'])
                with self.subTest(project=project, tool=tool.__name__):
                    result, _ = call_tool(tool, value)
                    self.assertEqual(result['work_status'], value)
                    self.assertFalse(result['work_status']['can_start_bounty'])
                    self.assertFalse(result['work_status']['can_submit_pr'])
                    self.assertEqual(result['work_authorization'], 'not_authorized_to_start')
                    for action in ('wait_for_owner', 'claim_again', 'authorization_unknown'):
                        invalid = deepcopy(value)
                        invalid.update(next_action_code=action, next_action=server.WORK_ACTIONS[action])
                        result, calls = call_tool(tool, invalid)
                        self.assertIsNone(result['work_status'])
                        self.assertEqual(result['work_authorization'], 'unknown')
                        self.assertEqual(result['next_action'], server.WORK_ACTIONS['authorization_unknown'])
                        self.assertEqual(result['state'], 'claimed')
                        self.assertEqual(sum(path.endswith('/work-status') for _, path, _ in calls), 1)

    def test_cross_field_lies_and_private_extensions_fail_closed(self):
        changes = [('assignment','other'), ('can_start_bounty',True), ('can_submit_pr',False),
                   ('submission_authority','CURRENT_HUMAN_CLAIM'), ('functional_completion', {'status':'none','authority':None}),
                   ('functional_completion', {'status':'accepted','authority':'PROVIDER_VERIFIED'}),
                   ('functional_completion', {'status':'accepted','authority':'OWNER_ACCEPTANCE_TESTIMONY','id':'private'})]
        for key, replacement in changes:
            value = self.packet(); value[key] = replacement
            result, _ = call_tool(server.job_status, value)
            self.assertIsNone(result['work_status'])

    def test_submitted_awaits_review_and_unavailable_never_claims_handoff(self):
        value = self.packet()
        value.update(job_state='submitted', claim={'status':'closed'}, can_submit_pr=False, submission_authority='NONE',
                     next_action_code='await_review', next_action=server.WORK_ACTIONS['await_review'])
        result, _ = call_tool(server.job_status, value, state='submitted')
        self.assertEqual(result['work_status']['next_action_code'], 'await_review')
        value = self.packet()
        value.update(functional_completion={'status':'unavailable','authority':None}, can_submit_pr=False, submission_authority='NONE',
                     next_action_code='authorization_unknown', next_action=server.WORK_ACTIONS['authorization_unknown'])
        result, _ = call_tool(server.job_status, value)
        self.assertEqual(result['work_authorization'], 'unknown')
        self.assertIsNotNone(result['work_status'])


class WorkStatusEnvelopeTests(unittest.TestCase):
    def packet(self, *, v2=True, action="request_human_claim"):
        value = projection(state="open", assignment="unassigned", project="standalone",
                           dependencies="not_applicable", claim="none", can_start=False, action=action)
        if v2:
            value.update(schema="supplier-job-work-v2", authority_scope="MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY",
                         functional_completion={"status": "none", "authority": None},
                         can_submit_pr=False, submission_authority="NONE")
        return value

    def test_metadata_stays_beside_the_exact_packet(self):
        for mode in ("poster", "racer"):
            for left in (0, 1, 2):
                for tool in (server.review_job, server.job_status):
                    with self.subTest(mode=mode, left=left, tool=tool.__name__):
                        packet = self.packet()
                        if mode == "racer":
                            packet["next_action"] = server._RACER_TAKE_ACTION
                        value = {"work_status": packet, "approval_mode": mode, "attempts_left": left}
                        result, _ = call_tool(tool, value, state="open")
                        self.assertEqual(set(result["work_status"]), set(packet))
                        self.assertEqual(result["work_status"], packet)
                        self.assertEqual(result["approval_mode"], mode)
                        self.assertEqual(result["attempts_left"], left)
                        self.assertFalse(result["work_status"]["can_start_bounty"])

    def test_older_bare_or_wrapped_packets_have_unknown_metadata(self):
        for v2 in (False, True):
            packet = self.packet(v2=v2)
            for value in (packet, {"work_status": packet}):
                for tool in (server.review_job, server.job_status):
                    with self.subTest(v2=v2, wrapped="work_status" in value, tool=tool.__name__):
                        result, _ = call_tool(tool, value, state="open")
                        self.assertEqual(result["work_status"], packet)
                        self.assertIsNone(result.get("approval_mode"))
                        self.assertIsNone(result.get("attempts_left"))

    def test_active_sealed_and_cancelled_presentations_keep_metadata_outside(self):
        for state, extra in (("claimed", {}), ("claimed", {"sealed": True}), ("cancelled", {})):
            packet = projection(project="standalone", dependencies="not_applicable")
            packet.update(schema="supplier-job-work-v2", authority_scope="MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY",
                          functional_completion={"status": "none", "authority": None},
                          can_submit_pr=True, submission_authority="CURRENT_HUMAN_CLAIM")
            if state == "cancelled":
                packet.update(job_state=state, claim={"status": "closed"}, can_start_bounty=False,
                              can_submit_pr=False, submission_authority="NONE", next_action_code="closed",
                              next_action=server.WORK_ACTIONS["closed"])
            for tool in (server.review_job, server.job_status):
                result, _ = call_tool(tool, {"work_status": packet, "approval_mode": "poster", "attempts_left": 1},
                                      state=state, job_extra=extra)
                self.assertEqual(set(result["work_status"]), set(packet))
                self.assertEqual(result["approval_mode"], "poster")
                self.assertEqual(result["attempts_left"], 1)
                self.assertEqual(result["work_status"]["can_start_bounty"], state == "claimed")
                self.assertEqual(result["work_status"]["can_submit_pr"], state == "claimed")

    def test_optional_metadata_is_validated_independently(self):
        for fields in ({"approval_mode": "poster"}, {"attempts_left": 0}):
            result, _ = call_tool(server.job_status, {"work_status": self.packet(), **fields}, state="open")
            self.assertEqual(result["work_status"], self.packet())
            for field in ("approval_mode", "attempts_left"):
                self.assertEqual(result.get(field), fields.get(field))

    def test_invalid_metadata_is_unknown_without_retry(self):
        for field, values in (("approval_mode", (None, True, 1, "unknown", [], {})),
                              ("attempts_left", (None, True, False, -1, 3, 1.0, "1", [], {}))):
            for replacement in values:
                for tool in (server.review_job, server.job_status):
                    with self.subTest(field=field, value=replacement, tool=tool.__name__):
                        value = {"work_status": self.packet(), field: replacement}
                        result, calls = call_tool(tool, value, state="open")
                        self.assertIsNone(result["work_status"])
                        self.assertEqual(result["work_authorization"], "unknown")
                        self.assertEqual(sum(path.endswith("/work-status") for _, path, _ in calls), 1)

    def test_nested_metadata_and_private_extensions_are_rejected(self):
        for field, addition in (("approval_mode", "racer"), ("attempts_left", 1),
                                ("source", "private_projection_marker")):
            packet = {**self.packet(), field: addition}
            for value in (packet, {"work_status": packet, "approval_mode": "poster", "attempts_left": 2}):
                result, _ = call_tool(server.job_status, value, state="open")
                self.assertIsNone(result["work_status"])
                self.assertNotIn("private_projection_marker", json.dumps(result))
        result, _ = call_tool(server.job_status, {"work_status": self.packet(),
                             "source": "private_projection_marker"}, state="open")
        self.assertIsNone(result["work_status"])
        self.assertNotIn("private_projection_marker", json.dumps(result))

    def test_wrapping_does_not_weaken_packet_validation(self):
        for field, replacement in (("job_id", "job_other"), ("can_start_bounty", True),
                                   ("can_submit_pr", True), ("next_action", "private_projection_marker")):
            packet = {**self.packet(), field: replacement}
            result, _ = call_tool(server.job_status, {"work_status": packet,
                                 "approval_mode": "poster", "attempts_left": 1}, state="open")
            self.assertIsNone(result["work_status"])
        for packet in (None, [], "invalid"):
            result, _ = call_tool(server.job_status, {"work_status": packet}, state="open")
            self.assertIsNone(result["work_status"])

    def test_racer_pending_copy_reads_top_level_mode(self):
        packet = self.packet(action="await_claim_decision")
        packet["next_action"] = server._RACER_TAKE_ACTION
        for tool in (server.review_job, server.job_status):
            result, _ = call_tool(tool, {"work_status": packet, "approval_mode": "racer", "attempts_left": 1},
                                  state="open")
            self.assertEqual(result["next_action"], server._RACER_TAKE_ACTION)
            self.assertEqual(result["work_status"], packet)
            for fields in ({}, {"approval_mode": "poster"}):
                result, _ = call_tool(tool, {"work_status": packet, **fields}, state="open")
                self.assertIsNone(result["work_status"])
