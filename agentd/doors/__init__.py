"""The doors: each turns an incoming message into a job and sends the answer back the same way."""
from __future__ import annotations


class Door:
    """One door. `poll` looks for new messages and adds jobs. `deliver` sends a finished job's answer back."""
    name = 'door'
    interval = 5

    def __init__(self, daemon):
        self.daemon = daemon
        self.note = ''

    def poll(self):
        raise NotImplementedError

    def status(self) -> str:
        return self.note


def build(daemon) -> list:
    """Every door this checkout has, in a fixed order."""
    from .inbox import InboxDoor
    from .schedule import ScheduleDoor
    from .sms import SmsDoor
    from .telegram import TelegramDoor
    from .triggers import TriggerDoor
    from .voice import VoiceDoor
    return [InboxDoor(daemon), SmsDoor(daemon), TelegramDoor(daemon), VoiceDoor(daemon), ScheduleDoor(daemon), TriggerDoor(daemon)]


def answer_text(job) -> str:
    """What goes back through a door when a job ends."""
    if job.get('answer'):
        return job['answer']
    if job['state'] == 'stopped':
        return 'Stopped.'
    return job.get('error') or 'The job ended without an answer.'
