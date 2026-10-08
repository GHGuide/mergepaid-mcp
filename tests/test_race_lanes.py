"""A race over MCP: open lanes, the caller's own lane, and nothing of a rival's work."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from mergepaid_mcp import server

BOARD = [
    {"lane": 1, "state": "submitted", "supplier_id": "sup_aaaaaaaa", "supplier_name": "rival",
     "expires_at": None, "pr_submitted": True, "pr_url": "https://github.com/acme/api/pull/1"},
    {"lane": 2, "state": "racing", "supplier_id": "sup_bbbbbbbb", "supplier_name": "me",
     "expires_at": "2026-09-22T12:00:00+00:00", "pr_submitted": False},
    {"lane": 3, "state": "open", "supplier_id": None, "supplier_name": None,
     "expires_at": None, "pr_submitted": False},
]
JOB = {"id": "job_race", "state": "submitted", "title": "Race", "description": "d", "criteria": "c",
       "amount_usd": 100, "repo_url": "https://github.com/acme/api", "estimate": {"attempts": 1},
       "lanes": 3, "lanes_open": 1, "lane_board": BOARD, "pr_url": None}
WORK = {"schema": "supplier-job-work-v2", "job_id": "job_race", "job_state": "submitted", "assignment": "you",
        "project": {"status": "standalone", "dependencies": "not_applicable"}, "claim": {"status": "active_for_you"},
        "can_start_bounty": True, "next_action_code": "submit_work", "next_action": server.WORK_ACTIONS["submit_work"],
        "authority_scope": "MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY",
        "functional_completion": {"status": "none", "authority": None},
        "can_submit_pr": True, "submission_authority": "CURRENT_HUMAN_CLAIM"}


def call(tool, *args, job=JOB, me="sup_bbbbbbbb", work=WORK):
    def backend(method, path, **kwargs):
        if path.endswith("/work-status"):
            return deepcopy(work)
        if path == "/api/suppliers/me":
            return {"id": me}
        if path.endswith("/execution-policy"):
            return {"default": "DENY_UNLESS_SEPARATELY_APPROVED"}
        if path == "/api/discovery/jobs":
            return [{k: v for k, v in job.items() if k not in ("lane_board",)}]
        return deepcopy(job)

    with patch.object(server, "TOKEN", "sup_token"), patch.object(server, "_call", side_effect=backend):
        return tool(*args)


class RaceLaneTests(unittest.TestCase):
    def test_find_work_says_how_many_lanes_are_free(self):
        card = call(server.find_work)["recommendation"]
        self.assertEqual((card["lanes"]["total"], card["lanes"]["open"]), (3, 1))
        self.assertIn("first lane", card["lanes"]["note"])

    def test_review_shows_rivals_by_lane_and_state_never_their_pull_request(self):
        result = call(server.review_job, "job_race")
        self.assertEqual([(r["lane"], r["state"], r["racer"]) for r in result["lanes"]["racers"]],
                         [(1, "submitted", "rival"), (2, "racing", "me"), (3, "open", None)])
        self.assertNotIn("pull/1", json.dumps(result))

    def test_status_reports_the_callers_own_lane(self):
        result = call(server.job_status, "job_race")
        self.assertEqual(result["your_lane"]["lane"], 2)
        self.assertEqual(result["your_lane"]["state"], "racing")
        self.assertIn("Submit its pull request", result["summary"])
        # the job reads submitted for another lane; this racer is still authorized
        self.assertEqual(result["work_authorization"], "current_human_claim")
        self.assertNotIn("pull/1", json.dumps(result))

    def test_a_hold_on_a_rivals_merge_never_stops_a_racing_lane(self):
        hold = {"status": "held", "reason_code": "authorization_missing", "reason": "r",
                "next_action": "n", "poster_can_confirm": True, "poster_can_reject": False}
        result = call(server.job_status, "job_race", job=dict(JOB, acceptance_hold=hold))
        self.assertEqual(result["your_lane"]["state"], "racing")
        self.assertNotIn("acceptance_hold", result)
        self.assertEqual(result["next_action"], server.WORK_ACTIONS["submit_work"])
        self.assertIn("Submit its pull request", result["summary"])
        # the racer whose pull request is in still hears why its merge has not settled
        submitted = [dict(BOARD[0], state="racing", supplier_id="sup_cccccccc"),
                     dict(BOARD[1], state="submitted", pr_submitted=True)]
        mine = call(server.job_status, "job_race", job=dict(JOB, acceptance_hold=dict(hold, lane=2), lane_board=submitted))
        self.assertEqual(mine["acceptance_hold"]["reason_code"], "authorization_missing")

    def test_status_says_a_lost_lane_earns_nothing(self):
        board = [dict(BOARD[0], state="won"), dict(BOARD[1], state="lost", expires_at=None)]
        job = dict(JOB, state="paid", lane_board=board, lanes_open=0)
        work = dict(WORK, job_state="paid", assignment="other", claim={"status": "other"}, can_start_bounty=False,
                    next_action_code="assigned_elsewhere", next_action=server.WORK_ACTIONS["assigned_elsewhere"],
                    can_submit_pr=False, submission_authority="NONE")
        result = call(server.job_status, "job_race", job=job, work=work)
        self.assertEqual(result["your_lane"]["state"], "lost")
        self.assertIn("earns nothing", result["summary"])

    def test_status_without_a_lane_says_so(self):
        result = call(server.job_status, "job_race", me="sup_cccccccc")
        self.assertEqual(result["your_lane"], {"lane": None, "state": "none"})

    def test_a_one_lane_job_is_presented_as_before(self):
        one = {k: v for k, v in JOB.items() if k not in ("lanes", "lanes_open", "lane_board")}
        one["state"] = "claimed"
        result = call(server.job_status, "job_race", job=one, work=dict(WORK, job_state="claimed"))
        self.assertNotIn("your_lane", result)
        self.assertEqual(result["lanes"], {"total": 1, "open": None})

    def test_a_request_on_a_race_says_no_lane_is_held_yet(self):
        def backend(method, path, **kwargs):
            if path.endswith("/credentials"):
                return {"credential": "mpo_x"}
            if path.endswith("/claim/request"):
                return {"claimed": False, "approval_delivery": "poster_account", "expires_at": "t", "lanes": 3}
            return deepcopy(JOB)

        with patch.object(server, "TOKEN", "sup_token"), patch.object(server, "_call", side_effect=backend):
            result = server.claim_job("job_race")
        self.assertFalse(result["claimed"])
        self.assertIn("no lane until the poster approves", result["summary"])


if __name__ == "__main__":
    unittest.main()
