#!/data/data/com.termux/files/usr/bin/python
"""Live skill jobs through the native harness; private receipts stay in state/."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parent
CASES = ('word', 'sheet', 'slides', 'review', 'research', 'apps')

def run(engine, case, folder, resume=False):
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if resume and (folder/'report.json').exists():
        import shutil
        prior=folder/('attempt-'+str(time.time_ns()))
        prior.mkdir()
        for name in ['report.json','stdout.txt','stderr.txt']:
            if (folder/name).exists():shutil.copy2(folder/name,prior/name)
    state = folder / 'runtime'
    state.mkdir(exist_ok=True)
    # This job cannot write/commit canonical notes. Other display and judge gates stay on.
    (state / 'mods.json').write_text(json.dumps({'memory-version': False, 'voice': False}))
    output = folder / {'word':'sample.docx','sheet':'sample.xlsx','slides':'sample.pptx','review':'review.txt','research':'research.md','apps':'apps.txt'}[case]
    specs = {
        'word': f'Use the docx skill to make a one-page Word file at {output}. Title: Bakery packing list. Add three numbered items: boxes, labels, ribbon. Read all parts of the skill first. Follow its file creation and validation steps, then tell me the exact byte size.',
        'sheet': f'What skills do I have for spreadsheets? Use one to make a sheet with three rows and tell me the file size. Save it at {output}. The three data rows are Apples 2, Pears 3, Plums 4. Include column headings. Read every part of the chosen skill and follow its validation steps.',
        'slides': f'Use the pptx skill to make a three-slide deck at {output}: Packing plan; Boxes and labels; Ready for pickup. Use text only and simple shapes. Read every part of the skill. Follow its creation and validation steps, then report the exact byte size.',
        'review': f'Use the grok:code-review skill for a short code review of {ROOT}/phonetics.py. Read the skill and actual code. Write your findings with file/line receipts to {output}. Do not edit the reviewed file. Say plainly if you find no bug. Report the review file size.',
        'research': f'Use the deep-research skill for a short research note, at most 250 words, on how Python sqlite3 parameter placeholders work. Read the skill, then fetch the official Python sqlite3 documentation and one official SQLite page. Include two source URLs and one small example. Save to {output}, then report its byte size. This is deliberately a small research task; use its lightest depth.',
        'apps': f'Is Termux:API installed, and which permissions does it hold? Use the apps card and app commands. Save the full exact command results to {output}. Summarize installed version and granted permission count.',
    }
    task=specs[case]+' Work through local execution_payload commands in the native loop. Python and document tools are on Debian (deb). Keep all new files inside '+str(folder)+'. Do not modify memory notes, accounts, installed apps or live source. Finish the actual file and inspect it before answering.'
    env = os.environ.copy(); env.pop('LD_LIBRARY_PATH',None); env['HARNESS_STATE_DIR']=str(state)
    command=[str(ROOT/'harness'),'--engine',engine,'--effort','max','--loop','-y',*(['--continue'] if resume else []),task]
    start=time.monotonic()
    with (folder/'stdout.txt').open('w') as stdout, (folder/'stderr.txt').open('w') as stderr:
        done=subprocess.run(command,env=env,cwd=ROOT,stdout=stdout,stderr=stderr)
    rows=[]
    if (state/'history.db').exists():
        db=sqlite3.connect(state/'history.db'); db.row_factory=sqlite3.Row
        rows=[dict(x) for x in db.execute('select id,status,direct_answer,execution_payload,execution_result from history order by id')]; db.close()
    executed=[]
    for row in rows:
        result=json.loads(row['execution_result']) if row.get('execution_result') else {}
        if result.get('approved') and result.get('exit_code') == 0:
            executed.append(row.get('execution_payload') or '')
    receipt='\n'.join(executed)
    checks={'exit_zero':done.returncode==0,'artifact_exists':output.is_file() and output.stat().st_size>0,'used_skill_or_card':('skill show' if case!='apps' else 'card apps') in receipt}
    turns=[]
    for path in (state/'sessions').glob('*.json'):
        turns.extend(json.loads(path.read_text()).get('turns', []))
    checks['four_field_replies']=bool(turns) and all(set(turn.get('reply',{})) == {'intent','cleaned_input','direct_answer','execution_payload'} for turn in turns)
    if output.exists() and case in ('word','sheet','slides'):
        try:
            with zipfile.ZipFile(output) as z:
                checks['valid_office_zip']=z.testzip() is None
                if case=='word': checks['content_verified']=all(x in z.read('word/document.xml').decode() for x in ['Bakery','boxes','labels','ribbon'])
                elif case=='slides': checks['three_slides']=len([n for n in z.namelist() if __import__('re').fullmatch(r'ppt/slides/slide\d+\.xml',n)])==3
                else: checks['content_verified']=all(x in ''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xml')) for x in ['Apples','Pears','Plums'])
        except Exception as exc: checks['office_error']=str(exc)
    report={'engine':engine,'case':case,'query':task,'exit_code':done.returncode,'seconds':round(time.monotonic()-start,2),'artifact':str(output),'bytes':output.stat().st_size if output.exists() else 0,'checks':checks,'passed':all(v is True for v in checks.values()),'rows':rows}
    (folder/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:report[k] for k in ['engine','case','exit_code','seconds','bytes','checks','passed']}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--engine',required=True,choices=['openai','anthropic']);p.add_argument('--case',required=True,choices=CASES);p.add_argument('--folder',type=Path);p.add_argument('--resume',action='store_true');a=p.parse_args()
    r=run(a.engine,a.case,a.folder or ROOT/'state/skills-apps/live'/a.engine/a.case,resume=a.resume)
    raise SystemExit(0 if r['passed'] else 1)
