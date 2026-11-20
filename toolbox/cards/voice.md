# voice — speak out loud through the phone

Speak a line (neural voice, Debian side)
  deb say "TEXT"
  This plays out of the phone speaker at once. Default voice: en-US-AvaNeural.
  deb say -v en-GB-RyanNeural "TEXT"       another voice
  deb say -l                               list the voices; plays nothing
  deb say -s                               stop what is playing

Android's own robot voice (Termux side, works with no network)
  termux-tts-speak "TEXT"

Spoken answers in George's Claude Code sessions
  deb voice             says the current setting; changes nothing. On 2026-11-19:
                        "Voice is OFF / Full: EVERY session / Lane: CAR (alarm, phone speaker)"
  deb voice on          Claude Code speaks the first line of every answer
  deb voice off         silence
  deb voice full        the whole answer, in every session
  deb voice car         play through the phone speaker even with Bluetooth or Android Auto on
  deb voice home        normal sound routing
  The switch is a file that Claude Code's own hook reads.

Spoken answers in g2 and g1
  Each final answer is read aloud with `say`. In a chat: /voice full (whole answer), /voice short
  (first sentence), /voice off, /voice on. The setting is in the harness's state/mods.json.
  Lane chats, daemon jobs and talk take turns through one speaker lock.
  The prompt stays open while the answer is read; /voice off stops it and skips queued speech.
  The lane saves the voice command's exit code in usage.jsonl as hook:voice.

Known failure
  With no network `say` falls back to the robot voice.
