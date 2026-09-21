"""Authored wire responses; no provider, server or credentials are used."""
import inspect
import unittest
from copy import deepcopy
from unittest.mock import patch
from mergepaid_mcp import server

OID='seo_'+'a'*32
PACKET={'schema':'supplier-execution-status-v1','job_id':'job_fixture',
        'offers':[{'offer_id':OID,'phase':'generation','status':'queued','can_request':False}]}

class ExecutionRequests(unittest.TestCase):
    def test_explicit_request_is_one_post_and_no_owner_grant(self):
        calls=[]
        with patch.object(server,'TOKEN','authored-fixture'),patch.object(server,'_call',side_effect=lambda *a,**kw:(calls.append((a,kw)) or deepcopy(PACKET))):
            v=server.submit_work('job_fixture',execution_offer_id=OID,idempotency_key='intent:one')
        self.assertEqual(v['execution'],PACKET)
        self.assertEqual(calls,[(('POST','/api/local-supplier-execution/jobs/job_fixture/requests'),
            {'headers':{'Authorization':'Bearer authored-fixture','Idempotency-Key':'intent:one'},'json':{'offer_id':OID}})])
        self.assertNotIn('authored-fixture',str(v))

    def test_legacy_positional_pr_unchanged(self):
        calls=[]
        def backend(method,path,**kw):
            calls.append((method,path,kw))
            return {'credential':'private-fixture'} if path.endswith('credentials') else {'id':'job_fixture','state':'submitted','pr_url':'https://github.com/a/b/pull/1'}
        with patch.object(server,'TOKEN','authored-fixture'),patch.object(server,'_call',side_effect=backend):
            v=server.submit_work('job_fixture','https://github.com/a/b/pull/1')
        self.assertEqual(v['state'],'submitted')
        self.assertEqual([p for _,p,_ in calls],['/api/jobs/job_fixture/credentials','/api/jobs/job_fixture/submit'])
        self.assertEqual(calls[-1][2]['json'],{'pr_url':'https://github.com/a/b/pull/1'})

    def test_invalid_or_mixed_inputs_never_call(self):
        with patch.object(server,'TOKEN','fixture'),patch.object(server,'_call') as call:
            for kw in ({'execution_offer_id':OID}, {'execution_offer_id':OID,'idempotency_key':'x','pr_url':'x'},
                       {'execution_offer_id':OID+'\n','idempotency_key':'x'}, {'execution_offer_id':OID,'idempotency_key':'x\n'},
                       {'pr_url':'x','idempotency_key':'x'}):
                self.assertIn('error',server.submit_work('job_fixture',**kw))
            call.assert_not_called()

    def test_no_raw_private_fields_or_conflicting_status(self):
        for change in ('extra','wrong_job','duplicate','private','can','phase','newline'):
            p=deepcopy(PACKET)
            if change=='extra':p['grant_id']='crg_private'
            elif change=='wrong_job':p['job_id']='job_other'
            elif change=='duplicate':p['offers']*=2
            elif change=='private':p['offers'][0]['prompt']='private'
            elif change=='can':p['offers'][0]['can_request']=True
            elif change=='phase':p['offers'][0]['phase']='accept'
            else:p['offers'][0]['offer_id']+='\n'
            self.assertIsNone(server._execution_packet(p,'job_fixture'))

    def test_uncertain_response_never_repeats(self):
        with patch.object(server,'TOKEN','fixture'),patch.object(server,'_call',return_value={'error':'private transport diagnostic'}) as call:
            v=server.submit_work('job_fixture',execution_offer_id=OID,idempotency_key='x')
        self.assertEqual(call.call_count,1);self.assertIn('Do not repeat',v['next_action'])
        self.assertNotIn('private transport diagnostic',str(v))

    def test_six_tools_and_status_read_only(self):
        self.assertEqual(inspect.getsource(server).count('@mcp.tool('),6)
        with patch.object(server,'TOKEN','fixture'),patch.object(server,'_call',return_value=PACKET) as call:
            self.assertEqual(server._execution_status('job_fixture'),PACKET)
        self.assertEqual(call.call_args.args,('GET','/api/local-supplier-execution/jobs/job_fixture/offers'))

if __name__=='__main__':unittest.main()
