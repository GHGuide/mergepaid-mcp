"""TRUTH-4 (MCP half): a house rule MergePaid can't read (`held: null`) is told to the racer
as one that "did not hold", with "Fix it and push again".

Every check passed; the only thing between the version and ready is a v2 patch-reading rule
GitHub left no patch for (contract: "held: null ... null never reads ready and is never
citable"). _check_next_words falls through to _CHECK_NOT_YET, which says some checks "did
not pass" or a rule "did not hold": neither happened, and pushing again changes nothing
while the file's patch stays hidden.

Fixed in R2-B: an unreadable rule (held null, reason code house_rule_unread) has its own words.
"""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import STATUS

UNREAD = {**STATUS, "ready": False, "house_rules": [
    {"rule": "max_changed_lines", "held": True, "detail": "2 of 300"},
    {"rule": "no_secrets", "held": None, "detail": "GitHub shows no lines for dist/index.js, so they can't be read"}]}


class UnreadableRuleWords(unittest.TestCase):
    def test_an_unreadable_rule_is_not_called_broken(self):
        words = server._acceptance_status(UNREAD, "job_pack", head=STATUS["head_commit"], state="claimed")["next_action"]
        self.assertNotIn("did not hold", words)
        self.assertNotIn("did not pass", words)


if __name__ == "__main__":
    unittest.main()
