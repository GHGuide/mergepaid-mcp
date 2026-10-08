"""TRUTH-10 (MCP): handback guidance names evidence bound to see-it rows.

The active regression checks that job_status's change-request next_action names
per-row evidence as well as evidence_urls. Current guidance says existing links
stay attached and resending replaces them. No expectedFailure marker is present.
"""
import re
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, JUDGING, run

WORK = {"job_id": "job_pack", "work": {"changes_open": True, "change_requests": [
    {"message": "Fix MP-3", "requested_at": "t", "pr_url": "p", "row_ids": ["MP-3"]}]}}


class HandbackWordsNameRowEvidence(unittest.TestCase):
    def test_the_handback_words_name_per_row_evidence(self):
        result, _ = run(server.job_status, "job_pack", job={**JOB, "state": "claimed"},
                        routes={"/judging": {**JUDGING, "acceptance": {**JUDGING["acceptance"],
                            "rows": [{"id": "MP-3", "class": "see_it"}]}}, "/work-status": HOLDER, "/work": WORK})
        self.assertRegex(result["next_action"], r"\bevidence\b(?!_urls)")


if __name__ == "__main__":
    unittest.main()
