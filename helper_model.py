"""One small, fast model call for the lane mods (thread tree, proof marks), on the lane's own API account.

The Claude Code mods use Haiku for this. The lanes use the small model of each provider, checked live on
2026-11-11: claude-haiku-5-5 answered in 0.9 s, gpt-6-luna in 1.8 s. Each call is one usage.jsonl record with
kind "mod:NAME", so the usage meter counts it. A failure returns None; a mod never breaks a turn.
"""
from __future__ import annotations

from datetime import datetime, timezone
import time

MODELS = {'anthropic': 'claude-haiku-5-5', 'openai': 'gpt-6-luna'}


def _client(engine, timeout):
    import harness as h
    if engine == 'anthropic':
        import anthropic
        return anthropic.Anthropic(api_key=h.load_key(engine), base_url='https://api.anthropic.com',
                                   timeout=timeout, max_retries=0)
    from openai import OpenAI
    return OpenAI(api_key=h.load_key(engine), base_url='https://api.openai.com/v1', timeout=timeout, max_retries=0)


def complete(engine: str, kind: str, system: str, prompt: str, *, effort: str = 'low', max_tokens: int = 4000,
             timeout: float = 60, client=None, log_path=None) -> str | None:
    import harness as h
    model = MODELS[engine]
    event = {'time_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'mod:' + kind, 'engine': engine,
             'model_requested': model, 'effort': effort, 'status': 'pending'}
    started = time.monotonic()
    try:
        client = client or _client(engine, timeout)
        if engine == 'anthropic':
            response = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                              output_config={'effort': effort},
                                              messages=[{'role': 'user', 'content': prompt}])
            text = ''.join(b.text for b in response.content if getattr(b, 'type', None) == 'text')
        else:
            response = client.responses.create(model=model, instructions=system, input=prompt,
                                               reasoning={'effort': effort}, max_output_tokens=max_tokens)
            text = response.output_text
        event['model_returned'] = getattr(response, 'model', None)
        usage = getattr(response, 'usage', None)
        if usage is not None:
            event['usage'] = usage.model_dump(exclude_none=True)
        event['status'] = 'accepted'
        return text
    except Exception as exc:  # any provider or network failure: no reading this time
        event['status'] = 'error'
        event['error'] = type(exc).__name__
        return None
    finally:
        event['elapsed_ms'] = round((time.monotonic() - started) * 1000)
        try:
            h.record_event(event, log_path)
        except OSError:
            pass
