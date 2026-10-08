"""Round-2 MCP regressions, with only the HTTP boundary replaced."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import JOB, JUDGING, run
from tests.test_fx_e_qa import result, view


class RoundTwoTests(unittest.TestCase):
    def test_declined_status_keeps_the_poster_reason_without_a_live_claim(self):
        request = {'job_id': JOB['id'], 'status': 'declined', 'reason': 'Not this time',
                   'expires_at': '2099-01-01', 'decided_at': '2026-10-01'}
        mine = {'status': 'lost', 'lost_because': 'the poster declined the request',
                'request': request, 'next_action': 'Find other work on the Market.'}
        for state in ('open', 'claimed'):
            with self.subTest(state=state):
                reply = result(server.job_status, state=state, routes={
                    '/claim-request': request, '/work': {'job_id': JOB['id'], 'work': mine}})
                self.assertIn('Not this time', reply['summary'])
                self.assertEqual(reply['claim_request']['poster_reason'], 'Not this time')
                self.assertEqual(reply['claim_request']['status'], 'declined')
                self.assertEqual(reply['next_action'], 'Find other work on the Market.')
                self.assertEqual(reply['work_authorization'], 'not_authorized_to_start')

    def test_closed_work_has_one_action_in_review_and_status(self):
        for tool in (server.review_job, server.job_status):
            for why in ('the poster declined the request', 'the poster sent it back',
                        'another lane won the pot'):
                with self.subTest(tool=tool.__name__, why=why):
                    mine = {'status': 'lost', 'lost_because': why,
                            'next_action': 'Find other work on the Market.'}
                    reply = result(tool, routes={'/work': {'job_id': JOB['id'], 'work': mine}})
                    self.assertEqual(reply['next_action'], 'Find other work on the Market.')
                    self.assertEqual(reply['work_status']['next_action'], reply['next_action'])
                    self.assertFalse(reply['work_status']['can_start_bounty'])

    def test_decline_refusal_gives_an_unconditional_next_action(self):
        reply = run(server.claim_job, JOB['id'], routes={
            '/claim/request': {'error': 'Refused', 'status': 409,
                              'detail': "the poster declined this account's request for this job; find other work"}})[0]
        self.assertEqual(reply['next_action'], 'Find other work on the Market.')
        self.assertEqual(reply['status'], 409)
        self.assertIn('declined', reply['refusal_reason'])
        other = run(server.claim_job, JOB['id'], routes={
            '/claim/request': {'error': 'Refused', 'status': 409, 'detail': 'No lane is free'}})[0]
        self.assertIn('status', other['next_action'])

    def test_own_job_warning_explains_the_fee_and_no_rep(self):
        for sealed in (False, True):
            with self.subTest(sealed=sealed):
                reply = result(server.review_job, sealed=sealed, routes={
                    '/judging': {**JUDGING, 'own_job': True}})
                self.assertIn('Paying your own racer only moves money between your own accounts, '
                              'costs the 15% fee and earns no rep.', reply['summary'])
                self.assertNotIn('pays nothing', reply['summary'])
                self.assertEqual(reply['net_payout_usd'], 85)

    def test_self_merge_hold_does_not_tell_the_racer_to_change_authors(self):
        reply = result(server.job_status, state='submitted', acceptance_hold={
            'reason_code': 'authorship_mismatch', 'self_merged': True}, routes={
                '/work-status': view('submitted', 'you', 'await_review')})
        self.assertIn('author merged it', reply['summary'])
        self.assertEqual(reply['next_action'],
                         'Wait for the poster to confirm the self-merge or send the work back; nothing is needed from you.')
        self.assertNotIn('Submit pull requests opened', reply['next_action'])

    def test_referee_labels_use_the_racer_voice_on_every_card(self):
        job = {**JOB, 'referee': {**JOB['referee'], 'label': 'Merged into your repository'}}
        for tool, args in ((server.find_work, ()), (server.review_job, (JOB['id'],)),
                           (server.claim_job, (JOB['id'],))):
            with self.subTest(tool=tool.__name__):
                reply = run(tool, *args, job=job, routes={'/api/discovery/jobs': [job]})[0]
                card = reply.get('recommendation') or reply
                self.assertEqual(card['referee']['label'], "Merged into the poster's repository")

    def test_lost_lane_never_reports_the_winners_pull_request(self):
        from tests.test_race_lanes import JOB as RACE, BOARD
        winner = 'https://github.com/acme/api/pull/1'
        own = 'https://github.com/acme/api/pull/2'
        board = [{**BOARD[0], 'state': 'won'},
                 {**BOARD[1], 'state': 'lost', 'pr_submitted': True}]
        work = {**view('paid', 'other', 'assigned_elsewhere'), 'job_id': RACE['id']}
        for submission, expected in ((None, None), ({'pr_url': own}, own)):
            with self.subTest(submission=submission):
                reply = run(server.job_status, RACE['id'], job={**RACE, 'state': 'paid',
                    'lane_board': board, 'pr_url': winner}, routes={
                        '/api/suppliers/me': {'id': 'sup_bbbbbbbb'}, '/work-status': work,
                        '/judging': {**JUDGING, 'job_id': RACE['id'], 'your_submission': submission,
                                     'acceptance_status': None}})[0]
                self.assertEqual(reply['pr_url'], expected)
                self.assertNotEqual(reply['pr_url'], winner)

    def test_closed_and_taken_jobs_do_not_offer_a_new_payout(self):
        for state in ('claimed', 'submitted', 'merged', 'paid', 'rejected', 'expired'):
            with self.subTest(state=state):
                reply = result(server.review_job, state=state)
                self.assertNotIn('offers a potential payout', reply['summary'])
                self.assertIn(state, reply['summary'])
                self.assertEqual(reply['net_payout_usd'], 85)
        self.assertIn('offers a potential payout', result(server.review_job)['summary'])


if __name__ == '__main__':
    unittest.main()
