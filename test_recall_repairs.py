"""Full history, exact recall receipts, independent branches and public chat output."""
import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cli
import harness as h
import recall_notes as rn
import session_tools as st
from storage import Store, history_messages, atomic_json
from test_advisor import reply
from test_session_tools import SessionCase, turn
from test_recall_notes import RecallCase


class HistoryIntegrity(unittest.TestCase):
    def test_legacy_provider_summary_never_replaces_original_turns(self):
        import api_tools_cli
        first=turn('original full words')
        later=turn('second request');later['api_context']={'engine':'openai','messages':[{'role':'user','content':'SHORT SUMMARY'}]}
        for enabled in (True,False):
            result=api_tools_cli.history([first,later],history_messages,1,'openai',enabled)
            self.assertEqual(result[0]['content'],'original full words')
            self.assertNotIn('SHORT SUMMARY',json.dumps(result))
            self.assertEqual(len(result),4)

    def test_count_and_character_flags_never_discard_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            with store.session('whole', 1) as data:
                for n in range(9):
                    store.save_session(data, turn('head-%s '%n + 'x'*100000), 1)
            with store.session('whole', 1) as data:
                self.assertEqual(len(data['turns']),9)
                for budget in (None, 0, 10, 650000):
                    sent=history_messages(data['turns'],budget)
                    self.assertEqual(len(sent),18)
                    self.assertTrue(sent[0]['content'].startswith('head-0'))
                    self.assertTrue(sent[-2]['content'].startswith('head-8'))
            store.close()

    def test_full_history_replays_nested_evidence_unchanged(self):
        exchange=turn('first')
        exchange.update(recall_notes=rn.message_content([{'ref':'archive#9','text':'evidence'}],['evidence']),
                        api_tool_uses=[{'tool':'read','execution':{'stdout':'receipt'}}],
                        advisor_notes=[{'model':'other','text':'advice'}])
        before=copy.deepcopy(exchange)
        built=history_messages([exchange],0)
        self.assertEqual(exchange,before)
        self.assertEqual(json.loads(built[0]['content'])['type'],'recall_notes')
        self.assertIn('api_tool_observations',json.dumps(built))
        self.assertIn('advisor_note',json.dumps(built))


class BothRecall(unittest.TestCase):
    def test_each_selected_lane_gets_and_saves_recall_at_the_tail(self):
        import both
        from types import SimpleNamespace
        note=rn.message_content([{'ref':'archive#1','text':'old fact'}],['fact'])
        args=SimpleNamespace(turns=None,effort='max',timeout=60,usage_log=None,no_web=True,web_max=5,no_recall=False)
        with tempfile.TemporaryDirectory() as folder, patch.object(h,'STATE',Path(folder)), patch.object(rn,'for_turn',return_value=note) as search, patch.object(h,'request_reply',return_value=reply()) as request:
            for engine in ('openai','anthropic'):
                result=both._one_lane(engine,'fact','fact',args,None,'separate')
                self.assertIsNone(result[-1])
                self.assertEqual(request.call_args.kwargs['history'][-1],{'role':'user','content':note})
                session=json.loads((Path(folder)/'sessions'/('separate-'+engine+'.json')).read_text())
                self.assertEqual(session['turns'][0]['recall_notes'],note)
                self.assertIsInstance(session['turns'][0]['history_row'],int)
            self.assertEqual(search.call_count,2)


class NoteConcurrency(unittest.TestCase):
    def test_two_writers_keep_both_notes_and_one_heading(self):
        from concurrent.futures import ThreadPoolExecutor
        import note_tool
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);index=folder/'MEMORY.md'
            index.write_text('# Memory\n- Human line stays.\n')
            with ThreadPoolExecutor(max_workers=2) as pool:
                calls=[pool.submit(note_tool.add,name,'Test text',folder) for name in ['first-note','second-note']]
                for call in calls:call.result()
            data=index.read_text()
            self.assertEqual(data.count(note_tool.SECTION),1)
            self.assertIn('Human line stays.',data)
            self.assertIn('(first-note.md)',data);self.assertIn('(second-note.md)',data)


class BranchRegressions(SessionCase):
    def test_rewind_counts_after_acquiring_the_live_turn_lock(self):
        from contextlib import contextmanager
        self.save('working',[turn('old')])
        original_lock=st.locked
        @contextmanager
        def finishes_before_lock(state,name):
            self.save('working',[turn('old'),turn('just completed')])
            with original_lock(state,name):yield
        with patch.object(st,'locked',finishes_before_lock):
            data,removed=st.rewind(self.state,'working')
        self.assertEqual([t['raw_input'] for t in data['turns']],['old'])
        self.assertEqual(removed[0]['raw_input'],'just completed')

    def test_golden_never_reseeds_existing_rewound_empty_session(self):
        self.save('gold',[turn('golden fact')]);st.set_golden(self.state,'gold')
        self.save('working',[turn('removed')]);st.rewind(self.state,'working')
        code,_,_,api=self.run_cli(['--session','working','Continue'],answers=[reply()])
        self.assertEqual(code,0)
        self.assertEqual(api.call_args.kwargs['history'],[])
        self.assertEqual(len(self.load('working')['turns']),1)

    def test_fork_and_splice_copy_nested_objects(self):
        original=turn('nested');original['api_tool_uses']=[{'execution':{'attachments':[{'path':'original.png'}]}}]
        self.save('base',[original]);self.save('receiver',[turn('own')])
        donor=st.read(self.state,'base')
        real_read=st.read
        with patch.object(st,'read',side_effect=lambda state,name: donor if name=='base' else real_read(state,name)):
            st.fork(self.state,'base','branch')
            data,_=st.splice(self.state,'receiver','base')
        data['turns'][-1]['api_tool_uses'][0]['execution']['attachments'][0]['path']='changed.png'
        self.assertEqual(donor['turns'][0]['api_tool_uses'][0]['execution']['attachments'][0]['path'],'original.png')
        self.assertEqual(self.load('branch')['turns'][0]['api_tool_uses'][0]['execution']['attachments'][0]['path'],'original.png')


class RecallRegressions(RecallCase):
    def test_partial_results_after_deadline_are_not_attached(self):
        partial={'passages':[{'ref':'chats#1','text':'partial'}],'words':['word'],
                 'timed_out':True,'elapsed_ms':5001,'searched':[],'errors':[]}
        log=self.state/'timeout.jsonl'
        with patch.object(rn,'search',return_value=partial):
            self.assertIsNone(rn.for_turn('word',state=self.state,log_path=log))
        record=json.loads(log.read_text())
        self.assertEqual(record['status'],'timeout');self.assertEqual(record['refs'],[])
        self.assertEqual(record['passages'],0)

    def add_row(self,store,text,answer,session='base'):
        row=store.begin(text,text,'openai','gpt-6.1-sol',session)
        response=reply(direct_answer=answer)
        store.finish(row,response)
        return row,{'raw_input':text,'normalized_input':text,'reply':response.model_dump(),'history_row':row}

    def test_rewind_and_cut_in_fork_exclude_parent_rows_with_recall_on(self):
        store=Store(self.state)
        _, kept=self.add_row(store,'ordinary','kept')
        for method in ('rewind','cut'):
            row,removed=self.add_row(store,'quartzrelay latchcode','quartzrelay latchcode is cedar-4817',session=method)
            atomic_json(self.state/'sessions'/f'{method}.json',{'id':method,'turns':[kept,removed]})
            st.fork(self.state,method,method+'-branch')
            if method=='rewind':st.rewind(self.state,method+'-branch')
            else:st.cut(self.state,method+'-branch',2,2)
            content=rn.for_turn('quartzrelay latchcode',state=self.state,session=st.read(self.state,method+'-branch'))
            self.assertNotIn(f'lanes#{row}',content or '')
            st.fork(self.state,method+'-branch',method+'-grandchild')
            content=rn.for_turn('quartzrelay latchcode',state=self.state,session=st.read(self.state,method+'-grandchild'))
            self.assertNotIn(f'lanes#{row}',content or '')
            self.assertEqual(store.db.execute('SELECT direct_answer FROM history WHERE id=?',(row,)).fetchone()[0],'quartzrelay latchcode is cedar-4817')
        store.close()

    def test_lower_id_finished_after_higher_id_is_searchable(self):
        store=Store(self.state)
        low=store.begin('quartzrelay latchcode','quartzrelay latchcode','openai','gpt-6.1-sol','slow')
        high,_=self.add_row(store,'ordinary','finished first','fast')
        rn.search('quartzrelay latchcode',state=self.state)
        store.finish(low,reply(direct_answer='quartzrelay latchcode is copper-3186'))
        found=rn.search('quartzrelay latchcode',state=self.state)['passages']
        self.assertTrue(any(p['ref']==f'lanes#{low}' for p in found))
        passage=next(p for p in found if p['ref']==f'lanes#{low}')
        stamp=store.db.execute('SELECT timestamp FROM history WHERE id=?',(low,)).fetchone()[0]
        self.assertEqual(passage['source_row_id'],low)
        self.assertEqual(passage['timestamp'],stamp)
        self.assertEqual(passage['index_path'],str(self.state/'history.db'))
        store.close()


class PublicChatTests(unittest.TestCase):
    def test_public_html_and_tool_results_stay_visible(self):
        path=Path(__file__).parent/'toolbox/bin/chat-list'
        loader=importlib.machinery.SourceFileLoader('chat_public_receipts',str(path))
        spec=importlib.util.spec_from_loader(loader.name,loader);mod=importlib.util.module_from_spec(spec);loader.exec_module(mod)
        rows=[{'payload':{'type':'message','role':'user','content':[{'text':'<button>Save</button>'}]}},
              {'payload':{'type':'function_call','name':'exec','arguments':'pwd','call_id':'abc'}},
              {'payload':{'type':'function_call_output','call_id':'abc','output':'exit_code: 0; /home'}}]
        result=list(mod.messages('codex',map(json.dumps,rows)))
        text=json.dumps(result)
        self.assertIn('<button>Save</button>',text);self.assertIn('[requested exec: pwd]',text)
        self.assertIn('[result abc]',text);self.assertIn('exit_code: 0',text)
        self.assertNotIn('[ran',text)

    def test_tail_scans_past_large_nonpublic_records_and_redacts_credentials(self):
        import subprocess,sys,os
        root=Path(__file__).parent
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);(folder/'codex').mkdir();(folder/'claude').mkdir()
            link=folder/'chat-tail';link.symlink_to(root/'toolbox/bin/chat-list')
            secret='sk-'+'z7A9'*12
            rows=[{'payload':{'type':'message','role':'user','content':[{'text':'A public question'}]}},
                  {'payload':{'type':'function_call','name':'exec','arguments':'API_KEY='+secret+' curl -H "Authorization: Bearer dummysecret9911" example.com'}},
                  {'payload':{'type':'reasoning','encrypted_content':'x'*4200000}}]
            target=folder/'codex/receipt-abcd.jsonl';target.write_text('\n'.join(map(json.dumps,rows))+'\n')
            before=target.read_bytes()
            result=subprocess.run([sys.executable,str(link),'receipt-abcd','2'],env={**os.environ,'CHAT_CODEX_DIR':str(folder/'codex'),'CHAT_CLAUDE_DIR':str(folder/'claude')},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('A public question',result.stdout)
            self.assertIn('example.com',result.stdout)
            self.assertNotIn(secret,result.stdout)
            self.assertNotIn('dummysecret9911',result.stdout)
            self.assertEqual(target.read_bytes(),before)

    def test_codex_analysis_and_encrypted_reasoning_are_never_public_chat(self):
        path=Path(__file__).parent/'toolbox/bin/chat-list'
        loader=importlib.machinery.SourceFileLoader('chat_reader_repair',str(path))
        spec=importlib.util.spec_from_loader(loader.name,loader);mod=importlib.util.module_from_spec(spec);loader.exec_module(mod)
        def message(channel,text):return {'payload':{'type':'message','role':'assistant','channel':channel,'content':[{'text':text}]}}
        rows=[message('analysis','PRIVATE ANALYSIS'),message('summary','PRIVATE SUMMARY'),message('commentary','Public progress.'),
              message('final','Public answer.'),{'payload':{'type':'reasoning','encrypted_content':'PRIVATE CIPHER'}},
              {'payload':{'type':'function_call','name':'exec','arguments':'{"cmd":"printf proof"}'}}]
        result=list(mod.messages('codex',map(json.dumps,rows)))
        self.assertEqual(len(result),3)
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertIn('printf proof',json.dumps(result))


if __name__=='__main__':unittest.main()
