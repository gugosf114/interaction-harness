"""CLI workflow: normalize, remember, request, gate, record, display, confirm."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys

import harness as h
import advisor
import corrections
import reply_judge
import recall_cli
import stamp
import senses_cli
import api_tools_cli
import lane_mods
import extra_lanes
import knobs as knobs_mod
import chat_screen
from chat_progress import phase

ALL_ENGINES = ['openai', 'anthropic', *extra_lanes.LANES.keys()]
from execution_images import prepare_execution
from lookup_gate import turn_metadata
from phonetics import normalize
from storage import (Store, history_messages, atomic_json,
                     confirmed_execution, successful_execution, execution_message)


# History budget per engine, in characters. Measured live on 2026-11-11: claude-opus-5-5 accepts
# 1,000,000 input tokens; gpt-6.1-sol accepted 380,000 and refused 950,000. Each budget leaves room
# for the 128,000-token answer and the system pages, at about 3 characters per token.
HISTORY_CHARS_DEFAULT = {'anthropic': 2400000, 'openai': 650000}

def native(request):
    if request.get('op') == 'exec': phase('Running a command', request.get('command', ''))
    fd = os.environ.get('HARNESS_BRIDGE_FD')
    if fd is None: raise h.HarnessError('Use the Termux harness launcher for --exec or --listen.')
    try:
        with socket.socket(fileno=os.dup(int(fd))) as sock:
            with sock.makefile('rwb') as stream:
                from chat_bridge import exchange
                result = exchange(stream, request)
                if result is None: raise h.HarnessError('The Termux command bridge closed.')
    except (OSError, ValueError) as exc:
        raise h.HarnessError('The Termux command bridge failed.') from exc
    if result.get('error'): raise h.HarnessError(result['error'])
    return result


def run_chat(args, model):
    import chat_screen
    return chat_screen.run_chat(args, model, sys.modules[__name__])


def main(argv=None, *, literal=False):
    parser=argparse.ArgumentParser(description='Direct answers, bounded memory, optional confirmed Termux execution.')
    parser.epilog='Screen: in an approved --loop command, screen snap or look PATH attaches the file to the next model turn. Run card screen for targets and commands.'
    parser.epilog+=' Stamp: /off stamp and /on stamp switch the operator_rules_stamp record that follows the request on every call. Type either one in a chat or as the whole question.'
    parser.add_argument('--engine',choices=ALL_ENGINES,default=os.environ.get('DEFAULT_ENGINE','openai'))
    parser.add_argument('--model',default=None)
    parser.add_argument('--effort',choices=['low','medium','high','xhigh','max'],default=h.DEFAULT_EFFORT,help='Reasoning effort on either engine (default: high).')
    parser.add_argument('--chat','--interactive',dest='chat',action='store_true',help='Stay open for multiple turns; automatic on an interactive terminal with no input.')
    parser.add_argument('--plain',action='store_true',help='Turn off chat colors (also NO_COLOR).')
    parser.add_argument('--timeout',type=float,default=1800)
    parser.add_argument('--usage-log',type=Path,default=h.STATE/'usage.jsonl')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--new',action='store_true',help='Fresh isolated turn (default); its ID becomes available to --continue.')
    group.add_argument('-c','--continue',dest='continuing',action='store_true')
    group.add_argument('--session',metavar='NAME')
    parser.add_argument('--turns',type=int,default=100000,help='Exchanges kept in the session (1–1000000). The character budget is the real limit.')
    parser.add_argument('--history-chars',type=int,default=None,help='Maximum prior-history characters sent to the model (0–4000000). Default: 2400000 on anthropic, 650000 on openai, sized to each model window measured live on 2026-11-11.')
    parser.add_argument('--no-normalize',action='store_true',help='Send exact typed input without phonetic substitutions.')
    parser.add_argument('-x','--exec',dest='execute',action='store_true',help='Ask y/N before running the returned command in native Termux.')
    parser.add_argument('--exec-timeout',type=int,default=3600)
    parser.add_argument('--loop',action='store_true',help='Execute approved commands and feed results back until completion or the turn ceiling; implies --exec.')
    parser.add_argument('--max-turns',type=int,default=200,help='Maximum model turns per --loop task, including the final answer (1–1000; default 200).')
    parser.add_argument('-y','--yes',action='store_true',help='Explicitly approve every command for this invocation; requires --exec or --loop.')
    parser.add_argument('--recall',metavar='QUERY',help='Search local history without an API call.')
    parser.add_argument('-l','--listen',action='store_true',help='Use Android speech recognition through Termux:API.')
    parser.add_argument('--listen-timeout',type=int,default=90)
    senses_cli.add_flags(parser)
    advisor.add_flags(parser)
    api_tools_cli.add_flags(parser)
    recall_cli.add_flags(parser)
    knobs_mod.add_flags(parser)
    parser.add_argument('--both',action='store_true',help='Ask every working lane the same question at once.')
    parser.add_argument('--lanes',default=None,metavar='A,B,C',help='With --both: the comma-separated lane set. Default: every lane with a key.')
    parser.add_argument('text',nargs='*',help='Quoted input, or pipe text on stdin.')
    args=parser.parse_args(argv)
    senses_cli.validate_args(parser,args)
    advisor.validate_args(parser,args)
    recall_cli.validate_args(parser,args)
    knobs_mod.validate(parser,args)
    if args.engine not in set(ALL_ENGINES): parser.error('DEFAULT_ENGINE must be one of: '+', '.join(ALL_ENGINES)+'.')
    if not 1<=args.timeout<=3600: parser.error('--timeout must be between 1 and 3600 seconds.')
    if not 1<=args.turns<=1000000: parser.error('--turns must be between 1 and 1000000.')
    args._history_chars_default = args.history_chars is None
    if args.history_chars is None: args.history_chars=HISTORY_CHARS_DEFAULT.get(args.engine,650000)
    if not 0<=args.history_chars<=4000000: parser.error('--history-chars must be between 0 and 4000000.')
    if not 1<=args.exec_timeout<=86400: parser.error('--exec-timeout must be between 1 and 86400.')
    if not 1<=args.max_turns<=1000: parser.error('--max-turns must be between 1 and 1000.')
    if args.yes and not (args.execute or args.loop):parser.error('--yes requires --exec or --loop.')
    if args.loop:args.execute=True
    if not 1<=args.listen_timeout<=180: parser.error('--listen-timeout must be between 1 and 180.')
    if args.listen and args.text: parser.error('Use --listen or typed text, not both.')
    if args.chat and (args.listen or args.recall is not None): parser.error('--chat uses typed input; use --listen or --recall separately.')
    if args.recall is not None and (args.text or args.listen or args.execute): parser.error('--recall searches history without input or execution.')
    if args.engine in extra_lanes.LANES:
        model=extra_lanes.lane_model(extra_lanes.LANES[args.engine],args.model)
    else:
        model=args.model or os.environ.get('OPENAI_MODEL' if args.engine=='openai' else 'ANTHROPIC_MODEL') or (h.DEFAULT_MODEL if args.engine=='openai' else h.ANTHROPIC_MODEL)
    if args.advisor is not None:return advisor.run(args,model)
    if args.tools:
        try:sys.stdout.write(api_tools_cli.settings(args,h.STATE).listing(model));return 0
        except (ValueError,OSError) as exc:print(str(exc),file=sys.stderr);return 2
    seeded=recall_cli.start_session(args)  # --fork, --from and the golden session seed a new session
    if seeded is not None:return seeded
    if args.both:
        import both
        if args.listen or args.recall is not None or args.execute or args.loop:
            parser.error('--both answers text questions; it does not use --listen, --recall, --exec or --loop.')
        if args.text: question=' '.join(args.text)
        elif not sys.stdin.isatty(): question=sys.stdin.read(h.MAX_INPUT_CHARS+1)
        else: parser.error('Supply a question for --both.')
        return both.run(args,question)
    if args.chat or (not args.text and not args.listen and args.recall is None and sys.stdin.isatty()):
        return run_chat(args,model)
    switched=reply_judge.typed(args)  # /on judge, /off judge typed as the whole question
    if switched is not None:return switched
    # /on stamp and /off stamp as the whole question: flip the switch, no model call.
    if not literal and args.text and stamp.is_switch(' '.join(args.text)):return stamp.run_switch(' '.join(args.text),h.STATE)
    corrected=None if literal else corrections.typed(args,model)  # /wrong WORDS saves the correction case and becomes a loop task for this lane
    if corrected is not None:return corrected
    store=None; row_id=None; events=[]; reply=None; execution=None;second=reply_judge.Second()
    try:
        store=Store(h.STATE)
        if args.recall is not None:
            matches=store.recall(args.recall)
            rendered=[]
            for row in matches:
                raw={k:row[k] for k in ('intent','cleaned_input','direct_answer','execution_payload')}
                # Recall uses the same gate; rejected legacy text is not displayed.
                try:
                    saved=senses_cli.saved_metadata(row)
                    checked=h.validate_reply(json.dumps(raw),row.get('normalized_input') or row.get('raw_input'),
                            execution_confirmed=store.follows_successful_execution(row['session_id'],row['id']))
                    reason=senses_cli.recall_violation(checked,row,saved)
                    if reason:raise h.GateError(reason)
                    rendered.append(h.display_text(checked,saved['sources']))
                except h.GateError: continue
            sys.stdout.write('\n'.join(rendered) if rendered else 'No saved match.\n')
            return 0
        if args.listen:
            raw=native({'op':'listen','timeout':args.listen_timeout})['text']
        elif args.text: raw=' '.join(args.text)
        elif not sys.stdin.isatty(): raw=sys.stdin.read(h.MAX_INPUT_CHARS+1)
        else: parser.error('Supply quoted text, pipe text on stdin, or use --listen.')
        cleaned=raw if args.no_normalize else normalize(raw)
        attached=senses_cli.prepare(args)
        sid=store.select_session(args.session,args.continuing)
        if len(raw)>h.MAX_INPUT_CHARS:
            row_id=store.begin(raw,cleaned,args.engine,model,sid)
            raise h.HarnessError(f'Input exceeds {h.MAX_INPUT_CHARS} characters.')
        last_exit=0;last_exchange=None
        with store.session(sid,args.turns) as session:
            ceiling=args.max_turns if args.loop else 1
            for step in range(1,ceiling+1):
                row_id=None;events=[];reply=None;execution=None
                # The turn number rides in the continuation message, which is saved exactly as sent.
                # Each request is then a byte-for-byte prefix of the next, so provider caches keep hitting.
                chat_screen.begin_turn()
                current=cleaned if step==1 else ('Continue the original task using the recorded execution observation. '
                    f'Return execution_payload null when finished. This is model turn {step} of {ceiling}.')
                current_raw=raw if step==1 else current
                turn_attachments=attached if step==1 else []
                row_id=store.begin(current_raw,current,args.engine,model,sid,attachments=turn_attachments)
                past=api_tools_cli.history(session['turns'],history_messages,args.history_chars,args.engine,
                                          api_tools_cli.settings(args,h.STATE).on('compaction'))
                if args.loop:
                    # Original task and latest actual result survive a small rolling window.
                    # Keep each task's context with its exchange. A new task must not
                    # replace the first history bytes and invalidate the conversation cache.
                    loop_context={'role':'user','content':json.dumps({'client_mode':'agent_loop',
                        'original_task':cleaned,'max_turns':ceiling},ensure_ascii=False)}
                    # A new task always brings its own record, even when its words repeat an earlier task.
                    if step==1 or loop_context not in past:past.append(loop_context)
                    if last_exchange is not None:
                        observation=execution_message(last_exchange)
                        if observation not in past:past.append(observation)
                    # Only the command this reply answers can back a completion claim, and only if it exited 0.
                    supported=last_exchange is not None and successful_execution(last_exchange.get('execution_result'))
                else:
                    latest=session['turns'][-1] if session['turns'] else None
                    notes=len(latest.get('advisor_notes') or []) if latest else 0  # advice sits after the command result
                    supported=bool(latest and successful_execution(latest.get('execution_result')) and len(past)>notes
                                   and past[-1-notes]==execution_message(latest))
                # Past-chat evidence for the operator's message: one data message at the tail, directly before the message.
                recalled=recall_cli.notes(args,session,cleaned,row_id) if step==1 else None
                if recalled:past.append({'role':'user','content':recalled})
                # The judge on the other engine reads the reply before it is shown; a fail gives one corrective retry.
                judged=dict(turns=session['turns'],step=step,loop=args.loop,recall_notes=recalled,
                            renew=lambda:{'api_runtime':api_tools_cli.runtime(args,h.STATE,sid,native)})
                reply=second.request_reply(current,judge_turn=judged,engine=args.engine,model=model,effort=args.effort,timeout=args.timeout,
                                      log_path=args.usage_log,events=events,history=past,execution_confirmed=supported,
                                      request_context=cleaned,web=not args.no_web,web_max=args.web_max,attachments=turn_attachments,
                                      api_runtime=api_tools_cli.runtime(args,h.STATE,sid,native),
                                      native_tool_evidence=api_tools_cli.native_evidence(last_exchange if args.loop else latest),
                                      knobs=knobs_mod.from_args(args))
                store.finish(row_id,reply,events)
                exchange={'raw_input':current_raw,'normalized_input':current,'reply':reply.model_dump(),'engine':args.engine,'model':model}
                if literal and step==1: exchange['literal_input']=True
                if args.loop and step==1:exchange['loop_context']=loop_context['content']
                metadata=turn_metadata(events);exchange.update(metadata)
                second.record(store,row_id,exchange)
                if turn_attachments:exchange['attachments']=turn_attachments
                if recalled:exchange['recall_notes']=recalled
                if args.loop:exchange['loop_step']=step
                store.save_session(session,exchange,args.turns)
                sys.stdout.write(chat_screen.display_reply(reply,metadata['sources']));sys.stdout.flush()
                if not (args.loop and reply.execution_payload):  # the turn's final answer: proof marks, thread tree, voice
                    lane_mods.turn_end(args,session,cleaned,reply,past,lambda:atomic_json(store.sessions/(sid+'.json'),session))
                chat_screen.after_reply(args,session,events)
                if not (args.execute and reply.execution_payload):return last_exit
                request={'op':'exec','command':reply.execution_payload,'timeout':args.exec_timeout}
                if args.yes:request['auto_confirm']=True
                lane_mods.before_command(reply.execution_payload)
                execution=native(request)
                lane_mods.after_command(execution)
                execution=prepare_execution(execution,args.engine,h.STATE,
                    [*past,{'attachments':turn_attachments}])
                store.finish(row_id,reply,events,execution=execution)
                exchange['execution_result']=execution
                atomic_json(store.sessions/(sid+'.json'),session)
                if execution.get('stdout'):sys.stdout.write(chat_screen.command_output(execution['stdout']));sys.stdout.flush()
                if execution.get('stderr'):sys.stderr.write(chat_screen.command_output(execution['stderr'],error=True));sys.stderr.flush()
                if execution.get('timed_out'):print('Command timed out.',file=sys.stderr)
                if execution.get('truncated'):print('Command output was truncated at the capture limit.',file=sys.stderr)
                code=int(execution.get('exit_code',0))
                last_exit=min(255,code if code>=0 else 128-code)
                if not args.loop:return last_exit
                if not confirmed_execution(execution):
                    print('Command declined; agent loop stopped.',file=sys.stderr);return last_exit
                last_exchange=exchange
                if step==ceiling:
                    message=f'Agent loop reached the {ceiling}-turn limit.'
                    store.finish(row_id,reply,events,execution=execution,status='loop_limit',error=message)
                    print(message,file=sys.stderr);return 3
        return last_exit
    except KeyboardInterrupt:
        if store and row_id: store.finish(row_id,reply,events,error='Stopped.',execution=execution,status='interrupted')
        chat_screen.error('Stopped.'); return 130
    except (h.HarnessError,ValueError) as exc:
        if store and row_id: store.finish(row_id,reply,events,error=str(exc),execution=execution)
        chat_screen.error(str(exc)); return 2
    except Exception as exc:
        message=f'Unexpected client error ({type(exc).__name__}).'
        if store and row_id:
            try: store.finish(row_id,reply,events,error=message,execution=execution)
            except Exception: pass
        chat_screen.error(message); return 2
    finally:
        if store: store.close()
