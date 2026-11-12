"""GNU Readline editing with atomic bracketed paste and private JSON history.

Only the input editor temporarily connects fd 1 to the terminal on fd 2.
Readline can then edit even when answer stdout is piped. The descriptor is
restored before any model call. No user text or ANSI decoration enters the pipe.
"""
import json
import fcntl
import os
from pathlib import Path
import sys

from storage import atomic_json


class InputTooLong(ValueError):
    pass


class InputMessage(str):
    def __new__(cls, text, literal=False):
        value = super().__new__(cls, text)
        value.literal = literal
        return value


class ChatInput:
    def __init__(self, state, color, limit):
        self.path = Path(state) / 'chat-input.json'
        self.color = color
        self.limit = limit
        self.initial = ''
        try: self.history = json.loads(self.path.read_text())
        except (OSError, ValueError): self.history = []
        if not isinstance(self.history, list): self.history = []
        self.history = [s for s in self.history if isinstance(s, str)]
        self.readline = None
        try:
            if sys.stdin.isatty() and sys.stderr.isatty() and sys.stdin.fileno() == 0:
                import readline
                self.readline = readline
                readline.parse_and_bind('set enable-bracketed-paste on')
                readline.parse_and_bind('set editing-mode emacs')
                readline.set_auto_history(False)
                readline.clear_history()
                for entry in self.history: readline.add_history(entry)
        except (AttributeError, OSError, ImportError): pass

    def remember(self, text):
        # Re-read so a second open chat's history is not overwritten.
        fd = os.open(self.path.with_suffix('.lock'),os.O_CREAT|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try: saved = json.loads(self.path.read_text())
            except (OSError, ValueError): saved = []
            if not isinstance(saved, list): saved = []
            if not saved or saved[-1] != text: saved.append(text)
            atomic_json(self.path, saved)
        self.history = saved
        if self.readline and (not self.readline.get_current_history_length() or
                self.readline.get_history_item(self.readline.get_current_history_length()) != text):
            self.readline.add_history(text)

    def line(self, prompt='> '):
        if self.readline:
            initial, self.initial = self.initial, ''
            if initial:
                self.readline.set_startup_hook(lambda: self.readline.insert_text(initial))
            saved = os.dup(1)
            try:
                sys.stdout.flush()
                os.dup2(2, 1)
                # Readline prompt markers keep ANSI escapes out of its width count.
                label = self.color('prompt', prompt, readline=True)
                return input(label)
            finally:
                self.readline.set_startup_hook(None)
                os.dup2(saved, 1)
                os.close(saved)
        print(prompt, end='', file=sys.stderr, flush=True)
        line = sys.stdin.readline(self.limit + 2)
        if not line: raise EOFError
        if len(line) > self.limit and not line.endswith('\n'):
            while line and not line.endswith('\n'):
                line = sys.stdin.readline(self.limit + 2)
            raise InputTooLong(f'Input exceeds {self.limit} characters.')
        return line.rstrip('\r\n')

    def read(self):
        text = self.line()
        block = text.strip().lower() == '/paste'
        pasted = '\n' in text
        if block:
            lines = []
            oversized = False
            size = -1
            while True:
                try: line = self.line('· ')
                except InputTooLong:
                    oversized = True
                    continue
                if line == '.': break
                if not oversized:
                    lines.append(line)
                    size += len(line)+1
                    if size > self.limit:
                        oversized = True
                        lines = []
            if oversized: raise InputTooLong(f'Input exceeds {self.limit} characters.')
            text = '\n'.join(lines)
        elif not pasted:
            while text.endswith('\\'):
                text = text[:-1] + '\n' + self.line('· ')
        if len(text) > self.limit:
            raise InputTooLong(f'Input exceeds {self.limit} characters.')
        return InputMessage(text, literal=block or '\n' in text)
