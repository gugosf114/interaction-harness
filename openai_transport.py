"""Buffer a Responses stream; only public tool phases escape before the gate."""
from chat_progress import watching, public_event


def complete_response(endpoint, **params):
    declared = callable(getattr(type(endpoint), 'stream', None)) or 'stream' in getattr(endpoint, '__dict__', {})
    method = getattr(endpoint, 'stream', None) if declared else None
    if not watching() or not callable(method):
        return endpoint.create(**params)
    response_id = None
    try:
        with method(**params) as stream:
            for event in stream:
                response = getattr(event, 'response', None)
                response_id = getattr(response, 'id', None) or response_id
                public_event(event)
            return stream.get_final_response()
    except BaseException:
        # Closing a background stream leaves its server job running. Cancel the
        # id reported by response.created before returning to the prompt.
        if params.get('background') and response_id:
            import harness as h
            receipt = {'kind':'cancel','engine':'openai','response_id':response_id}
            try:
                result = endpoint.cancel(response_id)
                receipt['status'] = getattr(result, 'status', 'unknown')
            except Exception as exc:
                receipt.update(status='error',error=type(exc).__name__)
                import chat_screen
                chat_screen.error('Provider cancellation failed: '+type(exc).__name__+'.')
            try: h.record_event(receipt)
            except OSError: pass
        raise
