#!/data/data/com.termux/files/usr/bin/python
"""Real maker tasks through both lanes. Receipts and outputs remain private."""
import argparse
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parent
CASES = ('image', 'word', 'research', 'browser')


def run(engine, case, folder):
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    state = folder / 'runtime'
    state.mkdir(exist_ok=True)
    (state/'mods.json').write_text(json.dumps({'memory-version': False, 'voice': False}))
    output = Path('/sdcard/Download') / f'makers-{engine}-{case}-nov12.png' if case == 'image' else folder / {
        'word': 'bread.docx', 'research': 'daly-city.pdf', 'browser': 'heading.json', 'image': 'unused'}[case]
    task = {
        'image': f'Make a picture of a blue teapot and put it in Downloads at {output}, then look at it and tell me what you see. Use make-image, then look.',
        'word': f'Make a Word file with three bullet points about bread at {output} and tell me its size. Use make-docx and read-doc.',
        'research': f'Research when Daly City was incorporated and write a one-page PDF with sources at {output}. Use deep-research with --engine {engine}; include "one-page report" in its question. Then read-doc to inspect it.',
        'browser': f'Open example.com in my signed-in Chrome and tell me the heading. Use page-open and page-eval. Save JSON with url, title, and headings (a list of all heading texts) at {output}, then page-close. If the page has no heading, record an empty list and report that fact.',
    }[case]
    task += ' Print the matching card first. Use local execution_payload commands. Keep all gates on. Do not write memory notes or change accounts.'
    env = {**os.environ, 'HARNESS_STATE_DIR': str(state)}
    env.pop('LD_LIBRARY_PATH', None)
    command = [str(ROOT/'harness'), '--engine', engine, '--effort', 'max', '--timeout', '3600',
               '--exec-timeout', '86400', '--loop', '-y', task]
    start = time.monotonic()
    with (folder/'stdout.txt').open('w') as out, (folder/'stderr.txt').open('w') as err:
        done = subprocess.run(command, env=env, cwd=ROOT, stdout=out, stderr=err)
    rows = []
    if (state/'history.db').exists():
        with sqlite3.connect(state/'history.db') as db:
            db.row_factory = sqlite3.Row
            rows = [dict(r) for r in db.execute('SELECT id,status,direct_answer,execution_payload,execution_result,attachments_json,sources_json,gate_json FROM history ORDER BY id')]
    commands = '\n'.join(r['execution_payload'] or '' for r in rows)
    turns = []
    for path in (state/'sessions').glob('*.json'):
        turns.extend(json.loads(path.read_text()).get('turns', []))
    checks = {'exit_zero': done.returncode == 0, 'artifact_exists': output.is_file() and output.stat().st_size > 0,
              'used_maker': {'image':'make-image','word':'make-docx','research':'deep-research','browser':'page-open'}[case] in commands,
              'four_fields': bool(turns) and all(set(t.get('reply', {})) == {'intent','cleaned_input','direct_answer','execution_payload'} for t in turns)}
    if case == 'image':
        checks['look'] = 'look ' in commands and any('execution_attachments' in (r.get('execution_result') or '') or 'attachments' in (r.get('execution_result') or '') for r in rows)
    if case == 'word' and output.exists():
        with zipfile.ZipFile(output) as book:
            checks['parsed_word'] = book.testzip() is None and b'bread' in book.read('word/document.xml').lower()
    if case == 'browser' and output.exists():
        try:
            page = json.loads(output.read_text())
            checks['page_read'] = page.get('url', '').rstrip('/') == 'https://example.com' and page.get('title') == 'Example Domain' and isinstance(page.get('headings'), list) and 'page-eval' in commands
        except (ValueError, AttributeError):
            checks['page_read'] = False
    if case == 'research' and output.exists():
        result = subprocess.run(['proot-distro','login','debian','--','python3','-c',
            'from pypdf import PdfReader;import json,sys;r=PdfReader(sys.argv[1]);print(json.dumps({"pages":len(r.pages),"text":"\\n".join(p.extract_text() or "" for p in r.pages),"links":[str(a.get_object().get("/A",{}).get("/URI")) for p in r.pages for a in p.get("/Annots",[]) if a.get_object().get("/A",{}).get("/URI")]}))',str(output)], capture_output=True,text=True)
        if result.returncode == 0:
            pdf = json.loads(result.stdout)
            (folder/'pdf.json').write_text(json.dumps(pdf, indent=2))
            checks['one_page'] = pdf['pages'] == 1
            checks['date_and_sources'] = 'March 22, 1911' in ' '.join(pdf['text'].split()) and 'Sources' in pdf['text'] and bool(pdf['links'])
            recorded = set()
            for row in rows:
                result_text = json.loads(row['execution_result']).get('stdout', '') if row.get('execution_result') else ''
                for run_path in re.findall(r'run folder: (/\S+)', result_text):
                    with sqlite3.connect(Path(run_path)/'history.db') as db:
                        for sources, in db.execute('SELECT sources_json FROM history WHERE sources_json IS NOT NULL'):
                            recorded.update(s['url'].rstrip('/') for s in json.loads(sources))
            checks['links_recorded'] = bool(recorded) and all(link.rstrip('/') in recorded for link in pdf['links'])
        else:
            checks['parsed_pdf'] = False
    report = {'engine': engine, 'case': case, 'query': task, 'exit_code': done.returncode,
              'seconds': round(time.monotonic()-start,2), 'artifact': str(output),
              'bytes': output.stat().st_size if output.exists() else 0, 'checks': checks,
              'passed': all(checks.values()), 'rows': rows}
    (folder/'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({k:report[k] for k in ['engine','case','exit_code','seconds','bytes','checks','passed']}), flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--engine', required=True, choices=['openai','anthropic'])
    p.add_argument('--case', required=True, choices=CASES)
    p.add_argument('--folder', type=Path)
    a = p.parse_args()
    result = run(a.engine, a.case, a.folder or ROOT/'state/makers/live'/a.engine/a.case)
    raise SystemExit(0 if result['passed'] else 1)
