"""Named tool-use claims need a matching receipt from the current turn."""
import re
import shlex
from pathlib import Path
from lookup_gate import QUOTED, DENIAL

NAMES = {
 'memory':r'(?:the )?memory (?:tool|notes)', 'code_execution':r'(?:the )?(?:code interpreter|code execution|hosted sandbox)',
 'computer':r'(?:the )?computer (?:tool|use)', 'browser':r'(?:the )?browser tool',
 'shell':r'(?:the )?(?:shell|bash) tool', 'hosted_shell':r'(?:the )?hosted shell',
 'text_editor':r'(?:the )?text editor tool', 'apply_patch':r'(?:the )?apply[_ -]patch(?: tool)?',
 'mcp_local':r'(?:the )?(?:local MCP|agentbridge-call)', 'mcp_remote':r'(?:the )?remote MCP',
 'files':r'(?:the )?Files API', 'file_search':r'(?:the )?file search tool',
 'skills':r'(?:a |the )?(?:hosted |API )?skill', 'tool_search':r'(?:the )?tool search',
 'programmatic':r'programmatic tool calling', 'context_editing':r'context editing',
 'compaction':r'(?:the )?(?:provider )?compaction', 'image_generation':r'(?:the )?image generation tool',
 'advisor':r'(?:the )?advisor tool', 'functions':r'harness_command', 'custom_tools':r'local_command',
}


def violation(answer, receipts):
    used={r['tool'] for r in receipts if r.get('status')=='success' or
          r.get('status')=='failed' and (r.get('execution',{}).get('approved') or r.get('provider'))}
    # Existing approved shell commands can use these same local tools without
    # going through an API-specific function. Their real command record counts.
    aliases={'agentbridge-call':'mcp_local','mcp':'mcp_local','screen':'computer',
             'edit-exact':'text_editor','apply_patch':'apply_patch','page-text':'browser'}
    for record in receipts:
        execution=record.get('execution',{})
        if execution.get('approved') is not True or execution.get('exit_code')!=0:continue
        used.add('shell')
        try:
            parts=shlex.split(record.get('command',''))
            if parts and Path(parts[0]).name in aliases:used.add(aliases[Path(parts[0]).name])
        except ValueError:pass
    text=QUOTED.sub(' ',answer)
    for sentence in re.split(r'(?<=[.!?])\s+|\n+',text):
        for name, pattern in NAMES.items():
            claim=re.search(r'\b(?:I|we)(?: have|[’\x27]ve)?(?:\s+(?:just|also|already|successfully))*\s+(?:used|called|ran|invoked|consulted)\s+'+pattern+r'\b',sentence,re.I)
            if claim and not DENIAL.search(sentence[:claim.start()]) and name not in used:
                return 'The client recorded no successful '+name+' use this turn. Remove that tool-use claim.'
    return None
