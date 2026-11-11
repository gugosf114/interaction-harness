"""CLI workflow: normalize, remember, request, gate, record, display, confirm."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys

import harness as h
from phonetics import normalize
from storage import Store, history_messages, atomic_json


def native(request):
    fd = os.environ.get('HARNESS_BRIDGE_FD')
    if fd is None: raise h.HarnessError('Use the Termux harness launcher for --exec or --listen.')
    try:
        with socket.socket(fileno=os.dup(int(fd))) as sock:
            with sock.makefile('rwb') as stream:
                stream.write(json.dumps(request).encode()+b'\n'); stream.flush()
                line = stream.readline(16777216)
                if not line: raise h.HarnessError('The Termux command bridge closed.')
                result = json.loads(line)
    except (OSError, ValueError) as exc:
        raise h.HarnessError('The Termux command bridge failed.') from exc
    if result.get('error'): raise h.HarnessError(result['error'])
    return result


def run_chat(args, model):
    """Pin one session for the whole loop; each turn still uses the standard gate."""
    try:
        store=Store(h.STATE)
        try: sid=store.select_session(args.session,args.continuing)
        finally: store.close()
    except (ValueError,OSError) as exc:
        print(str(exc),file=sys.stderr); return 2
    except Exception as exc:
        print(f'Unexpected client error ({type(exc).__name__}).',file=sys.stderr); return 2
    options=['--engine',args.engine,'--model',model,'--effort',args.effort,
             '--timeout',str(args.timeout),'--usage-log',str(args.usage_log),
             '--session',sid,'--turns',str(args.turns),'--history-chars',str(args.history_chars),
             '--exec-timeout',str(args.exec_timeout)]
    if args.no_normalize: options.append('--no-normalize')
    if args.execute: options.append('--exec')
    last_status=0
    if args.text: last_status=main([*options,'--',' '.join(args.text)])
    while True:
        try:
            # Prompts stay off stdout so redirected output remains answer-only.
            print('> ',end='',file=sys.stderr,flush=True)
            raw=sys.stdin.readline(h.MAX_INPUT_CHARS+2)
            if raw=='': return last_status
            if len(raw)>h.MAX_INPUT_CHARS and not raw.endswith('\n'):
                # Drain the rest of an oversized line so its tail cannot become a new request.
                while raw and not raw.endswith('\n'): raw=sys.stdin.readline(h.MAX_INPUT_CHARS+2)
                print(f'Input exceeds {h.MAX_INPUT_CHARS} characters.',file=sys.stderr)
                last_status=2; continue
            raw=raw.rstrip('\r\n')
            if raw.strip().lower() in {'exit','quit'}: return last_status
            if not raw.strip(): continue
            last_status=main([*options,'--',raw])
            if last_status==130: return 130
        except KeyboardInterrupt:
            print('',file=sys.stderr); return 130


def main(argv=None):
    parser=argparse.ArgumentParser(description='Direct answers, bounded memory, optional confirmed Termux execution.')
    parser.add_argument('--engine',choices=['openai','anthropic'],default=os.environ.get('DEFAULT_ENGINE','openai'))
    parser.add_argument('--model',default=None)
    parser.add_argument('--effort',choices=['low','medium','high','xhigh','max'],default=h.DEFAULT_EFFORT,help='Reasoning effort on either engine (default: high).')
    parser.add_argument('--chat','--interactive',dest='chat',action='store_true',help='Stay open for multiple turns; automatic on an interactive terminal with no input.')
    parser.add_argument('--timeout',type=float,default=90)
    parser.add_argument('--usage-log',type=Path,default=h.STATE/'usage.jsonl')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--new',action='store_true',help='Fresh isolated turn (default); its ID becomes available to --continue.')
    group.add_argument('-c','--continue',dest='continuing',action='store_true')
    group.add_argument('--session',metavar='NAME')
    parser.add_argument('--turns',type=int,default=6,help='Exchanges kept in the rolling session (1–50).')
    parser.add_argument('--history-chars',type=int,default=24000,help='Maximum prior-history characters sent to the model.')
    parser.add_argument('--no-normalize',action='store_true',help='Send exact typed input without phonetic substitutions.')
    parser.add_argument('-x','--exec',dest='execute',action='store_true',help='Ask y/N before running the returned command in native Termux.')
    parser.add_argument('--exec-timeout',type=int,default=120)
    parser.add_argument('--recall',metavar='QUERY',help='Search local history without an API call.')
    parser.add_argument('-l','--listen',action='store_true',help='Use Android speech recognition through Termux:API.')
    parser.add_argument('--listen-timeout',type=int,default=90)
    parser.add_argument('text',nargs='*',help='Quoted input, or pipe text on stdin.')
    args=parser.parse_args(argv)
    if args.engine not in {'openai','anthropic'}: parser.error('DEFAULT_ENGINE must be openai or anthropic.')
    if not 1<=args.timeout<=300: parser.error('--timeout must be between 1 and 300 seconds.')
    if not 1<=args.turns<=50: parser.error('--turns must be between 1 and 50.')
    if not 0<=args.history_chars<=200000: parser.error('--history-chars must be between 0 and 200000.')
    if not 1<=args.exec_timeout<=600: parser.error('--exec-timeout must be between 1 and 600.')
    if not 1<=args.listen_timeout<=180: parser.error('--listen-timeout must be between 1 and 180.')
    if args.listen and args.text: parser.error('Use --listen or typed text, not both.')
    if args.chat and (args.listen or args.recall is not None): parser.error('--chat uses typed input; use --listen or --recall separately.')
    if args.recall is not None and (args.text or args.listen or args.execute): parser.error('--recall searches history without input or execution.')
    model=args.model or os.environ.get('OPENAI_MODEL' if args.engine=='openai' else 'ANTHROPIC_MODEL') or (h.DEFAULT_MODEL if args.engine=='openai' else h.ANTHROPIC_MODEL)
    if args.chat or (not args.text and not args.listen and args.recall is None and sys.stdin.isatty()):
        return run_chat(args,model)
    store=None; row_id=None; events=[]; reply=None; execution=None
    try:
        store=Store(h.STATE)
        if args.recall is not None:
            matches=store.recall(args.recall)
            rendered=[]
            for row in matches:
                raw={k:row[k] for k in ('intent','cleaned_input','direct_answer','execution_payload')}
                # Recall uses the same gate; rejected legacy text is not displayed.
                try: rendered.append(h.display_text(h.validate_reply(json.dumps(raw),row.get('normalized_input') or row.get('raw_input'))))
                except h.GateError: continue
            sys.stdout.write('\n'.join(rendered) if rendered else 'No saved match.\n')
            return 0
        if args.listen:
            raw=native({'op':'listen','timeout':args.listen_timeout})['text']
        elif args.text: raw=' '.join(args.text)
        elif not sys.stdin.isatty(): raw=sys.stdin.read(h.MAX_INPUT_CHARS+1)
        else: parser.error('Supply quoted text, pipe text on stdin, or use --listen.')
        cleaned=raw if args.no_normalize else normalize(raw)
        sid=store.select_session(args.session,args.continuing)
        row_id=store.begin(raw,cleaned,args.engine,model,sid)
        if len(raw)>h.MAX_INPUT_CHARS: raise h.HarnessError(f'Input exceeds {h.MAX_INPUT_CHARS} characters.')
        with store.session(sid,args.turns) as session:
            past=history_messages(session['turns'],args.history_chars)
            reply=h.request_reply(cleaned,engine=args.engine,model=model,effort=args.effort,timeout=args.timeout,
                                  log_path=args.usage_log,events=events,history=past)
            store.finish(row_id,reply,events)
            exchange={'raw_input':raw,'normalized_input':cleaned,'reply':reply.model_dump(),'engine':args.engine,'model':model}
            store.save_session(session,exchange,args.turns)
            sys.stdout.write(h.display_text(reply)); sys.stdout.flush()
            if args.execute and reply.execution_payload:
                execution=native({'op':'exec','command':reply.execution_payload,'timeout':args.exec_timeout})
                store.finish(row_id,reply,events,execution=execution)
                session['turns'][-1]['execution_result']=execution
                atomic_json(store.sessions/(sid+'.json'),session)
                if execution.get('stdout'): sys.stdout.write(execution['stdout'])
                if execution.get('stderr'): sys.stderr.write(execution['stderr'])
                if execution.get('timed_out'): print('Command timed out.',file=sys.stderr)
                if execution.get('truncated'): print('Command output was truncated at the capture limit.',file=sys.stderr)
                code=int(execution.get('exit_code',0))
                return min(255,code if code>=0 else 128-code)
        return 0
    except KeyboardInterrupt:
        if store and row_id: store.finish(row_id,reply,events,error='Stopped.',execution=execution,status='interrupted')
        print('Stopped.',file=sys.stderr); return 130
    except (h.HarnessError,ValueError) as exc:
        if store and row_id: store.finish(row_id,reply,events,error=str(exc),execution=execution)
        print(str(exc),file=sys.stderr); return 2
    except Exception as exc:
        message=f'Unexpected client error ({type(exc).__name__}).'
        if store and row_id:
            try: store.finish(row_id,reply,events,error=message,execution=execution)
            except Exception: pass
        print(message,file=sys.stderr); return 2
    finally:
        if store: store.close()
