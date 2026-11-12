"""Use the existing cancellable buffered transport for a job with no terminal."""


def activate():
    import chat_progress
    # The normal chat installs a screen listener. A background job has no screen,
    # but still needs response.created so SIGINT can cancel the provider request.
    # No model text or thinking is displayed by this observer.
    chat_progress.listener = lambda phase, detail='': None
    chat_progress.response_listener = record_response


def record_response(engine, response_id):
    """Save only the public request id, so job stop can be checked at the provider."""
    if not response_id:
        return
    import os
    import time
    from .config import Paths, write_private_json
    paths = Paths()
    write_private_json(paths.home / 'requests' / (str(os.getpid()) + '.json'),
                       {'engine':engine, 'response_id':response_id, 'created':time.time(), 'pid':os.getpid()})
