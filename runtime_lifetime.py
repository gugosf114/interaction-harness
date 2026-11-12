"""Keep a tool runtime alive through the gate retry and close it on every exit."""
from functools import wraps


def managed_runtime(function):
    @wraps(function)
    def request(*args,**kwargs):
        runtime=kwargs.get('api_runtime')
        try:
            return function(*args,**kwargs)
        finally:
            if runtime is not None:runtime.close()
    return request
