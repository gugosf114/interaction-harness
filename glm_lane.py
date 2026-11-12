"""George's own fine-tuned GLM model on Modal (shortcut g4).

An OpenAI-compatible endpoint that returns plain text (no JSON mode, no tools), so
the client wraps the answer as a four-field observation. A wrap lane answers but
proposes no command. The endpoint scales to zero after a few idle minutes, so the
first call after a pause cold-starts; the lane raises its own timeout floor for
that. The server accepts temperature and max_tokens; it has no seed, stop, tier or
schema. Bring the app up with `deb modal deploy /root/.glm/modal/app.py` if it is
torn down (profile gmail, workspace gugosf, app glm-george).
"""
from __future__ import annotations

import json

import lane_base as base
from lane_base import Call, Lane, LaneError, Sent

BASE = 'https://gugosf--glm-george-openai.us-east.modal.run/v1'
MODEL = 'glm-george'
COLD_START = 720            # the endpoint can cold-start for several minutes; wait at least this long


def send(lane: Lane, call: Call) -> Sent:
    from openai import OpenAI
    base.check_media(lane, call.messages)
    client = call.client
    if client is None:
        client = OpenAI(api_key='none', base_url=base.lane_base_url(lane), timeout=call.timeout, max_retries=0)
    messages = [{'role': 'system', 'content': page} for page in call.system_pages]
    messages.append({'role': 'system', 'content': base.lane_note(lane, call.web)})
    for message in call.messages:
        messages.append({'role': message['role'], 'content': message['content']})
    params = {'model': call.model, 'messages': messages}
    kb = call.knobs
    if kb.temperature is not None:
        params['temperature'] = kb.temperature
    for name, value in (('seed', kb.seed), ('stop', kb.stop), ('service_tier', kb.service_tier)):
        if value is not None:
            base.say_once(call, f'[{lane.engine}] knob --{name.replace("_", "-")} not supported on this lane; skipped.')
    if kb.prefill:
        base.say_once(call, f'[{lane.engine}] --prefill is set on the answer text; the opening is forced after the reply.')
    response = client.chat.completions.create(**params)
    text = (response.choices[0].message.content or '') if response.choices else ''
    usage = getattr(response, 'usage', None)
    meta = {}
    if usage is not None:
        try:
            data = usage.model_dump(exclude_none=True)
        except AttributeError:
            data = dict(usage)
        meta = {'output_tokens': data.get('completion_tokens', 0),
                'input_tokens': data.get('prompt_tokens', 0),
                'total_tokens': data.get('total_tokens', 0)}
    return Sent(raw_json=base.wrap_text(text, call.raw_input), usage=meta,
                response_id=getattr(response, 'id', None))


LANE = Lane(engine='glm', shortcut='g4', default_model=MODEL, send=send, reply_mode='wrap',
            base_url=BASE, base_env='GLM_OPENAI_URL', base_file='glm-url', model_env='GLM_MODEL',
            min_timeout=COLD_START)
