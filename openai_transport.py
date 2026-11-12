"""Buffer a Responses stream; only public tool phases escape before the gate."""
from chat_progress import watching, public_event


def complete_response(endpoint, **params):
    declared = callable(getattr(type(endpoint), 'stream', None)) or 'stream' in getattr(endpoint, '__dict__', {})
    method = getattr(endpoint, 'stream', None) if declared else None
    if not watching() or not callable(method):
        return endpoint.create(**params)
    with method(**params) as stream:
        for event in stream: public_event(event)
        return stream.get_final_response()
