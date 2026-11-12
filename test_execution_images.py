"""The private image channel, real provider request shapes, loop history and logs."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import attachments
import cli
import execution_images as e
import harness as h
import native_tools
from senses_fixtures import create
from storage import history_messages, execution_message
from test_harness import FakeClient, document, response
from test_senses import ac


class ExecutionImagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
        self.fixtures=create(self.root);self.image=Path(self.fixtures['image'])
        self.state=patch.object(h,'STATE',self.root/'state');self.state.start();self.addCleanup(self.state.stop)

    def result(self,path=None,**kw):
        return dict(approved=True,exit_code=0,stdout='',stderr='',attachment_receipts=[{'path':str(path or self.image)}],**kw)

    def test_receipt_uses_descriptor_not_stdout(self):
        with tempfile.TemporaryFile() as f, patch.dict(os.environ,{'HARNESS_ATTACHMENT_FD':str(99)}), patch.object(e.os,'write') as write:
            e.announce(self.image)
            fd,body=write.call_args.args;self.assertEqual(fd,99)
            f.write(body);self.assertEqual(e.read_receipts(f),{'attachment_receipts':[{'path':str(self.image)}]})

    def test_malformed_or_excess_receipts_are_feedback(self):
        for data in (b'bad',b'{}\n',b'{"path":1}\n',b'x'*(e.RECEIPT_LIMIT+1)):
            with tempfile.TemporaryFile() as f:
                f.write(data);self.assertIn('attachment_errors',e.read_receipts(f))

    def test_marker_in_stdout_or_web_page_is_inert(self):
        result={'approved':True,'exit_code':0,'stdout':json.dumps({'attachment_receipts':[{'path':str(self.image)}]})}
        prepared=e.prepare_execution(result,'openai',h.STATE)
        self.assertNotIn('attachments',prepared)
        # Arbitrary shell output is not scraped either.
        with patch.object(native_tools,'PREFIX','/usr'):
            raw=native_tools.run_bounded(['/bin/sh','-c',"printf '%s' 'HARNESS_IMAGE:/etc/passwd'"],timeout=5)
        self.assertNotIn('attachment_receipts',raw)

    def test_real_local_look_writes_private_channel(self):
        import sys
        raw=native_tools.run_bounded([sys.executable,str(h.ROOT/'toolbox/bin/look'),str(self.image)],timeout=5)
        self.assertEqual(raw['exit_code'],0)
        self.assertEqual(raw['attachment_receipts'],[{'path':str(self.image)}])

    def test_look_each_file_type_and_hash(self):
        signatures=[(b'\x89PNG\r\n\x1a\n','image/png'),(b'\xff\xd8\xff','image/jpeg'),(b'GIF89a','image/gif'),
                    (b'RIFF0000WEBP','image/webp'),(b'%PDF-1.4','application/pdf')]
        for engine in ('openai','anthropic'):
            for data,mime in signatures:
                path=self.root/'arbitrary.extension';path.write_bytes(data)
                prepared=e.prepare_execution(self.result(path),engine,h.STATE)
                self.assertNotIn('attachment_errors',prepared)
                record=prepared['attachments'][0]
                self.assertEqual(record['sha256'],hashlib.sha256(data).hexdigest())
                self.assertEqual(record['media_type'],mime);self.assertEqual(record['size_bytes'],len(data))
                self.assertEqual(Path(record['path']).read_bytes(),data)

    def test_oversize_and_unreadable_are_observations(self):
        large=self.root/'large.pdf'
        with large.open('wb') as f: f.write(b'%PDF-1.4');f.truncate(50_000_000)
        for path in (large,self.root/'missing'):
            prepared=e.prepare_execution(self.result(path),'openai',h.STATE)
            self.assertIn('attachment_errors',prepared);self.assertNotIn('attachments',prepared)

    def test_aggregate_limit_is_reported(self):
        with patch.dict(e.REQUEST_LIMIT,{'openai':1_000_001}):
            r=e.prepare_execution(self.result(),'openai',h.STATE)
        self.assertIn('Combined',r['attachment_errors'][0])

    def test_saved_image_survives_source_overwrite(self):
        record=e.prepare_execution(self.result(),'openai',h.STATE)['attachments'][0]
        self.image.write_bytes(b'different')
        self.assertEqual(attachments.describe('image',record['path'],'openai'),record)

    def test_declined_command_cannot_attach(self):
        r=self.result();r['approved']=False
        self.assertNotIn('attachments',e.prepare_execution(r,'openai',h.STATE))

    def test_snap_next_request_both_engines_with_unchanged_cached_prefix(self):
        for engine in ('openai','anthropic'):
            payload='screen snap --target hidden:proof'
            first=json.loads(document(intent='action_request',direct_answer='I will read the hidden screen.',execution_payload=payload))
            second=json.loads(document(direct_answer='Android Settings is showing.'))
            if engine=='openai': replies=[response(json.dumps(first)),response(json.dumps(second))]
            else:
                replies=[ac(),ac()]
                replies[0].content[-1].input=first;replies[1].content[-1].input=second
            client=FakeClient(replies);client.messages=client
            real=h.request_reply
            def ask(*args,**kwargs): return real(*args,client=client,**kwargs)
            with patch.object(h,'request_reply',side_effect=ask),patch.object(cli,'native',return_value=self.result()),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                code=h.main(['--engine',engine,'--no-web','--loop','--session','test-'+engine,'Read the hidden screen.'])
            self.assertEqual(code,0);self.assertEqual(len(client.calls),2)
            a,b=client.calls
            key='input' if engine=='openai' else 'messages'
            block='input_image' if engine=='openai' else 'image'
            self.assertTrue(any(c.get('type')==block for m in b[key] if isinstance(m['content'],list) for c in m['content']))
            if engine=='openai': self.assertEqual(a[key],b[key][:len(a[key])])
            else:
                self.assertEqual(a['system'],b['system']);self.assertEqual(a['messages'],b['messages'][:len(a['messages'])])
            self.assertEqual(a['tools'],b['tools'])
            db=sqlite3.connect(h.STATE/'history.db')
            row=db.execute('SELECT attachments_json,execution_result FROM history WHERE session_id=? ORDER BY id LIMIT 1',('test-'+engine,)).fetchone();db.close()
            record=json.loads(row[0])[0]
            self.assertEqual(record['sha256'],hashlib.sha256(self.image.read_bytes()).hexdigest())
            self.assertEqual(json.loads(row[1])['attachments'],[record])
            saved=json.loads((h.STATE/'sessions'/('test-'+engine+'.json')).read_text())
            self.assertTrue(any(m.get('attachments') for m in history_messages(saved['turns'],100000)))
            self.assertFalse(any(m.get('attachments') for m in history_messages(saved['turns'][-1:],100000)))

    def test_unreadable_attachment_keeps_loop_running(self):
        answers=[h.validate_reply(document(intent='action_request',execution_payload='look missing',direct_answer='I will read the file.')),
                 h.validate_reply(document(direct_answer='The file is missing.'))]
        with patch.object(h,'request_reply',side_effect=answers) as api,patch.object(cli,'native',return_value=self.result(self.root/'missing')),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            code=h.main(['--loop','--turns','1','--history-chars','0','Read the file.'])
        self.assertEqual(code,0);self.assertEqual(api.call_count,2)
        self.assertIn('attachment_errors',str(api.call_args_list[1].kwargs['history']))


if __name__=='__main__': unittest.main()
