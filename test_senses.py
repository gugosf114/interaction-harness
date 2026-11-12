"""Provider-shaped web receipts, provenance gates, attachments and CLI storage."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import harness as h
import cli
import attachments as a
from lookup_gate import violation,source_block,turn_metadata
from senses import tool_list
from senses_fixtures import create
from storage import Store,history_messages
from test_harness import document,FakeClient,response

U='https://example.com'


def oa_web(answer='The page title is Example Domain.',kind='search',count=1):
    r=response(document(direct_answer=answer))
    action={'type':kind,'url':U,'sources':[{'url':U,'title':'Example Domain'}]}
    r.output=[NS(type='web_search_call',id='lookup'+str(i),status='completed',action=action) for i in range(count)]+r.output
    return r


def ac(content=None,stop='tool_use',answer='The page title is Example Domain.'):
    blocks=[] if content is None else copy.deepcopy(content)
    if stop=='tool_use':blocks.append({'type':'tool_use','id':'final-tool','name':'emit_reply','input':json.loads(document(direct_answer=answer))})
    return NS(id='claude-response',model=h.ANTHROPIC_MODEL,stop_reason=stop,
              usage=NS(model_dump=lambda **_:{'input_tokens':40,'output_tokens':20,'cache_read_input_tokens':100,'server_tool_use':{'web_search_requests':sum(b.get('name')=='web_search' for b in blocks)}}),
              content=[NS(**b) for b in blocks])


def search_blocks(error=None):
    return [{'type':'server_tool_use','id':'search-1','name':'web_search','input':{'query':'example'}},
            {'type':'web_search_tool_result','tool_use_id':'search-1','content':
             {'type':'web_search_tool_result_error','error_code':error} if error else
             [{'type':'web_search_result','url':U,'title':'Example Domain','encrypted_content':'opaque'}]}]


class SensesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.log=self.root/'usage';self.patch=patch.object(h,'STATE',self.root/'state');self.patch.start()
        self.fixtures=create(self.root)

    def tearDown(self):self.patch.stop();self.tmp.cleanup()

    def ask(self,engine,replies,query='Explain the page.',**kw):
        client=FakeClient(replies);client.messages=client
        events=[]
        reply=h.request_reply(query,engine=engine,client=client,events=events,log_path=self.log,**kw)
        return reply,client,events

    def test_search_for_each_provider_records_sources(self):
        for engine,raw in [('openai',oa_web()),('anthropic',ac(search_blocks()))]:
            with self.subTest(engine=engine):
                _,_,events=self.ask(engine,[raw]);meta=turn_metadata(events)
                self.assertEqual(meta['lookup_counts']['search'],1)
                self.assertEqual(meta['sources'],[{'url':U,'title':'Example Domain'}])

    def test_no_search_for_each_provider(self):
        for engine,raw in [('openai',response()),('anthropic',ac())]:
            _,_,events=self.ask(engine,[raw]);meta=turn_metadata(events)
            self.assertEqual(meta['lookup_counts']['total'],0);self.assertEqual(meta['sources'],[])

    def test_pause_turn_sends_all_content_back_unchanged(self):
        blocks=[{'type':'thinking','thinking':'short reasoning','signature':'signed-value'},*search_blocks()]
        first=ac(blocks,stop='pause_turn');last=ac(answer='The page is Example Domain.')
        _,client,events=self.ask('anthropic',[first,last])
        content=client.calls[1]['messages'][-1]['content']
        self.assertEqual(content,blocks)
        self.assertEqual(client.calls[0]['tools'],client.calls[1]['tools'])
        self.assertEqual(events[-1]['usage']['input_tokens'],80)
        self.assertEqual(events[-1]['lookup_counts']['total'],1)

    def test_http_200_lookup_error_blocks_answer(self):
        client=FakeClient([ac(search_blocks('unavailable'))]);client.messages=client
        with self.assertRaisesRegex(h.HarnessError,'unavailable'):
            h.request_reply('Search.',engine='anthropic',client=client,log_path=self.log)
        self.assertEqual(len(client.calls),1)
        self.assertEqual(json.loads(self.log.read_text())['lookup_counts']['total'],1)

    def test_paused_lookup_failure_is_returned_to_model_before_stopping(self):
        failure=search_blocks('unavailable')
        client=FakeClient([ac(failure,stop='pause_turn'),ac()]);client.messages=client
        with self.assertRaisesRegex(h.HarnessError,'unavailable'):
            h.request_reply('Search.',engine='anthropic',client=client,log_path=self.log)
        self.assertEqual(client.calls[1]['messages'][-1]['content'],failure)

    def test_pending_server_tool_is_not_mistaken_for_a_completed_lookup(self):
        blocks=search_blocks()
        first=ac(blocks[:1]);second=ac(blocks[1:])
        _,client,events=self.ask('anthropic',[first,second])
        self.assertEqual(len(client.calls),2)
        self.assertEqual(client.calls[1]['messages'][-1]['content'][0]['type'],'tool_result')
        self.assertTrue(client.calls[1]['messages'][-1]['content'][0]['is_error'])
        self.assertEqual(events[-1]['lookup_counts']['total'],1)

    def test_openai_failed_lookup_blocks_answer(self):
        r=oa_web();r.output[0].status='failed'
        with self.assertRaisesRegex(h.HarnessError,'lookup failed'):self.ask('openai',[r])

    def test_fetch_receipts_for_both_providers(self):
        blocks=[{'type':'server_tool_use','id':'fetch-1','name':'web_fetch','input':{'url':U}},
                {'type':'web_fetch_tool_result','tool_use_id':'fetch-1','content':{'type':'web_fetch_result','url':U,'content':{'type':'document','title':'Example Domain','source':{'type':'text','media_type':'text/plain','data':'Example Domain'}}}}]
        for engine,raw in [('openai',oa_web(kind='open_page')),('anthropic',ac(blocks))]:
            _,_,events=self.ask(engine,[raw]);self.assertEqual(events[-1]['lookup_counts']['fetch'],1)

    def test_duplicate_sources_and_eight_source_cap(self):
        sources=[{'url':f'https://example.com/{i}','title':f'Page {i}'} for i in range(10)]
        block=source_block(sources+[sources[0]],'Read https://example.com/9')
        self.assertEqual(len(block.splitlines()),9)
        self.assertTrue(block.splitlines()[1].endswith('/9'))
        self.assertEqual(block.count(' — https://example.com/0\n'),1)

    def test_sources_are_between_answer_and_command(self):
        reply=h.validate_reply(document(intent='action_request',direct_answer='Inspect the result.',execution_payload='pwd'))
        out=h.display_text(reply,[{'url':U,'title':'Example Domain'}])
        self.assertEqual(out,'Inspect the result.\n\nSources:\n1. Example Domain — https://example.com\n\npwd\n')

    def test_no_web_disables_both_hosted_tools(self):
        for engine,raw in [('openai',response()),('anthropic',ac())]:
            _,client,_=self.ask(engine,[raw],web=False)
            types=[t.get('type') for t in client.calls[0]['tools']]
            self.assertFalse(any(t and t.startswith('web_') for t in types))

    def test_no_web_cli_and_invalid_attachment_never_make_hidden_calls(self):
        out=io.StringIO()
        with patch.object(h,'request_reply',return_value=h.validate_reply(document())) as api,contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(['--no-web','Explain.']),0)
            self.assertFalse(api.call_args.kwargs['web'])
        wrong=self.root/'wrong.png';wrong.write_text('not an image')
        with patch.object(h,'request_reply') as api,contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--image',str(wrong),'Describe.']),2);api.assert_not_called()

    def test_search_can_return_a_command_in_the_same_four_field_reply(self):
        raw=oa_web();raw.output_text=document(intent='action_request',direct_answer='Print the page title.',execution_payload="printf '%s\\n' 'Example Domain'")
        reply,_,events=self.ask('openai',[raw])
        text=h.display_text(reply,turn_metadata(events)['sources'])
        self.assertLess(text.index('Sources:'),text.index('printf'))
        self.assertEqual(set(reply.model_dump()),{'intent','cleaned_input','direct_answer','execution_payload'})

    def test_history_url_is_allowed_without_claiming_a_new_lookup(self):
        reply,_,events=self.ask('openai',[response(document(direct_answer='Use '+U))],history=[{'role':'user','content':'The link is '+U}])
        self.assertEqual(reply.direct_answer,'Use '+U)
        self.assertEqual(turn_metadata(events)['sources'],[])

    def test_system_example_url_does_not_whitelist_a_model_link(self):
        client=FakeClient([response(document(direct_answer='Use https://not-user.invalid')),response()])
        with patch.object(h,'load_tools',return_value='An example is https://not-user.invalid'):
            h.request_reply('Explain the setting.',client=client,log_path=self.log)
        self.assertEqual(len(client.calls),2)

    def test_openai_format_retry_keeps_lookup_receipts_and_remaining_budget(self):
        first=oa_web('The title is Example Domain. I hope this helps.')
        _,client,events=self.ask('openai',[first,response(document(direct_answer='The title is Example Domain.'))])
        self.assertEqual(len(client.calls),2)
        self.assertEqual(client.calls[1]['input'][-2]['role'],'assistant')
        self.assertEqual(client.calls[1]['input'][-2]['content'],first.output_text)
        self.assertIn(U,client.calls[1]['input'][-1]['content'])
        self.assertEqual(client.calls[1]['max_tool_calls'],4)
        self.assertEqual(client.calls[0]['tools'],client.calls[1]['tools'])

    def test_tool_list_is_byte_identical_across_calls(self):
        for engine,replies in [('openai',[response(),response()]),('anthropic',[ac(),ac()])]:
            client=FakeClient(replies);client.messages=client
            for text in ('First question.','Different question.'):
                h.request_reply(text,engine=engine,client=client,log_path=self.log)
            self.assertEqual(json.dumps(client.calls[0]['tools']),json.dumps(client.calls[1]['tools']))
        self.assertEqual(sum(t.get('max_uses',0) for t in tool_list('anthropic',h.api_schema())),5)

    def test_lookup_claim_rejected_without_proof_and_retried_once(self):
        for engine,replies in [('openai',[response(document(direct_answer='I searched online.')),response()]),
                               ('anthropic',[ac(answer='I looked up the answer.'),ac(answer='The supplied text gives the answer.')])]:
            _,client,events=self.ask(engine,replies)
            self.assertEqual(len(client.calls),2);self.assertEqual(events[0]['status'],'gate_rejected')
            if engine=='anthropic':self.assertEqual(client.calls[1]['messages'][-1]['content'][0]['type'],'tool_result')

    def test_lookup_claim_passes_with_proof_and_denials_are_content(self):
        for text in ['I did not search online.','There is no proof that I fetched it.','The log says "I searched online".']:
            self.assertIsNone(violation(text,{'total':0},[],''))
        self.assertIsNone(violation('I searched online.',{'total':1},[],''))
        self.assertIsNotNone(violation('After browsing, the answer is clear.',{'total':0},[],''))
        self.assertIsNotNone(violation("I've searched the site's contents.",{'total':0},[],''))

    def test_urls_need_source_request_or_history(self):
        text='Read '+U
        self.assertIsNotNone(violation(text,{'total':0},[],''))
        self.assertIsNone(violation(text,{'total':0},[],U))
        self.assertIsNone(violation(text,{'total':1},[{'url':U,'title':'Example'}],''))
        _,client,events=self.ask('openai',[response(document(direct_answer='See https://invented.invalid')),response()])
        self.assertEqual(len(client.calls),2);self.assertEqual(events[0]['status'],'gate_rejected')

    def test_oversize_rejected_before_any_request(self):
        p=self.root/'large.pdf'
        with p.open('wb') as f:f.write(b'%PDF-');f.truncate(a.OPENAI_PDF_LIMIT)
        with self.assertRaisesRegex(a.AttachmentError,'50 MB'):a.describe('file',p,'openai')
        with self.assertRaises(a.AttachmentError):a.check_size('image',8_000_000,'anthropic')

    def test_signature_not_extension_and_wrong_type_rejected(self):
        p=self.root/'renamed.pdf';p.write_bytes(Path(self.fixtures['image']).read_bytes())
        self.assertEqual(a.describe('image',p,'openai')['media_type'],'image/png')
        with self.assertRaises(a.AttachmentError):a.describe('file',p,'openai')
        p.write_text('not an image')
        with self.assertRaises(a.AttachmentError):a.describe('image',p,'openai')
        for header,mime in [(b'\xff\xd8\xff','image/jpeg'),(b'GIF89a','image/gif'),(b'RIFFxxxxWEBP','image/webp')]:
            self.assertEqual(a.media_type(header),mime)

    def test_history_resends_image_on_turn_two_for_both_engines(self):
        record=a.describe('image',self.fixtures['image'],'openai')
        exchange={'normalized_input':'Read the digits.','reply':json.loads(document()),'attachments':[record]}
        history=history_messages([exchange])
        for engine,raw in [('openai',response()),('anthropic',ac())]:
            _,client,_=self.ask(engine,[raw],query='What were those digits?',history=history)
            sent=client.calls[0]['input' if engine=='openai' else 'messages']
            user=next(m for m in sent if isinstance(m.get('content'),list))
            image=user['content'][1]
            self.assertEqual(image['type'],'input_image' if engine=='openai' else 'image')
        self.assertNotIn('base64',json.dumps(exchange))

    def test_changed_saved_attachment_stops_before_request(self):
        record=a.describe('image',self.fixtures['image'],'openai')
        Path(self.fixtures['image']).write_bytes(Path(self.fixtures['image']).read_bytes()+b'changed')
        client=FakeClient([])
        with self.assertRaisesRegex(h.HarnessError,'changed'):
            h.request_reply('Describe.',client=client,attachments=[record],log_path=self.log)
        self.assertEqual(client.calls,[])

    def test_chat_attachment_paths_and_phone_home(self):
        kind,path,question=a.chat_attachment('/image "/sdcard/Download/a b.png" What is "NC"?')
        self.assertEqual((kind,path,question),('image','/sdcard/Download/a b.png','What is "NC"?'))
        self.assertEqual(a.phone_path('~/x.png'),a.PHONE_HOME/'x.png')

    def test_sqlite_and_session_metadata_and_recall(self):
        client=FakeClient([oa_web()]);out=io.StringIO()
        original=h.request_reply
        def ask(*args,**kwargs):return original(*args,client=client,**kwargs)
        with patch.object(h,'request_reply',side_effect=ask),contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(['--session','proof','Search example page.']),0)
        db=sqlite3.connect(h.STATE/'history.db');db.row_factory=sqlite3.Row
        row=dict(db.execute('SELECT * FROM history').fetchone());db.close()
        self.assertEqual(json.loads(row['sources_json'])[0]['url'],U)
        self.assertEqual(json.loads(row['lookup_counts_json'])['total'],1)
        session=json.loads((h.STATE/'sessions/proof.json').read_text())
        self.assertEqual(session['turns'][0]['sources'][0]['url'],U)
        with contextlib.redirect_stdout(out),patch.object(h,'request_reply') as api:
            self.assertEqual(cli.main(['--recall','example']),0);api.assert_not_called()
        self.assertEqual(out.getvalue().count('Sources:'),2)


if __name__=='__main__':unittest.main()
