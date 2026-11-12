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
  deb voice             says the current setting; changes nothing
  deb voice on          Claude Code speaks the first line of every answer
  deb voice off         silence
  deb voice full        the whole answer, in every session
  deb voice car         play through the phone speaker even with Bluetooth or Android Auto on
  deb voice home        normal sound routing
  The switch is a file that Claude Code's own hook reads. It does not make `george` or `g1` speak.
  To hear a harness answer, speak it with `deb say`.

Known failure
  With no network `say` falls back to the robot voice.
