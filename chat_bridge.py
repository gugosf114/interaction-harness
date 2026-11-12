"""Keep a cancelled native operation's reply out of the following operation."""
import json
import signal
import threading


def exchange(stream, request):
    interrupted = False
    def defer(*_):
        nonlocal interrupted
        interrupted = True
    main_thread = threading.current_thread() is threading.main_thread()
    previous = signal.signal(signal.SIGINT, defer) if main_thread else None
    try:
        stream.write(json.dumps(request).encode()+b'\n'); stream.flush()
        line = stream.readline(16777216)
        result = json.loads(line) if line else None
        # The parent kills the native process group and returns this receipt.
        # Drain it before raising, even when both sides receive the same Ctrl-C.
        if interrupted or (result and result.get('interrupted')): raise KeyboardInterrupt
        return result
    finally:
        if main_thread: signal.signal(signal.SIGINT, previous)
