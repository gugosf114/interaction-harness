"""Gemini through Google's own generateContent API (shortcut g5).

The native API, not the OpenAI-compatible one, because only the native API carries
Grounding with Google Search, URL context, inline images and PDFs together with the
strict JSON reply. Field names were checked against the Gemini API reference and a
live call on 2026-11-11:

- systemInstruction parts, contents with role user/model, inline_data parts.
- generationConfig: responseMimeType application/json + responseJsonSchema (the four
  fields), maxOutputTokens, thinkingConfig.thinkingLevel, temperature, seed,
  stopSequences.
- tools: google_search and url_context.
- service_tier at the top level of the body ("priority" or "flex").
- usageMetadata: promptTokenCount, cachedContentTokenCount, candidatesTokenCount,
  thoughtsTokenCount, serviceTier; candidates[].groundingMetadata for sources.

Gemini caches implicitly: the frozen pages go first in systemInstruction and stay
byte-identical, so a repeated prefix reports cachedContentTokenCount.
"""
from __future__ import annotations

import json

import lane_base as base
from lane_base import Call, Lane, LaneError, ProviderHTTPError, Sent

API = 'https://generativelanguage.googleapis.com/v1beta/models/'
MODEL = 'gemini-4-carbon'          # "Our strongest reasoning model" (Google model page), callable by the key on 2026-11-11
MAX_OUTPUT = 65536                  # outputTokenLimit the models list reports for gemini-4-carbon
# Where each knob goes in the body, and the words a refusal uses for it.
KNOB_TOKENS = {'temperature': ('temperature',), 'seed': ('seed',),
               'stop': ('stop_sequences', 'stopsequences', 'stop sequences'),
               'service_tier': ('service_tier', 'servicetier', 'service tier')}
# The provider's exact answer to a request that ends with a model turn (live, 2026-11-11).
PREFILL_REFUSAL = 'HTTP 400: Requests ending with a model turn are not supported.'


def thinking_level(effort: str) -> str:
    return {'low': 'LOW', 'medium': 'MEDIUM'}.get(effort, 'HIGH')


def contents(messages: list) -> list:
    """user/assistant messages as Gemini contents; same-role neighbours are merged."""
    out: list = []
    for message in messages:
        role = 'model' if message['role'] == 'assistant' else 'user'
        parts = [{'text': message['content']}]
        for record in message.get('attachments') or []:
            mime, data = base.attachment_bytes(record)
            parts.append({'inline_data': {'mime_type': mime, 'data': data}})
        if out and out[-1]['role'] == role:
            out[-1]['parts'].extend(parts)
        else:
            out.append({'role': role, 'parts': parts})
    return out


def build_body(lane: Lane, call: Call, knobs: dict) -> dict:
    pages = [*call.system_pages, base.lane_note(lane, call.web)]
    config = {'responseMimeType': 'application/json', 'responseJsonSchema': call.schema,
              'maxOutputTokens': MAX_OUTPUT, 'thinkingConfig': {'thinkingLevel': thinking_level(call.effort)}}
    if 'temperature' in knobs: config['temperature'] = knobs['temperature']
    if 'seed' in knobs: config['seed'] = knobs['seed']
    if 'stop' in knobs: config['stopSequences'] = list(knobs['stop'])
    body = {'systemInstruction': {'parts': [{'text': page} for page in pages]},
            'contents': contents(call.messages), 'generationConfig': config}
    if call.web:
        body['tools'] = [{'google_search': {}}, {'url_context': {}}]
    if 'service_tier' in knobs:
        body['service_tier'] = knobs['service_tier']
    return body


def usage(meta: dict) -> dict:
    prompt = int(meta.get('promptTokenCount') or 0)
    cached = int(meta.get('cachedContentTokenCount') or 0)
    output = int(meta.get('candidatesTokenCount') or 0) + int(meta.get('thoughtsTokenCount') or 0)
    out = {'input_tokens': prompt - cached, 'output_tokens': output,
           'total_tokens': int(meta.get('totalTokenCount') or prompt + output)}
    if cached:
        out['cache_read_input_tokens'] = cached
    if meta.get('serviceTier'):
        out['service_tier'] = meta['serviceTier']
    if meta.get('thoughtsTokenCount'):
        out['thoughts_tokens'] = int(meta['thoughtsTokenCount'])
    return out


def read_reply(payload: dict):
    feedback = payload.get('promptFeedback') or {}
    if feedback.get('blockReason'):
        raise LaneError(f'Gemini refused the request: {feedback["blockReason"]}.')
    candidates = payload.get('candidates') or []
    if not candidates:
        raise LaneError('Gemini returned no answer.')
    first = candidates[0]
    reason = first.get('finishReason')
    if reason not in (None, 'STOP', 'MAX_TOKENS'):
        raise LaneError(f'Gemini stopped with {reason}; no answer was displayed.')
    parts = (first.get('content') or {}).get('parts') or []
    text = ''.join(p.get('text', '') for p in parts if not p.get('thought'))
    grounding = first.get('groundingMetadata') or {}
    sources = [{'url': (chunk.get('web') or {}).get('uri', ''), 'title': (chunk.get('web') or {}).get('title')}
               for chunk in grounding.get('groundingChunks') or [] if chunk.get('web')]
    url_meta = (first.get('urlContextMetadata') or first.get('url_context_metadata') or {})
    fetched = [item for item in url_meta.get('urlMetadata') or url_meta.get('url_metadata') or []]
    for item in fetched:
        url = item.get('retrievedUrl') or item.get('retrieved_url')
        if url:
            sources.append({'url': url, 'title': url})
    queries = grounding.get('webSearchQueries') or []
    report = {'web_search_queries': queries, 'url_context': len(fetched)} if (queries or fetched) else None
    return text, sources, len(queries), len(fetched), report


def send(lane: Lane, call: Call) -> Sent:
    key = base.lane_key(lane) if call.client is None else 'test'
    if call.knobs.prefill:
        base.knob_refused(call, lane, 'prefill', PREFILL_REFUSAL + ' The opening is set on direct_answer instead.')
    knobs = call.knobs.as_dict()
    post = call.client or base.post_json
    url = API + call.model + ':generateContent'
    for _ in range(len(knobs) + 1):
        body = build_body(lane, call, knobs)
        try:
            payload, headers = post(url, body, {'x-goog-api-key': key}, call.timeout)
            break
        except ProviderHTTPError as exc:
            message = base.provider_message(exc.body)
            if exc.status == 400 and base.drop_refused(call, lane, knobs, message, KNOB_TOKENS):
                continue
            raise LaneError(f'The gemini lane rejected this request (HTTP {exc.status}): {message}') from exc
    else:
        raise LaneError('The gemini lane refused every knob combination.')
    text, sources, search, fetch, report = read_reply(payload)
    meta = usage(payload.get('usageMetadata') or {})
    tier = headers.get('x-gemini-service-tier') or headers.get('X-Gemini-Service-Tier')
    if tier:
        meta['service_tier_header'] = tier
    return Sent(raw_json=text, usage=meta, response_id=payload.get('responseId'), sources=sources,
                search=search, fetch=fetch, provider_report=report)


LANE = Lane(engine='gemini', shortcut='g5', default_model=MODEL, send=send, reply_mode='json',
            key_env='GEMINI_API_KEY', key_file='gemini-api-key', model_env='GEMINI_MODEL',
            web='google_search', images=True, pdfs=True)
