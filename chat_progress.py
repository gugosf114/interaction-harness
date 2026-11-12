"""Public phase names only. Never forward model text, thinking, or partial replies."""
import json

listener = None
usage_listener = None
response_listener = None

def record_usage(event):
    if usage_listener is not None: usage_listener(event)


def phase(name, detail=''):
    if listener is not None:
        listener(name, detail)


def watching():
    return listener is not None


def public_event(event):
    """Accept only named tool/status metadata from the providers' stream events."""
    kind = getattr(event, 'type', '')
    if kind == 'response.created' and response_listener is not None:
        response_listener('openai', getattr(getattr(event, 'response', None), 'id', None))
    if kind.startswith('response.web_search_call.'):
        phase('Searching the web')
    elif kind in ('response.output_item.added', 'response.output_item.done'):
        item = getattr(event, 'item', None)
        if getattr(item, 'type', '') == 'web_search_call':
            action = getattr(item, 'action', None)
            query = getattr(action, 'query', '') or ', '.join(getattr(action, 'queries', []) or [])
            phase('Searching the web', query or getattr(action, 'url', '') or '')
    elif kind in ('content_block_start', 'content_block_stop'):
        block = getattr(event, 'content_block', None)
        if getattr(block, 'type', '') == 'server_tool_use':
            name = getattr(block, 'name', '')
            data = getattr(block, 'input', {})
            if isinstance(data, str):
                try: data = json.loads(data)
                except ValueError: data = {}
            if name in ('web_search', 'web_fetch'):
                phase('Searching the web' if name == 'web_search' else 'Reading a web page',
                      (data or {}).get('query') or (data or {}).get('url') or '')
            elif name == 'advisor':
                phase('Waiting on advisor')
