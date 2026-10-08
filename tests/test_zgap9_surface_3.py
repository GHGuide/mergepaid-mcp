"""SURFACE9-3 (MCP half): a claim a restore's founders' item holds, whose submission the restore
may have lost. /work says so in MergePaid's own words, and job_status relays them, as it does for a
copy review, rather than the generic "submit it before the claim ends"."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import HOLDER, JOB, JUDGING, run

TOLD = ("MergePaid was restored from a backup that may have lost your submission on this job: if you submitted, "
        "submit the same pull request again. Your claim does not run out while the MergePaid founders check what "
        "happened.")


class RestoredClaimWords(unittest.TestCase):
    def test_the_racer_whose_submission_a_restore_lost_is_told_to_submit_it_again(self):
        result = run(server.job_status, "job_pack", job={**JOB, "state": "claimed"},
                     routes={"/judging": JUDGING, "/work-status": HOLDER,
                             "/work": {"job_id": "job_pack", "work": {"next_action": TOLD}}})[0]
        self.assertEqual(result["next_action"], TOLD)


if __name__ == "__main__":
    unittest.main()
