"""Editable first-party prices. Hide money whenever a charge cannot be priced."""
import json
from pathlib import Path

PRICES = Path(__file__).with_name('prices.json')


def price(event, prices=None, service_tier=None):
    if prices is None:
        try: prices = json.loads(PRICES.read_text()).get('models', {})
        except (OSError, ValueError): return None
    reports = (event.get('lookup_counts') or {}).get('provider_reports') or []
    ids = event.get('provider_response_ids') or []
    by_id = {r.get('response_id'):r for r in reports if r.get('response_id') in ids}
    if len(by_id) > 1:
        # Long-context rates are per request, not per aggregate model turn.
        values = []
        for ident, report in by_id.items():
            part = {**event, 'usage':report.get('usage') or {}, 'response_id':ident,
                    'provider_response_ids':[ident],
                    'lookup_counts':{**event.get('lookup_counts',{}), 'provider_reports':[]}}
            values.append(price(part, prices, service_tier))
        return sum(values) if all(v is not None for v in values) else None
    entry = prices.get(event.get('model_returned') or event.get('model_requested'))
    if not entry or not entry.get('verified'): return None
    usage = event.get('usage') or {}
    rates = entry.get('usd_per_million_tokens')
    if not usage or not rates: return None
    # Runtime/tool bills need a priced receipt. Local execution has no provider fee.
    for use in event.get('api_tool_uses') or []:
        if use.get('tool') not in ('functions','custom_tools','shell','text_editor','apply_patch','memory','mcp_local','computer','browser','namespaces','background','native_command'):
            return None
    tier = service_tier or usage.get('service_tier')
    if tier not in (None, 'standard', 'default', 'auto', 'fast'): return None
    if tier == 'fast':
        if not entry.get('fast'): return None
        rates = entry['fast']['usd_per_million_tokens']
    inputs = usage.get('input_tokens',0)
    read = usage.get('cache_read_input_tokens',0) + (usage.get('input_tokens_details') or {}).get('cached_tokens',0)
    creation = usage.get('cache_creation_input_tokens',0)
    full_input = inputs + (creation+read if event.get('engine') == 'anthropic' else 0)
    long = entry.get('long_context') or {}
    if full_input > long.get('above_input_tokens',float('inf')):
        rates = long['usd_per_million_tokens']
    openai_write = (usage.get('input_tokens_details') or {}).get('cache_write_tokens', 0)
    if event.get('engine') == 'openai': inputs -= read + openai_write
    if creation and 'cache_write_5m' not in rates: return None
    # Unknown input modalities have separate rates; do not guess their bill.
    details = usage.get('input_tokens_details') or {}
    if any(v for k,v in details.items() if k not in ('cached_tokens','cache_write_tokens') and isinstance(v,(int,float))): return None
    if any(v for k,v in (usage.get('output_tokens_details') or {}).items() if k not in ('reasoning_tokens','thinking_tokens') and isinstance(v,(int,float))): return None
    total = inputs*rates['input'] + read*rates['cache_read'] + usage.get('output_tokens',0)*rates['output']
    if openai_write:
        if 'cache_write_30m' not in rates: return None
        total += openai_write*rates['cache_write_30m']
    detail = usage.get('cache_creation') or {}
    hour = detail.get('ephemeral_1h_input_tokens',0)
    if hour and 'cache_write_1h' not in rates: return None
    total += (creation-hour)*rates.get('cache_write_5m',0) + hour*rates.get('cache_write_1h',0)
    total /= 1000000
    counts = event.get('lookup_counts') or {}
    server = usage.get('server_tool_use') or {}
    if any(v for k,v in server.items() if k not in ('web_search_requests','web_fetch_requests') and v): return None
    search = server.get('web_search_requests',0)
    if event.get('engine') == 'openai':
        ids = event.get('provider_response_ids') or [event.get('response_id')]
        calls = [x for x in counts.get('calls',[]) if x.get('response_id') in ids]
        if any(x.get('kind') not in ('search',) for x in calls): return None
        search = len(calls)
    if search:
        if 'usd_per_web_search' not in entry: return None
        total += search*entry['usd_per_web_search']
    return total


def total(events, service_tier=None):
    billed = [e for e in events if e.get('kind') != 'recall']
    if not billed: return None
    values = [price(e, service_tier=service_tier if not e.get('kind') else None) for e in billed]
    return sum(values) if all(v is not None for v in values) else None


def records(state, sid):
    path = Path(state)/'chat-cost.jsonl'
    if not path.exists(): path = Path(state)/'chat-status.jsonl'
    try: rows = [json.loads(x) for x in path.read_text().splitlines()]
    except (OSError,ValueError): return []
    return [r for r in rows if r.get('session') == sid]


def record(state, sid, amount):
    import os
    fd = os.open(Path(state)/'chat-cost.jsonl',os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
    with os.fdopen(fd,'a') as file:
        file.write(json.dumps({'session':sid,'cost_usd':amount})+'\n')


def old_session(state, sid):
    """An older session without cost receipts has an unknown starting bill."""
    try: rows = [json.loads(x) for x in (Path(state)/'chat-cost.jsonl').read_text().splitlines()]
    except (OSError,ValueError): rows = []
    if not any(r.get('session') == sid for r in rows): record(state,sid,None)


def prior_cost(state, sid):
    values = [r.get('cost_usd') for r in records(state,sid)]
    return sum(values) if all(v is not None for v in values) else None


def report(state, sid):
    rows = records(state,sid)
    if not rows: return 'No priced turn in this session.'
    amount = rows[-1].get('cost_usd')
    if amount is None: return 'Price unknown for this turn.'
    text = f'Turn ${amount:.5f}'
    session = prior_cost(state,sid)
    if session is not None: text += f' · session ${session:.5f}'
    return text + ' (model, judge and add-ons).'
