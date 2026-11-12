"""Tool flags and chat switches without changing the operator's tool pages."""
import json
import shlex
import sys

from api_tools_config import Settings, TOOLS, write_json, flag_name


def add_flags(parser):
    parser.add_argument('--tools',action='store_true',help='List API tools, switches, lanes, and recorded availability.')
    for name,(lanes,default,purpose,reason) in TOOLS.items():
        group=parser.add_mutually_exclusive_group()
        group.add_argument('--'+flag_name(name),dest='api_'+name,action='store_true',default=None,help=purpose)
        group.add_argument('--no-'+flag_name(name),dest='api_'+name,action='store_false',help='Disable '+name.replace('_',' ')+'.')
    parser.add_argument('--computer-target',default=None,help='phone, hidden:NAME, laptop, or yana for computer tools.')


def settings(args,state):
    overrides={name:getattr(args,'api_'+name) for name in TOOLS if getattr(args,'api_'+name,None) is not None}
    for name,value in overrides.items():
        if value and args.engine not in TOOLS[name][0]:raise ValueError(name.replace('_','-')+' is not offered on the '+args.engine+' lane.')
    if args.no_web:overrides.update(web_search=False,web_fetch=False)
    options={'computer_target':args.computer_target} if args.computer_target else None
    return Settings(state,args.engine,overrides,options)


def options(args):
    result=[]
    for name in TOOLS:
        value=getattr(args,'api_'+name,None)
        if value is not None:result.append('--'+('' if value else 'no-')+flag_name(name))
    if args.computer_target:result+=['--computer-target',args.computer_target]
    return result


def chat_command(line,args,state,model):
    if line.strip()=='/tools':
        print(settings(args,state).listing(model),end='');return True
    if not line.startswith(('/on','/off')):return False
    words=shlex.split(line)
    if len(words)!=2 or words[0] not in ('/on','/off'):raise ValueError('Use /on NAME or /off NAME.')
    name=words[1].replace('-','_')
    if name=='api_advisor':name='advisor'
    if name not in TOOLS:raise ValueError('Unknown API tool: '+words[1])
    if words[0]=='/on' and args.engine not in TOOLS[name][0]:raise ValueError(name.replace('_','-')+' is not offered on the '+args.engine+' lane.')
    value=words[0]=='/on';config=settings(args,state)
    config.saved[name]=value;write_json(config.path,config.saved)
    setattr(args,'api_'+name,value)
    if args.engine=='openai' and name in ('web_search','web_fetch'):
        for other in ('web_search','web_fetch'):
            config.saved[other]=value;setattr(args,'api_'+other,value)
        write_json(config.path,config.saved)
    print(name.replace('_','-')+(' on.' if value else ' off.'))
    return True


def runtime(args,state,session_id,executor):
    from api_tools_runtime import Runtime
    config=settings(args,state)
    baseline={'web_search','web_fetch','history_cache'}
    if not (config.effective-baseline) and config.on('web_search') and config.on('web_fetch') and (args.engine!='anthropic' or config.on('history_cache')):
        return None
    def approved(request):
        # Give the operator the concrete command before the runner asks y/N.
        print(request['command'],file=sys.stderr)
        return executor(request)
    return Runtime(config,approved,execute=args.execute,auto_confirm=args.yes,exec_timeout=args.exec_timeout,session_id=session_id)


def history(exchanges,builder,budget,engine,enabled=True):
    if not enabled:return builder(exchanges,budget)
    for index in range(len(exchanges)-1,-1,-1):
        context=exchanges[index].get('api_context')
        if context and context.get('engine')==engine:
            # Compaction covers the history preceding that exchange, not its current question.
            return [*context['messages'],*builder(exchanges[index:],budget)]
    return builder(exchanges,budget)


def native_evidence(exchange):
    if not exchange:return None
    result=exchange.get('execution_result') or {}
    if result.get('approved') is not True or result.get('exit_code')!=0:return None
    return {'tool':'native_command','status':'success','source':'native_execution_observation',
            'command':exchange['reply']['execution_payload'],
            'execution':{'approved':True,'exit_code':0}}
