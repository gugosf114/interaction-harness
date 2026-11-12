"""API capability switches. Provider definitions are deterministic and kept separate from operator pages."""
import copy
import hashlib
import json
from pathlib import Path

BOTH = ('openai', 'anthropic')
# name: (lanes, default, purpose, default reason)
TOOLS = {
    'web_search': (BOTH, True, 'Search the web.', 'Keeps the existing lookup behavior.'),
    'web_fetch': (BOTH, True, 'Read a web page.', 'Keeps the existing lookup behavior.'),
    'history_cache': (('anthropic',), True, 'Cache the growing chat.', 'Cuts repeated input without changing the answer.'),
    'memory': (('anthropic',), False, 'Read and write model notes on this phone.', 'Adds lasting notes across chats.'),
    'code_execution': (BOTH, False, 'Run code in the provider sandbox.', 'Uses a paid hosted runtime.'),
    'computer': (BOTH, False, 'See and act on a named screen.', 'Can change the device.'),
    'browser': (('anthropic',), False, 'Drive the phone browser through its API toolset.', 'Can act on signed-in websites.'),
    'shell': (BOTH, False, 'Run local shell commands with approval.', 'Can change files and devices.'),
    'hosted_shell': (('openai',), False, 'Run commands in an OpenAI container.', 'Uses a paid hosted runtime.'),
    'text_editor': (('anthropic',), False, 'Read and edit local text files.', 'Can change files.'),
    'apply_patch': (('openai',), False, 'Apply model-generated file patches.', 'Can change files.'),
    'mcp_local': (BOTH, False, 'Use the phone MCP tools through agentbridge-call.', 'Exposes device actions to the model.'),
    'mcp_remote': (BOTH, False, 'Let the provider call an authenticated MCP server.', 'Sends tool requests through a remote endpoint.'),
    'files': (BOTH, False, 'Upload attachments once and use provider file IDs.', 'Stores files with the API provider.'),
    'file_search': (('openai',), False, 'Search an uploaded vector store.', 'Uses provider storage and retrieval.'),
    'skills': (BOTH, False, 'Load versioned skills in a hosted runtime.', 'Runs skill instructions and supporting code.'),
    'tool_search': (BOTH, False, 'Find and load deferred tool definitions.', 'Changes how tools enter model context.'),
    'programmatic': (BOTH, False, 'Let sandbox code call other enabled tools.', 'Changes tool execution and adds runtime cost.'),
    'context_editing': (('anthropic',), False, 'Clear old tool results in provider context.', 'Removes old detail from the model input.'),
    'compaction': (BOTH, False, 'Replace older context with a provider summary.', 'Changes the context sent to the model.'),
    'background': (('openai',), False, 'Poll a long-running provider response.', 'Changes storage and request lifetime.'),
    'image_generation': (('openai',), False, 'Generate an image and save its bytes.', 'Adds image-generation charges.'),
    'advisor': (('anthropic',), False, 'Ask a configured advisor model for help.', 'Calls another paid model.'),
    'functions': (BOTH, False, 'Call the local command runner with JSON arguments.', 'Exposes local command execution.'),
    'custom_tools': (('openai',), False, 'Call the local runner with a free-form command.', 'Exposes local command execution.'),
    'namespaces': (('openai',), False, 'Group the local function under a namespace.', 'Changes tool names and discovery.'),
}
ALWAYS_OFF = ('context_editing', 'compaction')
DEFAULT_OPTIONS = {
    'computer_target': 'phone', 'browser_endpoint': 'http://127.0.0.1:9335',
    'mcp_url': '', 'mcp_token_file': '', 'mcp_allowed_tools': [],
    'mcp_bridge_url': '', 'mcp_bridge_token_file': '',
    'vector_store_ids': [], 'openai_skills': [], 'anthropic_skills': [],
    'advisor_model': 'claude-opus-5-5', 'advisor_max_uses': 1,
    'max_tool_steps': 24, 'compaction_threshold': 50000,
    'image_options': {'complexity':'high'},
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def flag_name(name):
    return 'api-advisor' if name=='advisor' else name.replace('_','-')


def write_json(path, value):
    import os, tempfile
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2); stream.write('\n'); name = stream.name
    os.replace(name, path)


class Settings:
    def __init__(self, state, engine, overrides=None, options=None):
        self.state = Path(state); self.engine = engine; self.path = self.state/'tools.json'
        defaults = {name: spec[1] for name, spec in TOOLS.items()}
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            if not isinstance(saved, dict): raise ValueError('tools.json must be an object.')
        else:
            # George's order (2026-11-11): on his own install every tool starts ON and the model picks.
            # The two that squeeze or clear the chat stay off. Any other state folder (tests and proofs
            # use scratch ones) starts from the table above, so each test states its own switches.
            own = self.state.resolve() == (Path(__file__).resolve().parent / 'state').resolve()
            first = {name: name not in ALWAYS_OFF for name in defaults} if own else defaults
            saved = {**first, 'options': copy.deepcopy(DEFAULT_OPTIONS)}
            write_json(self.path, saved)
        self.saved = saved
        self.enabled = {name: saved.get(name, default) for name, default in defaults.items()}
        if any(type(v) is not bool for v in self.enabled.values()):
            raise ValueError('Each tool switch in tools.json must be true or false.')
        self.enabled.update(overrides or {})
        self.asked = {name for name, on in (overrides or {}).items() if on}
        if engine=='openai':
            # OpenAI has one web tool containing search and page-open actions.
            selected=[v for k,v in (overrides or {}).items() if k in ('web_search','web_fetch')]
            if selected and len(set(selected))>1:raise ValueError('OpenAI bundles web search and fetch; their switches must agree.')
            value=selected[0] if selected else self.enabled['web_search'] and self.enabled['web_fetch']
            self.enabled.update(web_search=value,web_fetch=value)
        self.options = {**copy.deepcopy(DEFAULT_OPTIONS), **saved.get('options', {}), **(options or {})}
        self.effective = {name for name, on in self.enabled.items() if on and engine in TOOLS[name][0]}
        # A tool that is on but has nothing to work with steps aside instead of stopping the call.
        # Asked for by flag, it stays in, and the missing setting is reported as an error.
        needs = {'skills': bool(self.options['anthropic_skills' if engine == 'anthropic' else 'openai_skills']),
                 'file_search': bool(self.options['vector_store_ids']),
                 'mcp_remote': str(self.options['mcp_url']).startswith('https://')}
        self.unset = {name for name, ready in needs.items() if name in self.effective and not ready and name not in self.asked}
        # OpenAI takes one of these three in a request: it answers "code_interpreter and shell with an
        # OpenAI-managed container cannot be used together" for code execution with either shell, and it has
        # one shell tool type. The one asked for by flag stays. With none asked, skills that are set up keep
        # the hosted shell; otherwise code execution stays, and the phone's commands still run through the
        # function and custom tools.
        group = ('code_execution', 'shell', 'hosted_shell')
        present = [name for name in group if name in self.effective]
        chosen = [name for name in present if name in self.asked]
        if engine == 'openai' and len(present) > 1 and len(chosen) < 2:
            keep = chosen[0] if chosen else ('hosted_shell' if 'skills' in self.effective - self.unset and 'hosted_shell' in present else present[0])
            self.unset.update(name for name in present if name != keep)
        self.effective -= self.unset
        if 'skills' in self.effective: self.effective.add('code_execution' if engine == 'anthropic' else 'hosted_shell')
        if 'programmatic' in self.effective:
            self.effective.add('functions')
            if engine == 'anthropic': self.effective.add('code_execution')
        if 'tool_search' in self.effective or 'namespaces' in self.effective: self.effective.add('functions')
        self.availability_path = self.state/'tools-availability.json'
        self.availability = json.loads(self.availability_path.read_text()) if self.availability_path.exists() else {}

    def on(self, name): return name in self.effective

    def unavailable(self, name, model, error):
        self.availability.setdefault(self.engine, {}).setdefault(model, {})[name] = str(error)
        write_json(self.availability_path, self.availability)

    def available(self,name,model):
        errors=self.availability.get(self.engine,{}).get(model,{})
        if name in errors:
            del errors[name];write_json(self.availability_path,self.availability)

    def listing(self, model):
        errors = self.availability.get(self.engine, {}).get(model, {})
        lines = []
        for name, (lanes, default, purpose, reason) in TOOLS.items():
            state = 'on' if self.on(name) else 'off'
            if self.engine not in lanes: status = 'not offered on this lane'
            elif name in errors: status = 'unavailable: ' + errors[name]
            elif name in self.unset:
                status = {'skills': 'switched on; steps aside until a skill is listed in tools.json options',
                          'file_search': 'switched on; steps aside until vector_store_ids is set in tools.json options',
                          'mcp_remote': 'switched on; steps aside until an https mcp_url is set in tools.json options',
                          'code_execution': 'switched on; steps aside: OpenAI takes one of code execution, shell, hosted shell',
                          'shell': 'switched on; steps aside: OpenAI takes one of code execution, shell, hosted shell',
                          'hosted_shell': 'switched on; steps aside: OpenAI takes one of code execution, shell, hosted shell'}[name]
            else: status = 'enabled' if self.on(name) else 'available to enable'
            lines.append(f'{flag_name(name)}: {state}; {"/".join(lanes)}; {purpose} {status}')
        return '\n'.join(lines)+'\n'


COMMAND_SCHEMA = {'type': 'object', 'properties': {'command': {'type': 'string'}},
                  'required': ['command'], 'additionalProperties': False}


def provider_tools(settings, base, mcp_catalog=()):
    """Build once, in fixed order. No paths, clocks, results or random IDs enter definitions."""
    engine=settings.engine; on=settings.on; options=settings.options
    tools=copy.deepcopy(base)
    if engine=='anthropic':
        tools=[t for t in tools if (t.get('name')!='web_search' or on('web_search'))
               and (t.get('name')!='web_fetch' or on('web_fetch'))]
    elif not (on('web_search') or on('web_fetch')): tools=[t for t in tools if t['type']!='web_search']
    specs = {
        'openai': {
            'code_execution': {'type':'code_interpreter','container':{'type':'auto'}},
            'computer': {'type':'computer'}, 'shell': {'type':'shell','environment':{'type':'local'}},
            'hosted_shell': {'type':'shell','environment':{'type':'container_auto'}},
            'apply_patch': {'type':'apply_patch'}, 'file_search': {'type':'file_search','vector_store_ids':options['vector_store_ids']},
            'tool_search': {'type':'tool_search'}, 'programmatic': {'type':'programmatic_tool_calling'},
            'image_generation': {'type':'image_generation',**options['image_options']},
            'custom_tools': {'type':'custom','name':'local_command','description':'Run a command on the phone through the approval gate.','format':{'type':'text'}},
        },
        'anthropic': {
            'memory': {'type':'memory_20250818','name':'memory'},
            'code_execution': {'type':'code_execution_20260521','name':'code_execution'},
            'computer': {'type':'computer_toolset_20260801','configs':{
                'right_click':{'enabled':False},'middle_click':{'enabled':False},'cursor_position':{'enabled':False}}},
            'browser': {'type':'browser_toolset_20260801','configs':{'javascript_exec':{'enabled':True},'file_upload':{'enabled':True},'read_console':{'enabled':True},'read_network':{'enabled':True}}},
            'shell': {'type':'bash_20250124','name':'bash'},
            'text_editor': {'type':'text_editor_20250728','name':'str_replace_based_edit_tool'},
            'tool_search': {'type':'tool_search_tool_regex_20251119','name':'tool_search_tool_regex'},
            'advisor': {'type':'advisor_20260301','name':'advisor','model':options['advisor_model'],'max_uses':options['advisor_max_uses']},
        },
    }
    if on('shell') and on('hosted_shell'):
        raise ValueError('Choose local shell or hosted shell for a request; OpenAI uses one shell tool type.')
    if engine=='openai' and on('code_execution') and (on('shell') or on('hosted_shell')):
        raise ValueError('Choose code execution or a shell for a request; OpenAI refuses the two together.')
    for name in TOOLS:
        if on(name) and name in specs[engine]:
            definition=copy.deepcopy(specs[engine][name])
            if name=='hosted_shell' and on('skills'): definition['environment']['skills']=copy.deepcopy(options['openai_skills'])
            tools.append(definition)
    functions=[]
    if on('functions'):
        functions.append({'name':'harness_command','description':'Run a local shell command in native Termux, with operator approval. Returns exit_code, stdout and stderr.',
                          'input_schema':COMMAND_SCHEMA})
    if on('mcp_local'):
        for entry in sorted(mcp_catalog,key=lambda x:x['name']):
            functions.append({'name':'phone__'+entry['name'],'description':entry.get('description',''), 'input_schema':entry['inputSchema']})
    namespaced=[]
    for definition in functions:
        if engine=='openai':
            definition={'type':'function','name':definition['name'],'description':definition['description'],
                        'parameters':definition['input_schema'],'strict':False}
        if on('tool_search'):definition['defer_loading']=True
        if on('programmatic'):
            definition['allowed_callers']=['direct','programmatic' if engine=='openai' else 'code_execution_20260521']
        if engine=='openai' and on('namespaces'):
            namespaced.append(definition)
        else:tools.append(definition)
    if namespaced:tools.append({'type':'namespace','name':'local','description':'Phone command tools.','tools':namespaced})
    if on('mcp_remote') and not options['mcp_url'].startswith('https://'):
        if 'mcp_remote' in getattr(settings,'asked',()):raise ValueError('Remote MCP needs an HTTPS mcp_url in tools.json options.')
    elif on('mcp_remote'):
        if engine=='openai':
            definition={'type':'mcp','server_label':'phone','server_url':options['mcp_url'],'require_approval':'never'}
            if options['mcp_allowed_tools']: definition['allowed_tools']=options['mcp_allowed_tools']
            tools.append(definition)
        else:
            definition={'type':'mcp_toolset','mcp_server_name':'phone'}
            if options['mcp_allowed_tools']:
                definition.update(default_config={'enabled':False},configs={n:{'enabled':True} for n in options['mcp_allowed_tools']})
            tools.append(definition)
    return tools


def cache_history(params, enabled=True):
    """Automatic caching uses one of four markers and follows the growing history."""
    if not enabled:return params
    def markers(obj):
        if isinstance(obj,dict):return int('cache_control' in obj)+sum(markers(v) for v in obj.values())
        if isinstance(obj,list):return sum(markers(v) for v in obj)
        return 0
    if markers(params)>=4:raise ValueError('History caching needs one free Anthropic cache marker.')
    params['cache_control']={'type':'ephemeral'}
    return params
