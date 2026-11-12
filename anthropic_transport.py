"""Keep long Claude requests alive; buffer the entire message before any display gate.

Official recipe: https://platform.claude.com/docs/en/build-with-claude/streaming
Create-only injected adapters remain supported. A stream failure never falls back
into a second request, and partial text/tool JSON never reaches the caller.
"""
import anthropic
import httpx2 as httpx


def _incomplete(stream, reason):
    response = getattr(stream, 'response', None)
    request = getattr(response, 'request', None) or httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
    return anthropic.APIConnectionError(message=reason, request=request)


def complete_message(endpoint, **params):
    # Looking at the declared API avoids treating a Mock's invented attributes as
    # a streaming implementation. Real Messages and BetaMessages declare stream.
    declared = callable(getattr(type(endpoint), 'stream', None)) or 'stream' in getattr(endpoint, '__dict__', {})
    method = getattr(endpoint, 'stream', None) if declared else None
    if not callable(method):
        return endpoint.create(**params)
    with method(**params) as stream:
        try:
            from chat_progress import watching, public_event
            if watching():
                for event in stream: public_event(event)
            message = stream.get_final_message()
        except AssertionError as exc:
            raise _incomplete(stream, 'Claude stream ended before a message was received.') from exc
        if not getattr(message, 'stop_reason', None):
            raise _incomplete(stream, 'Claude stream ended before a final stop reason.')
        return message
