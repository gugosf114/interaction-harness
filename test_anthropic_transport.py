import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import anthropic
import httpx2 as httpx
from anthropic_transport import complete_message


class Stream:
    def __init__(self, message, error=None):
        self.message=message; self.error=error; self.closed=False; self.consumed=False
    def __enter__(self): return self
    def __exit__(self,*args): self.closed=True
    def get_final_message(self):
        self.consumed=True
        if self.error: raise self.error
        return self.message


class Endpoint:
    def __init__(self, stream): self.result=stream; self.params=None
    def stream(self,**params): self.params=params; return self.result
    def create(self,**params): raise AssertionError('A streamed request must not be repeated.')


class BufferedStreamTests(unittest.TestCase):
    def test_complete_message_and_usage_are_preserved_without_printing(self):
        message=SimpleNamespace(stop_reason='tool_use',content=[{'type':'tool_use','name':'emit_reply','input':{'intent':'observation','cleaned_input':'x','direct_answer':'Answer.','execution_payload':None}}],usage={'input_tokens':9,'cache_read_input_tokens':7,'output_tokens':2})
        stream=Stream(message);endpoint=Endpoint(stream)
        params={'model':'claude-opus-5-5','max_tokens':128000,'messages':[{'role':'user','content':'x'}],'cache_control':{'type':'ephemeral'}}
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            result=complete_message(endpoint,**params)
        self.assertIs(result,message)
        self.assertEqual(endpoint.params,params)
        self.assertTrue(stream.consumed and stream.closed)
        self.assertEqual(stdout.getvalue(),'')

    def test_beta_arguments_stay_exact(self):
        endpoint=Endpoint(Stream(SimpleNamespace(stop_reason='pause_turn')))
        complete_message(endpoint,betas=['context-management-2025-06-27'],tools=[{'type':'code_execution_20260521'}])
        self.assertEqual(endpoint.params['betas'],['context-management-2025-06-27'])
        self.assertEqual(endpoint.params['tools'],[{'type':'code_execution_20260521'}])

    def test_partial_stream_is_rejected_and_closed(self):
        stream=Stream(SimpleNamespace(stop_reason=None,content=['partial JSON']))
        with self.assertRaises(anthropic.APIConnectionError):complete_message(Endpoint(stream),model='x')
        self.assertTrue(stream.closed)

    def test_stream_error_does_not_start_another_request(self):
        error=anthropic.APIConnectionError(request=httpx.Request('POST','https://api.anthropic.com/v1/messages'))
        stream=Stream(None,error)
        with self.assertRaises(anthropic.APIConnectionError):complete_message(Endpoint(stream),model='x')
        self.assertTrue(stream.closed)

    def test_real_sdk_accumulates_tool_json_and_cache_usage(self):
        import json
        reply={'intent':'observation','cleaned_input':'x','direct_answer':'Answer.','execution_payload':None}
        events=[
            {'type':'message_start','message':{'id':'msg_unit','type':'message','role':'assistant','model':'claude-opus-5-5','content':[],'stop_reason':None,'stop_sequence':None,'usage':{'input_tokens':9,'output_tokens':1,'cache_read_input_tokens':7}}},
            {'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'tool_unit','name':'emit_reply','input':{}}},
            {'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':json.dumps(reply)}},
            {'type':'content_block_stop','index':0},
            {'type':'message_delta','delta':{'stop_reason':'tool_use','stop_sequence':None},'usage':{'output_tokens':20}},
            {'type':'message_stop'},
        ]
        wire=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
        requests=[]
        def transport(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=wire)
        with anthropic.Anthropic(api_key='unit-test',http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                results=[complete_message(endpoint,model='claude-opus-5-5',max_tokens=128000,system='Frozen prefix',messages=[{'role':'user','content':'x'}],**extra) for endpoint,extra in [(client.messages,{}),(client.beta.messages,{'betas':['context-management-2025-06-27']})]]
        for result in results:
            self.assertEqual(result.content[0].input,reply)
            self.assertEqual(result.usage.cache_read_input_tokens,7)
            self.assertEqual(result.usage.output_tokens,20)
            self.assertEqual(result.stop_reason,'tool_use')
        self.assertEqual(output.getvalue(),'')
        self.assertEqual(len(requests),2)
        self.assertTrue(all(request['stream'] for request in requests))
        self.assertTrue(all(request['system']=='Frozen prefix' for request in requests))

    def test_empty_real_sdk_stream_is_a_connection_error(self):
        transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=b''))
        with anthropic.Anthropic(api_key='unit-test',http_client=httpx.Client(transport=transport)) as client:
            with self.assertRaises(anthropic.APIConnectionError):
                complete_message(client.messages,model='claude-opus-5-5',max_tokens=128000,messages=[{'role':'user','content':'x'}])

    def test_create_only_fake_and_mock_adapters_still_work(self):
        for endpoint in [SimpleNamespace(create=Mock(return_value='complete')), Mock()]:
            endpoint.create.return_value='complete'
            self.assertEqual(complete_message(endpoint,model='x'),'complete')
            endpoint.create.assert_called_once_with(model='x')

if __name__=='__main__':unittest.main()
