"""SURFACE4-5 (round 4): held-out cases the poster revealed in a change request vanish from
job_status once the racer hands the fix back, while review_job tells it to read them there.

The poster asks for changes naming the held-out row MP-6, revealing its cases file. While the
ask is open, job_status carries `change_request.held_out.cases_file`. The racer hands the fix
back: `changes_open` is false, so `_change_request` returns None; no rejection exists, so
neither `your_rejection` nor `previous_rejection` (FLOW3-4) is built. /work still carries the
file (`change_requests[-1].held_out.cases_file`), but no field of job_status does. review_job's
`held_out_revealed` (revealed_to_you, FLOW3-4's fix) says "read them in job_status
(your_rejection.held_out, previous_rejection.held_out or change_request.held_out)": none exists.
The same holds after a later send-back that names another row, and after the racer is seated
again: the cases it must still meet are named as readable where they are not. The web lane
shows them only on the open ask too (Review.jsx YourLane: `ask` needs `changes_open`).
"""
from copy import deepcopy
import json
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import ACCEPTANCE, HOLDER, JOB, JUDGING, run

CASES = "case-1: '+' in the local part logs in\ncase-2: '++' is refused\n"
HELD = {"id": "MP-6", "class": "held_out", "name": "Passes my held-out cases", "cases": 2, "commitment": "c" * 64}
REVEALED = {"row_id": "MP-6", "sha256": "c" * 64, "at": "2026-09-27T09:00:00+00:00", "revealed_to_you": True,
            "revealed_to_you_at": "2026-09-27T09:00:00+00:00", "words": "revealed to you"}
ASK = {"id": 40, "message": "MP-6 still fails two of my cases", "requested_at": "2026-09-27T09:00:00+00:00",
       "pr_url": "https://github.com/acme/widget/pull/17", "supplier_id": "sup_1", "row_ids": ["MP-6"],
       "resubmitted_at": "2026-09-27T11:00:00+00:00", "resolved_at": None, "messages": [],
       "held_out": {"row_id": "MP-6", "sha256": "c" * 64, "bytes": len(CASES), "cases_file": CASES}}


class RevealedInAChangeRequest(unittest.TestCase):
    def test_cases_revealed_to_the_racer_stay_where_review_job_says_they_are(self):
        acceptance = {**deepcopy(ACCEPTANCE), "schema": "acceptance-pack-v2", "rows": ACCEPTANCE["rows"] + [HELD],
                      "held_out_revealed": REVEALED}
        judging = {**JUDGING, "acceptance": acceptance}
        job = {**JOB, "state": "submitted", "acceptance_summary": {**JOB["acceptance_summary"], "held_out": 1}}
        handed_back = {**HOLDER, "job_state": "submitted", "next_action_code": "await_review",
                       "next_action": server.WORK_ACTIONS["await_review"], "can_start_bounty": False}
        work = {"job_id": "job_pack", "work": {"status": "submitted", "changes_open": False, "claimed_event_id": 5,
                                               "change_requests": [ASK], "rejection": None}}
        routes = {"/judging": judging, "/work-status": handed_back, "/work": work}
        review = run(server.review_job, "job_pack", job=job, routes=routes)[0]
        said = review["acceptance"]["held_out_revealed"]["words"]
        self.assertIn("read them in job_status", said)  # where the racer is told to read them
        status = run(server.job_status, "job_pack", job=job, routes=routes)[0]
        self.assertIn(json.dumps(CASES), json.dumps(status))


if __name__ == "__main__":
    unittest.main()
