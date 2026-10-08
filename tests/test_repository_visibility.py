"""review_job relays whether GitHub confirmed the job's repository public (ADR 92)."""
import unittest

from mergepaid_mcp import server
from test_race_lanes import JOB, call


class RepositoryVisibilityTests(unittest.TestCase):
    def test_review_says_public_only_when_github_said_so(self):
        self.assertEqual(call(server.review_job, "job_race", job={**JOB, "repository_visibility": "public"})
                         ["repository_visibility"], "public")
        self.assertEqual(call(server.review_job, "job_race")["repository_visibility"], "unchecked")


if __name__ == "__main__":
    unittest.main()
