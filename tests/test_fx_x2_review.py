"""E-mcp-X2: payout truth and lane-aware actions at the mocked HTTP boundary."""
import unittest

from mergepaid_mcp import server
from tests.test_acceptance_loop import JOB, JUDGING, run
from tests.test_fx_e_qa import result, view
from tests.test_race_lanes import BOARD, JOB as RACE, WORK


class FinalReviewTests(unittest.TestCase):
    def test_submitted_share_is_potential_for_holders_and_other_racers(self):
        for assignment in ('you', 'other'):
            with self.subTest(assignment=assignment):
                reply = result(server.review_job, state='submitted', amount_usd=180, routes={
                    '/work-status':view('submitted', assignment, 'await_review'),
                    '/work':{'job_id':JOB['id'], 'work':None}})
                self.assertIn('is submitted. Potential payout: $153.00 to the winning racer after the 15% fee.', reply['summary'])
                self.assertNotIn('Recorded racer share', reply['summary'])
                self.assertFalse(reply['work_status']['can_start_bounty'])
                self.assertIn('do not verify Stripe transfer', reply['payment_note'])

    def test_only_merged_or_paid_jobs_describe_a_recorded_share(self):
        for state in ('draft', 'funded', 'open', 'claimed', 'submitted', 'merged', 'paid', 'rejected', 'expired'):
            with self.subTest(state=state):
                reply = result(server.review_job, state=state)
                self.assertEqual('Recorded racer share' in reply['summary'], state in ('merged', 'paid'))
                self.assertEqual(reply['net_payout_usd'], 85)

    def test_own_lane_review_uses_status_action_for_held_rival_and_still_racing_lanes(self):
        held = {'reason_code':'copy_check_pending', 'lane':1,
                'held_submissions':[{'lane':1, 'pr_url':'https://github.com/acme/api/pull/1'}]}
        for own_state, held_lane, expected in (
            ('submitted', 1, "Wait for the other lane's merge to settle; check job status later."),
            ('submitted', 2, 'Wait: it settles on its own once GitHub confirms, or the poster confirms the merge or sends the work back; nothing is needed from you.'),
            ('racing', 1, 'Your current job claim permits work on this job. Submit its pull request when ready; context, runtime and network permissions remain separate.'),
        ):
            with self.subTest(own_state=own_state, held_lane=held_lane):
                submitted = own_state == 'submitted'
                job = {**RACE, 'lane_board':[BOARD[0], {**BOARD[1], 'state':own_state, 'pr_submitted':submitted}],
                       'acceptance_hold':{**held, 'lane':held_lane,
                           'held_submissions':[{'lane':held_lane, 'pr_url':f'https://github.com/acme/api/pull/{held_lane}'}]}}
                work = {**WORK, 'can_start_bounty':not submitted, 'can_submit_pr':not submitted,
                        'submission_authority':'NONE' if submitted else 'CURRENT_HUMAN_CLAIM',
                        'next_action_code':'await_review' if submitted else 'submit_work',
                        'next_action':server.WORK_ACTIONS['await_review' if submitted else 'submit_work']}
                routes = {'/api/suppliers/me':{'id':'sup_bbbbbbbb'}, '/work-status':work,
                          '/judging':{**JUDGING, 'job_id':RACE['id'], 'acceptance_status':None},
                          '/work':{'job_id':RACE['id'], 'work':{'status':'submitted' if submitted else 'holding', 'lane':2}}}
                review = run(server.review_job, RACE['id'], job=job, routes=routes)[0]
                status = run(server.job_status, RACE['id'], job=job, routes=routes)[0]
                self.assertEqual(status['next_action'], expected)
                self.assertEqual(review['next_action'], expected)
                self.assertEqual(review['work_status']['next_action'], expected)
                self.assertEqual(review['work_status']['can_start_bounty'], not submitted)
                self.assertEqual(review['work_status']['can_submit_pr'], not submitted)
                self.assertEqual(review['work_status']['next_action_code'], work['next_action_code'])


if __name__ == '__main__':
    unittest.main()
