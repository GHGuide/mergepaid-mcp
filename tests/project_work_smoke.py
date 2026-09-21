"""Real stdio/loopback project seam with entirely synthetic identities/evidence.

Run from any directory with mcp/.venv/bin/python. Requires the already-installed
backend .venv; installs nothing. Owns only two MCP children, one backend child and
its temporary database. No candidate code, model or external provider is executed.
"""
import asyncio
from collections import Counter
from contextlib import AsyncExitStack
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile

import httpx
from mcp import Client, StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[2]
TOOLS = {'find_work', 'review_job', 'claim_job', 'submit_work', 'job_status', 'my_earnings'}
WORK_FIELDS = {'schema', 'job_id', 'job_state', 'assignment', 'project', 'claim',
    'can_start_bounty', 'next_action_code', 'next_action', 'authority_scope', 'functional_completion', 'can_submit_pr', 'submission_authority'}


class SmokeFailure(Exception):
    pass


class ObservedSession:
    """Metadata for returned JSON only; never retain or print raw fixture text."""
    def __init__(self, client, ordinal):
        self.client, self.ordinal, self.returned = client, ordinal, []

    async def call_tool(self, name, arguments, **options):
        response = await self.client.call_tool(name, arguments, **options)
        require(bool(response.content) and len(response.content[0].text.encode()) <= 65536, 'invalid_mcp_envelope')
        value = json.loads(response.content[0].text)
        require(type(value) is dict, 'invalid_mcp_payload')
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
        self.returned.append({'sequence': len(self.returned)+1, 'tool': name,
            'canonical_payload_bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest()})
        return response

    def receipt(self):
        return {'supplier_ordinal': self.ordinal, 'tool_call_count': len(self.returned),
            'tool_counts': dict(sorted(Counter(item['tool'] for item in self.returned).items())),
            'canonical_returned_payload_bytes': sum(item['canonical_payload_bytes'] for item in self.returned),
            'returned_payloads': self.returned}


def require(condition, code):
    if not condition: raise SmokeFailure(code)


def child_environment():
    # No inherited provider credentials, proxy endpoints, production database or
    # session configuration. PATH is needed only for the installed Python runtime.
    return {'PATH': os.defpath, 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'ALL_PROXY': '', 'NO_PROXY': '127.0.0.1,localhost'}


async def request(client, method, path, body=None, *, expected=200, key=None, headers=None, content=None):
    options = {'headers': dict(headers or {})}
    if key is not None: options['headers']['Idempotency-Key'] = key
    if content is not None: options['content'] = content
    elif body is not None: options['json'] = body
    response = await client.request(method, path, **options)
    require(response.status_code == expected, 'unexpected_local_http_status_' + str(response.status_code) + '_expected_' + str(expected))
    require(len(response.content) <= 1024*1024, 'oversized_local_response')
    if expected in (302, 404, 409): return None
    return response.json()


async def tool(client, name, job=None):
    response = await client.call_tool(name, {} if job is None else {'job_id': job}, read_timeout_seconds=10)
    require(bool(response.content) and len(response.content[0].text.encode()) <= 65536, 'invalid_mcp_envelope')
    value = json.loads(response.content[0].text)
    require(type(value) is dict, 'invalid_mcp_payload')
    return value


def status(value, job, *, start, project, assignment):
    packet = value.get('work_status')
    require(type(packet) is dict and set(packet) == WORK_FIELDS, 'missing_or_private_work_packet')
    require(set(packet['project']) == {'status', 'dependencies'} and set(packet['claim']) == {'status'}, 'unexpected_work_packet_fields')
    require(packet['schema'] == 'supplier-job-work-v2' and packet['job_id'] == job, 'wrong_work_packet_identity')
    require(packet['authority_scope'] == 'MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY', 'wrong_authority_scope')
    require(packet['can_start_bounty'] is start and packet['project']['status'] == project
        and packet['assignment'] == assignment, 'incorrect_project_work_authority')
    require(value['work_authorization'] == ('current_human_claim' if start else 'not_authorized_to_start'), 'incorrect_mcp_authority_label')
    if start:
        require(packet['claim']['status'] == 'active_for_you' and packet['project']['dependencies'] == 'ready'
            and 'permissions remain separate' in value['next_action'], 'claim_scope_not_preserved')
    return packet


def task(name, deps=(), revision='v1'):
    return {'id': name, 'revision': revision, 'depends_on': list(deps), 'write_scopes': ['src/' + name]}


async def exercise(api, secret, backend_process):
    owner_options = {'base_url': api, 'trust_env': False, 'timeout': 10,
        'headers': {'Origin': 'http://localhost:8401'}, 'follow_redirects': False}
    async with httpx.AsyncClient(**owner_options) as owner, httpx.AsyncClient(base_url=api, trust_env=False, timeout=10) as public:
        for _ in range(100):
            require(backend_process.poll() is None, 'backend_stopped_before_health')
            try:
                health = await public.get('/api/health')
                if health.status_code == 200: break
            except httpx.TransportError: pass
            await asyncio.sleep(0.05)
        else: raise SmokeFailure('backend_health_timeout')
        await request(owner, 'GET', '/api/auth/github/login?as=project-mcp-synthetic-owner', expected=302)
        suppliers = [await request(public, 'POST', '/api/suppliers', {'name': 'Synthetic seam supplier ' + str(n)}) for n in (1, 2)]
        require(suppliers[0]['id'] != suppliers[1]['id'], 'supplier_identity_collision')
        parent = (await request(owner, 'POST', '/api/projects', {'title': 'Synthetic seam',
            'objective': 'Exercise a private coordination boundary', 'criteria': 'Synthetic smoke only'}, expected=201, key='create'))['project']
        project_path = '/api/projects/' + parent['id']
        tasks = [task('prerequisite'), task('dependent', ['prerequisite']), task('independent')]
        specs = [{**item, 'job': {'title': 'Synthetic ' + item['id'], 'description': 'Inert fixture work',
            'repo_url': 'https://github.com/acme/widget', 'criteria': 'Synthetic fixture condition', 'amount_usd': 10}} for item in tasks]
        parent = (await request(owner, 'POST', project_path + '/proposals', {'brief_id': parent['brief']['id'],
            'expected_generation': parent['generation'], 'tasks': specs}, key='proposal'))['project']
        materialized = await request(owner, 'POST', project_path + '/materializations', {'brief_id': parent['brief']['id'],
            'plan_id': parent['current_plan_id'], 'expected_generation': parent['generation']}, key='materialize')
        jobs = {item['task_id']: item['job_id'] for item in materialized['record']['mappings']}

        async def activate(name):
            current = await request(owner, 'GET', project_path)
            bound = await request(owner, 'POST', project_path + '/bindings', {'task_id': name, 'job_id': jobs[name],
                'expected_generation': current['generation']}, key='activate:' + name)
            await request(owner, 'POST', '/api/jobs/' + jobs[name] + '/fund', {})
            return bound['record']['id']

        async def approve(client, name):
            job = jobs[name]
            asked = await tool(client, 'claim_job', job)
            require(asked.get('claimed') is False and asked.get('approval_delivery') == 'poster_account'
                and 'approve_url' not in asked and 'claim_token' not in asked, 'supplier_received_claim_approval')
            status(await tool(client, 'job_status', job), job, start=False, project='current', assignment='unassigned')
            notifications = await request(owner, 'GET', '/api/notifications')
            notice = next((item for item in notifications if item['job_id'] == job and item['type'] == 'claim_requested'), None)
            require(notice is not None, 'owner_approval_notification_missing')
            await request(owner, 'POST', '/api/jobs/' + job + '/claim/approve', {'request_id': notice['data']['approval_request_id']})
            status(await tool(client, 'job_status', job), job, start=True, project='current', assignment='you')

        prerequisite_binding = await activate('prerequisite')
        await activate('independent')
        async with AsyncExitStack() as stack:
            error_sink = stack.enter_context(open(os.devnull, 'w'))
            sessions = []
            for supplier in suppliers:
                env = {**child_environment(), 'MERGEPAID_API': api, 'MERGEPAID_TOKEN': supplier['api_token']}
                params = StdioServerParameters(command=sys.executable, args=['-m', 'mergepaid_mcp.server'], env=env, cwd=str(ROOT / 'mcp'))
                client = await stack.enter_async_context(Client(stdio_client(params, errlog=error_sink), raise_exceptions=True))
                require({item.name for item in (await client.list_tools()).tools} == TOOLS, 'supplier_tool_count_changed')
                sessions.append(ObservedSession(client, len(sessions)+1))
            first, second = sessions
            await request(public, 'GET', '/api/jobs/' + jobs['dependent'] + '/work-status', expected=404,
                headers={'Authorization': 'Bearer ' + suppliers[0]['api_token']})
            await request(owner, 'POST', '/api/jobs/' + jobs['dependent'] + '/fund', {}, expected=409)
            hidden = await tool(first, 'review_job', jobs['dependent'])
            require('error' in hidden and not hidden.get('work_status'), 'unactivated_reservation_exposed')
            for client in sessions:
                status(await tool(client, 'review_job', jobs['prerequisite']), jobs['prerequisite'], start=False,
                    project='current', assignment='unassigned')
            await approve(first, 'prerequisite')
            status(await tool(second, 'job_status', jobs['prerequisite']), jobs['prerequisite'], start=False, project='current', assignment='other')

            pr_url = 'https://github.com/acme/widget/pull/77'
            submitted = await first.call_tool('submit_work', {'job_id': jobs['prerequisite'], 'pr_url': pr_url}, read_timeout_seconds=10)
            require(json.loads(submitted.content[0].text).get('state') == 'submitted', 'synthetic_pr_not_recorded')
            await request(owner, 'POST', '/api/jobs/' + jobs['prerequisite'] + '/repository-binding/authorize',
                {'installation_id': 456, 'repository_id': 123, 'repository': 'acme/widget'})
            for action, merged in (('opened', False), ('closed', True)):
                payload = {'action': action, 'pull_request': {'html_url': pr_url, 'merged': merged, 'number': 77,
                    'base': {'sha': 'a'*40, 'repo': {'full_name': 'acme/widget', 'id': 123}},
                    'head': {'sha': 'b'*40, 'repo': {'full_name': 'supplier/widget-fork', 'id': 789}},
                    'merge_commit_sha': 'c'*40}, 'repository': {'full_name': 'acme/widget', 'id': 123}, 'installation': {'id': 456}}
                encoded = json.dumps(payload, separators=(',', ':')).encode()
                await request(public, 'POST', '/api/webhooks/github', content=encoded, headers={
                    'Content-Type': 'application/json', 'X-GitHub-Event': 'pull_request', 'X-GitHub-Delivery': 'synthetic-project-mcp-' + action,
                    'X-Hub-Signature-256': 'sha256=' + hmac.new(secret.encode(), encoded, hashlib.sha256).hexdigest()})
            current = await request(owner, 'GET', project_path)
            captured = await request(owner, 'POST', project_path + '/attempts/capture', {'binding_id': prerequisite_binding,
                'expected_generation': current['generation']}, key='capture-prerequisite')
            require(captured['record']['qualifies'] is True, 'synthetic_prerequisite_capture_unqualified')
            await activate('dependent')
            await approve(first, 'dependent'); await approve(second, 'independent')
            status(await tool(second, 'job_status', jobs['dependent']), jobs['dependent'], start=False, project='current', assignment='other')
            status(await tool(first, 'job_status', jobs['independent']), jobs['independent'], start=False, project='current', assignment='other')
            current = await request(owner, 'GET', project_path)
            await request(owner, 'POST', project_path + '/plans', {'expected_generation': current['generation'],
                'tasks': [task('prerequisite', revision='v2'), tasks[1], tasks[2]]}, key='revise-prerequisite')
            stale = status(await tool(first, 'job_status', jobs['dependent']), jobs['dependent'], start=False, project='stale', assignment='you')
            require(stale['project']['dependencies'] == 'blocked', 'dependency_revision_not_blocking')
            status(await tool(first, 'review_job', jobs['dependent']), jobs['dependent'], start=False, project='stale', assignment='you')
            status(await tool(second, 'job_status', jobs['independent']), jobs['independent'], start=True, project='current', assignment='you')
            status(await tool(second, 'review_job', jobs['independent']), jobs['independent'], start=True, project='current', assignment='you')
            # Inspect only the minimized packet for cross-job private references.
            serialized = json.dumps(stale)
            require(all(value not in serialized for value in (parent['id'], prerequisite_binding, jobs['prerequisite'], jobs['independent'],
                suppliers[0]['api_token'], suppliers[1]['api_token'])), 'private_reference_in_work_packet')
        return {'schema': 'synthetic-project-mcp-smoke-v1', 'result': 'passed',
            'evidence_kind': 'synthetic_development_transport_observation',
            'transport': 'real_stdio_real_loopback_backend', 'supplier_count': 2, 'supplier_tools_per_session': 6,
            'simulated_owner_approvals': 3, 'synthetic_signed_provider_events': 2,
            'unactivated_reservation_denied': True, 'unassigned_start_denied': True, 'other_supplier_start_denied': True,
            'dependency_revision_blocks_work': True, 'unchanged_independent_work_remains_usable': True,
            'authority_scope': 'MARKETPLACE_CLAIM_AND_SUBMISSION_ONLY', 'mcp_sessions_closed': 2,
            'real_human_approval': False, 'external_provider_calls': 0, 'model_calls': 0,
            'patch_execution': False, 'real_money': False,
            'supplier_observations': [session.receipt() for session in sessions],
            'byte_scope': 'canonical_returned_tool_json_only', 'total_information_disclosure_measured': False,
            'human_effort_measured': False, 'context_ledger_covers_all_mcp_information': False}


def main():
    backend_python = ROOT / '.venv/bin/python'
    require(backend_python.is_file(), 'backend_virtualenv_missing')
    receipt, backend_stopped = None, False
    with tempfile.TemporaryDirectory(prefix='mergepaid-project-mcp-') as directory:
        secret = secrets.token_urlsafe(40)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(128)
            api = 'http://127.0.0.1:' + str(listener.getsockname()[1])
            env = {**child_environment(), 'PYTHONPATH': str(ROOT), 'MERGEPAID_DB': str(Path(directory) / 'fixture.sqlite'),
                'PUBLIC_BASE_URL': api, 'OAUTH_STUB': '1', 'SESSION_SECRET': secrets.token_urlsafe(40), 'GITHUB_WEBHOOK_SECRET': secret}
            backend = subprocess.Popen([str(backend_python), '-m', 'uvicorn', 'backend.app:app', '--fd', str(listener.fileno()),
                '--log-level', 'critical', '--no-access-log'], cwd=ROOT, env=env, pass_fds=(listener.fileno(),),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            async def bounded(): return await asyncio.wait_for(exercise(api, secret, backend), timeout=120)
            receipt = asyncio.run(bounded())
        finally:
            was_running = backend.poll() is None
            if was_running:
                backend.terminate()
                try: backend.wait(timeout=5)
                except subprocess.TimeoutExpired: backend.kill(); backend.wait(timeout=5)
            backend_stopped = backend.poll() is not None
            require(backend_stopped, 'owned_backend_cleanup_unconfirmed')
            if receipt is not None:
                require(was_running and backend.returncode in (0, -signal.SIGTERM), 'unexpected_backend_exit_status')
    receipt.update(backend_reaped=backend_stopped, temporary_database_removed=not Path(directory).exists())
    print(json.dumps(receipt, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try: main()
    except SmokeFailure as error:
        print(json.dumps({'schema': 'synthetic-project-mcp-smoke-v1', 'result': 'failed', 'code': str(error)}))
        sys.exit(1)
    except KeyboardInterrupt:
        print(json.dumps({'schema': 'synthetic-project-mcp-smoke-v1', 'result': 'interrupted'})); sys.exit(130)
    except BaseException:
        # Never echo HTTP bodies, child output, private fixture text or credentials.
        print(json.dumps({'schema': 'synthetic-project-mcp-smoke-v1', 'result': 'failed', 'code': 'unexpected_smoke_failure'}))
        sys.exit(1)
