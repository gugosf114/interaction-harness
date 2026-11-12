"""Open models through one OpenAI-compatible key (shortcut g3): OpenRouter and the like.

Any base URL plus a key. OpenRouter's Chat Completions accepts response_format
json_schema (the four fields), temperature, seed, stop, and provider routing. It
has no single service-tier field; the client maps --service-tier to provider.sort
(price/latency/throughput) and to the :nitro variant for priority endpoints. Web
search is the `web` plugin (engine auto), which returns url_citation annotations.
Field names checked against the OpenRouter API reference on 2026-11-11.

No key exists yet. To turn the lane on, in native Termux:
    export OPENROUTER_API_KEY=...        # from https://openrouter.ai/keys
    python ~/interaction-harness/save_lane_key.py openrouter
Optionally first: export OPENROUTER_BASE_URL=... and export OPENROUTER_MODEL=...
Until the key is saved the lane answers with one line naming the missing key.
"""
from __future__ import annotations

import json

import lane_base as base
from lane_base import Call, Lane, LaneError, Sent

BASE = 'https://openrouter.ai/api/v1'
MODEL = 'z-ai/glm-5.3'              # a strong open model on OpenRouter; override with OPENROUTER_MODEL
SORTS = {'price', 'latency', 'throughput'}
KNOB_TOKENS = {'temperature': ('temperature',), 'seed': ('seed',), 'stop': ('stop',),
               'service_tier': ('service_tier', 'provider', 'sort')}


def send(lane: Lane, call: Call) -> Sent:
    from openai import OpenAI, BadRequestError
    base.check_media(lane, call.messages)
    client = call.client
    key = base.lane_key(lane) if client is None else 'test'
    if client is None:
        client = OpenAI(api_key=key, base_url=base.lane_base_url(lane), timeout=call.timeout, max_retries=0,
                        default_headers={'HTTP-Referer': 'https://interaction-harness.local',
                                         'X-Title': 'interaction-harness'})
    messages = [{'role': 'system', 'content': page} for page in call.system_pages]
    messages.append({'role': 'system', 'content': base.lane_note(lane, call.web)})
    for message in call.messages:
        messages.append({'role': message['role'], 'content': message['content']})
    params = {'model': call.model, 'messages': messages,
              'response_format': {'type': 'json_schema',
                                  'json_schema': {'name': 'interaction_reply', 'strict': True, 'schema': call.schema}}}
    extra = {}
    kb = call.knobs
    sent = {}
    if kb.temperature is not None:
        params['temperature'] = kb.temperature; sent['temperature'] = True
    if kb.seed is not None:
        params['seed'] = kb.seed; sent['seed'] = True
    if kb.stop is not None:
        params['stop'] = list(kb.stop); sent['stop'] = True
    if kb.service_tier is not None:
        tier = kb.service_tier.lower()
        if tier in ('priority', 'nitro'):
            extra['provider'] = {'sort': 'throughput'}
            params['model'] = call.model if call.model.endswith(':nitro') else call.model + ':nitro'
        elif tier in SORTS:
            extra['provider'] = {'sort': tier}
        else:
            base.knob_refused(call, lane, 'service_tier',
                              f'OpenRouter has no tier {kb.service_tier!r}; use price, latency, throughput or priority.')
        if 'provider' in extra:
            sent['service_tier'] = True
    if kb.prefill:
        base.say_once(call, f'[{lane.engine}] --prefill is set on the answer text; the opening is forced after the reply.')
    if call.web:
        extra['plugins'] = [{'id': 'web', 'max_results': call.web_max}]
    attempts = len(sent) + 1
    while True:
        try:
            response = client.chat.completions.create(**params, extra_body=extra or None)
            break
        except BadRequestError as exc:
            message = str(getattr(exc, 'body', None) or exc)
            attempts -= 1
            dropped = attempts > 0 and _drop(call, params, extra, sent, message)
            if not dropped:
                raise LaneError(f'The openrouter lane rejected this request: '
                                f'{base.provider_message(message)}') from exc
    text = (response.choices[0].message.content or '') if response.choices else ''
    sources, search = _sources(response)
    meta = _usage(response)
    report = {'web_search_requests': search} if search else None
    return Sent(raw_json=text, usage=meta, response_id=getattr(response, 'id', None), sources=sources,
                search=search, provider_report=report)


def _drop(call, params, extra, sent, message):
    low = message.lower()
    for name in list(sent):
        if any(token in low for token in KNOB_TOKENS.get(name, (name,))):
            base.knob_refused(call, LANE, name, base.provider_message(message))
            sent.pop(name)
            if name == 'service_tier':
                extra.pop('provider', None)
                params['model'] = params['model'].replace(':nitro', '')
            else:
                params.pop(name, None)
            return True
    return False


def _sources(response):
    sources, search = [], 0
    choice = response.choices[0] if response.choices else None
    message = getattr(choice, 'message', None) if choice else None
    for ann in (getattr(message, 'annotations', None) or []):
        data = ann.model_dump() if hasattr(ann, 'model_dump') else dict(ann)
        cite = data.get('url_citation') or {}
        if cite.get('url'):
            sources.append({'url': cite['url'], 'title': cite.get('title') or cite['url']})
    usage = getattr(response, 'usage', None)
    details = (getattr(usage, 'model_dump', lambda **_: {})(exclude_none=True) if usage else {})
    server = details.get('server_tool_use_details') or details.get('server_tool_use') or {}
    if isinstance(server, dict):
        search = int(server.get('web_search_requests') or 0)
    if not search and sources:
        search = 1
    return sources, search


def _usage(response):
    usage = getattr(response, 'usage', None)
    if usage is None:
        return {}
    try:
        data = usage.model_dump(exclude_none=True)
    except AttributeError:
        data = dict(usage)
    out = {'input_tokens': data.get('prompt_tokens', 0), 'output_tokens': data.get('completion_tokens', 0),
           'total_tokens': data.get('total_tokens', 0)}
    details = data.get('prompt_tokens_details') or {}
    if isinstance(details, dict) and details.get('cached_tokens'):
        out['cache_read_input_tokens'] = details['cached_tokens']
    return out


LANE = Lane(engine='openrouter', shortcut='g3', default_model=MODEL, send=send, reply_mode='json',
            base_url=BASE, key_env='OPENROUTER_API_KEY', key_file='openrouter-api-key',
            base_env='OPENROUTER_BASE_URL', base_file='openrouter-base-url', model_env='OPENROUTER_MODEL',
            web='web', images=False)
