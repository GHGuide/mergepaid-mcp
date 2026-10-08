"""FX-E: reproduce the agent-side QA findings without a network or a server."""
import asyncio
import json
from copy import deepcopy
from unittest.mock import patch

import unittest
from functools import partial, update_wrapper
from mergepaid_mcp import server
from tests.test_acceptance_loop import ACCEPTANCE, HOLDER, JOB, JUDGING, STATUS, run


def cases(names, values):
    def decorate(test):
        test.cases = (names.split(','), values)
        return test
    return decorate


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, test in list(globals().items()):
        if not name.startswith('test_') or not callable(test):
            continue
        names, values = getattr(test, 'cases', ([], [()]))
        for value in values:
            args = value if len(names) != 1 else (value,)
            suite.addTest(unittest.FunctionTestCase(update_wrapper(partial(test, **dict(zip(names, args))), test),
                                                    description=f'{name}: {value}'))
    return suite


def view(state='open', assignment='unassigned', action='request_human_claim'):
    return {**HOLDER, 'job_state': state, 'assignment': assignment,
            'claim': {'status': 'active_for_you' if state == 'claimed' and assignment == 'you' else 'closed'},
            'can_start_bounty': state == 'claimed' and assignment == 'you',
            'next_action_code': action, 'next_action': server.WORK_ACTIONS[action]}


def result(tool, *, state='open', routes=None, **job):
    job = {**JOB, 'state': state, **job}
    return run(tool, job['id'], job=job,
               routes={'/work-status': view(state), **(routes or {})})[0]


def test_practice_recommendation_and_review_hide_every_dollar():
    practice = {**JOB, 'practice': True, 'title': 'Practice parser'}
    found = run(server.find_work, job=practice, routes={'/api/discovery/jobs': [practice]})[0]
    reviewed = result(server.review_job, practice=True, title='Practice parser')
    for reply in (found, reviewed):
        assert reply['summary'].startswith('Practice job: no payout')
        assert '$' not in json.dumps(reply)
    assert found['recommendation']['practice'] is True
    assert reviewed['practice'] is True
    assert reviewed['net_payout_usd'] is None
    # Older job payloads still have the proposed 85/15 split.
    assert result(server.review_job)['net_payout_usd'] == 85


def test_other_submitted_lane_does_not_inherit_the_held_merge():
    from tests.test_race_lanes import JOB as RACE, BOARD, WORK, call
    held = {'reason_code': 'copy_check_pending', 'lane': 1, 'pr_url': 'https://github.com/acme/api/pull/1'}
    board = [BOARD[0], {**BOARD[1], 'state': 'submitted', 'pr_submitted': True}]
    reply = call(server.job_status, 'job_race', job={**RACE, 'lane_board': board, 'acceptance_hold': held},
                 work={**WORK, 'can_start_bounty': False, 'next_action_code': 'await_review',
                       'next_action': server.WORK_ACTIONS['await_review'], 'can_submit_pr': False,
                       'submission_authority': 'NONE'})
    assert reply['summary'].startswith("Another lane's merge is being confirmed")
    assert 'your head' not in reply['summary']
    assert 'acceptance_hold' not in reply
    # The actual merged lane receives the hold; an old hold without an identity cannot prove it.
    for lane, expect in ((2, True), (None, False)):
        job = {**RACE, 'lane_board': board, 'acceptance_hold': {**held, 'lane': lane}}
        own = call(server.job_status, 'job_race', job=job)
        assert ('acceptance_hold' in own) is expect


@cases('tool', [server.review_job, server.job_status, server.claim_job])
def test_invalid_or_revoked_token_is_reported_as_token_error(tool):
    reply = result(tool, routes={'/work-status': {'error': 'Refused', 'status': 401, 'detail': 'invalid token'}})
    assert reply.get('status') == 401
    assert 'MERGEPAID_TOKEN' in reply['next_action']


@cases('tool', [server.review_job, server.job_status, server.claim_job, server.submit_work])
def test_malformed_id_has_one_correct_action_without_calls(tool):
    with patch.object(server, 'TOKEN', 'fixture'), patch.object(server, '_call') as api:
        reply = tool('bad id!')
    assert reply['next_action'] == 'Check the job ID.'
    api.assert_not_called()


@cases('state', ['submitted', 'merged', 'paid'])
def test_non_participant_never_hears_personal_entitlement(state):
    reply = result(server.job_status, state=state, routes={
        '/work-status': view(state, 'other', 'assigned_elsewhere')})
    assert 'another racer' in reply['summary'].lower()
    assert 'Local entitlement is recorded' not in reply['summary']
    assert 'your earnings' not in reply['next_action'].lower()


def test_ended_lane_relays_poster_reason_and_closed_next_step():
    from tests.test_race_lanes import JOB as RACE, BOARD, WORK, call
    mine = {'status': 'lost', 'lost_because': 'the poster ended your lane: No progress',
            'next_action': 'Find other work on the Market.'}
    def api(method, path, **kw):
        if path.endswith('/work'): return {'job_id': 'job_race', 'work': mine}
        if path.endswith('/work-status'): return {**WORK, 'job_state': 'claimed', 'can_start_bounty': False,
            'next_action_code': 'request_human_claim', 'next_action': server.WORK_ACTIONS['request_human_claim'],
            'assignment': 'unassigned', 'claim': {'status': 'none'}, 'can_submit_pr': False, 'submission_authority': 'NONE'}
        if path == '/api/suppliers/me': return {'id': 'sup_bbbbbbbb'}
        if path == '/api/jobs/job_race': return {**RACE, 'state': 'claimed', 'lane_board': [BOARD[0],
            {**BOARD[1], 'state': 'released'}]}
        return {}
    with patch.object(server, 'TOKEN', 'fixture'), patch.object(server, '_call', side_effect=api):
        reply = server.job_status('job_race')
    assert 'No progress' in reply['summary']
    assert reply['next_action'] == 'Find other work on the Market.'
    assert reply['claim_request'] is None


def test_rejection_summary_shows_reason_checks_and_hides_old_approval():
    mine = {'status': 'lost', 'rejection': {'reason': 'The total is wrong', 'row_ids': ['MP-1']},
            'lost_because': 'the poster sent it back', 'next_action': 'Find other work on the Market.'}
    reply = result(server.job_status, routes={'/work': {'job_id': JOB['id'], 'work': mine},
        '/claim-request': {'job_id': JOB['id'], 'status': 'approved', 'expires_at': '2099-01-01'}})
    assert reply['summary'] == 'The poster sent your work back: The total is wrong (checks: MP-1).'
    assert reply['claim_request'] is None
    assert reply['next_action'] == 'Find other work on the Market.'


def test_rotation_reason_is_relayed_without_blame():
    reply = result(server.job_status, routes={'/claim-request': {
        'job_id': JOB['id'], 'status': 'withdrawn', 'withdrawn_reason': 'credential_rotated', 'expires_at': '2099-01-01'}})
    assert reply['claim_request']['withdrawn_reason'] == 'credential_rotated'
    assert 'Withdrawn because your credential was replaced' in reply['summary']
    assert reply['next_action'] == 'Ask again with this credential.'


def test_money_has_commas_fixed_decimals_and_complete_sentences():
    reply = run(server.find_work, minimum_payout_usd=1000000, routes={'/api/discovery/jobs': []})[0]
    assert '$1,000,000.00' in reply['summary']
    assert reply['summary'].endswith('.')
    earned = run(server.my_earnings, routes={'/api/suppliers/me': {'balance_usd': 1542.75, 'paid_usd': 1542.75}})[0]
    assert '$1,542.75' in earned['summary']


@cases('unfunded,byline', [(True, 'Posted by MergePaid · Launch Pool'),
                                          (False, 'Posted & funded by MergePaid')])
def test_launch_pool_byline_tracks_funding(unfunded, byline):
    assert result(server.review_job, launch_pool=True, unfunded=unfunded)['byline'] == byline


def test_unfunded_does_not_infer_a_stripe_provider_or_synthetic_mode():
    reply = result(server.review_job, launch_pool=True, practice=True, unfunded=True)
    assert reply['funding_note'] == 'No provider funding is confirmed for this job.'
    assert reply['funding_mode'] is None


def test_specific_refusal_actions_survive_403_and_409():
    for status in (403, 409):
        reply = run(server.submit_work, JOB['id'], 'https://github.com/acme/widget/pull/7',
                    routes={'/credentials': {'error': 'Refused', 'status': status,
                                            'detail': 'Only the racer the poster approved can submit.'}})[0]
        assert 'approved' in reply['next_action']
    reply = run(server.claim_job, JOB['id'], routes={'/credentials': {'credential': 'fixture'},
        '/claim/request': {'error': 'Refused', 'status': 409,
                          'detail': "the poster declined this account's request for this job; find other work"}})[0]
    assert 'other work' in reply['next_action'].lower()
    assert 'state does not allow' not in reply['next_action']
    from tests.test_racer import run as racer_run, JOB as RACER_JOB, HOLDER as RACER_HOLDER
    early = racer_run(server.claim_job, RACER_JOB['id'], job={**RACER_JOB, 'state': 'claimed'},
        routes={'/work-status': RACER_HOLDER, '/credentials': {'credential': 'fixture'},
                '/claim/renew': {'error': 'Refused', 'status': 409, 'detail': 'too early'}})[0]
    assert 'when' in early['next_action'] and 'state does not allow' not in early['next_action']


def test_failing_check_has_same_primary_action_in_submit_and_status():
    failed = {**STATUS, 'rows': [{**STATUS['rows'][0], 'status': 'failed'}], 'ready': False}
    submitted = {**JOB, 'state': 'submitted', 'acceptance_status': failed}
    sent = run(server.submit_work, JOB['id'], 'https://github.com/acme/widget/pull/17',
        routes={'/credentials': {'credential': 'fixture'}, '/submit': submitted})[0]
    status = result(server.job_status, state='submitted', routes={
        '/work-status': view('submitted', 'you', 'await_review'),
        '/judging': {**JUDGING, 'acceptance_status': failed,
                     'your_submission': {'head_commit': failed['head_commit']}}})
    for reply in (sent, status):
        assert reply['next_action'] == 'Fix the failing check and push; the poster reviews after.'
        assert reply['acceptance_status']['next_action'].startswith(reply['next_action'])


@cases('settled', [False, True])
def test_failed_first_submission_respects_copy_review_or_hand_settlement(settled):
    failed = {**STATUS, 'rows': [{**STATUS['rows'][0], 'status': 'failed'}], 'ready': False}
    told = server._POT_SETTLED[1] if settled else (
        "The MergePaid founders compare this version with an earlier racer's ready work by hand before a "
        "merge of it can pay. Nothing is needed from you.")
    reply = run(server.submit_work, JOB['id'], 'https://github.com/acme/widget/pull/17', routes={
        '/submit': {**JOB, 'state': 'submitted', 'acceptance_status': failed},
        '/work': {'job_id': JOB['id'], 'work': {'next_action': told, 'pot_settled_by_hand': settled}}})[0]
    assert reply['next_action'] == told
    assert reply['acceptance_status']['next_action'] == told
    assert reply['warnings'] == [told]


@cases('tool,args', [(server.job_status, {'reply': '  '}),
                                      (server.submit_work, {'pr_url': 'https://github.com/acme/widget/pull/7', 'message': '  '})])
def test_whitespace_message_asks_for_words(tool, args):
    assert run(tool, JOB['id'], **args)[0]['next_action'] == 'Write a message.'


def test_change_request_without_evidence_does_not_mention_links():
    mine = {'status': 'holding', 'changes_open': True, 'change_requests': [{'message': 'Fix the total'}]}
    reply = result(server.job_status, state='claimed', routes={
        '/work-status': view('claimed', 'you', 'submit_work'), '/work': {'job_id': JOB['id'], 'work': mine}})
    assert 'same pull request' in reply['next_action']
    assert 'links' not in reply['next_action']


def test_long_protected_lists_are_bounded_and_point_to_full_kit():
    protected = {'judge': [f'path/{i}/**' for i in range(600)], 'amber': ['package.json'], 'may_edit': []}
    reply = result(server.review_job, routes={'/judging': {**JUDGING,
        'acceptance': {**ACCEPTANCE, 'protected': protected}}})
    assert len(json.dumps(reply)) < 12000
    assert len(reply['acceptance']['protected']['judge']) <= 5
    assert reply['acceptance']['protected_counts']['judge'] == 600
    assert 'full list in the kit' in reply['acceptance']['protected_note'].lower()


def test_own_job_is_left_out_of_recommendations_but_still_reviewable():
    own = {**JOB, 'own_job': True}
    other = {**JOB, 'id': 'job_other'}
    found = run(server.find_work, routes={'/api/discovery/jobs': [own, other]})[0]
    assert found['recommendation']['job_id'] == 'job_other'
    assert not found['alternatives']
    reviewed = result(server.review_job, routes={'/judging': {**JUDGING, 'own_job': True}})
    assert 'This is your own job.' in reviewed['summary']
    assert 'costs the 15% fee and earns no rep' in reviewed['summary']


def test_sealed_review_respects_practice_and_own_account_facts():
    reviewed = result(server.review_job, sealed=True, practice=True, routes={
        '/judging': {**JUDGING, 'own_job': True}})
    assert reviewed['summary'].startswith('Practice job: no payout')
    assert 'This is your own job.' in reviewed['summary']
    assert 'costs the 15% fee and earns no rep' in reviewed['summary']
    assert '$' not in json.dumps(reviewed)
    assert reviewed['gross_payout_usd'] is None and reviewed['net_payout_usd'] is None
    assert 'repo_url' not in reviewed and 'acceptance' not in reviewed and 'bundle' not in reviewed


def test_tool_schema_describes_existing_parameters_and_enum_choices():
    schemas = {t.name: t.input_schema for t in asyncio.run(server.mcp.list_tools())}
    assert len(schemas) == 8
    for schema in schemas.values():
        for prop in schema['properties'].values():
            assert prop.get('description')
    assert 'python' in json.dumps(schemas['find_work']['properties']['languages'])
    assert 'criteria_conflict' in json.dumps(schemas['submit_work']['properties']['blocker_code'])
    assert '{row, url}' in schemas['submit_work']['properties']['evidence']['description']


def test_cancelled_participant_review_and_status_use_authenticated_closure():
    def api(method, path, **kw):
        if path == '/api/jobs/job_cancelled':
            return {'id': 'job_cancelled', 'state': 'cancelled', 'title': 'Closed job'} if kw.get('headers') else {
                'error': 'Refused', 'status': 404}
        if path.endswith('/work-status'):
            return {**view('cancelled', 'unassigned', 'closed'), 'job_id': 'job_cancelled'}
        if path.endswith('/execution-policy'):
            return {'error': 'Refused', 'status': 404}
        return {}
    with patch.object(server, 'TOKEN', 'fixture'), patch.object(server, '_call', side_effect=api):
        for tool in (server.review_job, server.job_status):
            reply = tool('job_cancelled')
            assert reply.get('state') == 'cancelled'
            assert 'cancelled' in reply['summary']
            assert reply['work_authorization'] == 'not_authorized_to_start'


def test_refusals_stay_normal_results_and_pending_request_does_not_invent_withdraw_ui():
    reply = run(server.submit_work, JOB['id'], blocker_code='unknown')[0]
    assert 'error' in reply and 'next_action' in reply
    pending = run(server.claim_job, JOB['id'], routes={'/claim/request': {
        'approval_delivery': 'poster_account', 'expires_at': '2099-01-01', 'deduplicated': True}})[0]
    assert pending['claimed'] is False and pending['already_requested'] is True
    assert 'withdraw' not in pending['next_action'].lower()


def test_product_words_replace_legacy_backend_actions_and_language_case_still_works():
    legacy = {**view('claimed', 'you', 'submit_work'),
              'next_action': 'Your current bounty claim permits work on this bounty. Submit its pull request when ready; context, runtime and network permissions remain separate.'}
    reply = result(server.job_status, state='claimed', routes={'/work-status': legacy})
    assert 'bounty claim' not in json.dumps(reply)
    found = run(server.find_work, languages=[' Python '], routes={'/api/discovery/jobs': [JOB]})[0]
    assert found['recommendation'] is not None
