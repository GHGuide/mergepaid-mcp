"""Round 4 · R4-C, principle E: a ready version's words say which passed rows the fix's own
code or configuration can influence (the backend's `independent: false`), so the racer knows
the poster may still name them; a black-box pass adds nothing, and nothing a malformed row id
says is repeated."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import STATUS

READY = {"ready": True, "judge_intact": True, "reason_codes": [], "house_rules": [],
         "rows": [{"id": "MP-1", "status": "passed", "solid": False, "limit": "not yet proven on GitHub",
                   "independent": True},
                  {"id": "MP-2", "status": "passed", "solid": False, "limit": "tool", "independent": False}]}


def words(state="claimed", head=None, **status):
    return server._acceptance_status({**STATUS, **status}, "job_pack", head=head, state=state)["next_action"]


class PrincipleE(unittest.TestCase):
    def test_a_ready_version_names_the_rows_the_poster_may_still_name(self):
        for state in ("claimed", "submitted"):
            said = words(state, **READY)
            self.assertIn("Every check passed on th", said)
            self.assertTrue(said.endswith(" MP-2 runs inside your own code or reads its configuration, so it is not "
                                          "independently verified: the poster may still send the work back naming "
                                          "it."), said)

    def test_only_black_box_passes_add_nothing(self):
        rows = [dict(READY["rows"][0]), dict(READY["rows"][0], id="MP-2")]
        self.assertNotIn("independently", words(**{**READY, "rows": rows}))
        old = [{k: v for k, v in r.items() if k != "independent"} for r in READY["rows"]]  # a stored reading
        self.assertNotIn("independently", words(**{**READY, "rows": old}))

    def test_two_rows_and_a_malformed_id(self):
        rows = READY["rows"] + [dict(READY["rows"][1], id="MP-3"), dict(READY["rows"][1], id="MP-3; rm -rf")]
        said = words(**{**READY, "rows": rows})
        self.assertIn(" MP-2, MP-3 run inside your own code or read its configuration, so they are not "
                      "independently verified: the poster may still send the work back naming one.", said)
        self.assertNotIn("rm -rf", said)

    def test_a_version_that_is_not_ready_says_nothing_of_it(self):
        failed = {**READY, "ready": False, "rows": [dict(READY["rows"][0], status="failed"), READY["rows"][1]]}
        self.assertNotIn("independently", words(**failed))

    def test_the_citation_refusal_names_influenceable_rows(self):
        self.assertIn("configuration can influence (not independently verified",
                      server._CODE_ACTIONS["rejection_needs_failing_row"])


if __name__ == "__main__":
    unittest.main()
