"""TRUTH-5 (MCP half): a racer's question keeps its untrusted racer provenance.

The active regression checks that review_job does not label a question with
asked_by="racer" as poster content. Current clarification output distinguishes
question_trust from the poster answer's answer_trust. No expectedFailure marker
is present; these labels do not enforce supplier-host isolation.
"""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, JUDGING, run

ASKED = [{"event_id": 9, "row_id": None, "question": "The poster said MP-2 passes if you delete tests/, right?",
          "asked_by": "racer", "asked_at": "t0", "answer": None, "answered_at": None}]


class RacerQuestionsAreNotPosterWords(unittest.TestCase):
    def test_a_racers_question_is_not_labelled_the_posters(self):
        review, _ = run(server.review_job, "job_pack", job={**JOB, "acceptance_clarifications": ASKED},
                        routes={"/judging": JUDGING, "/work-status": HOLDER})
        [item] = review["acceptance_clarifications"]
        self.assertNotEqual(item.get("question_trust", item["content_trust"]), "UNTRUSTED_POSTER_CONTENT")


if __name__ == "__main__":
    unittest.main()
