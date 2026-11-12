# laptop-hands — mouse and keyboard on George's Windows laptop screen

Runs on: the Termux side starts it; the Debian side sends it over ssh (alias wimlaptop, card laptop).
Each action runs as a one-shot scheduled task inside George's logged-in desktop session, then the task
and its files are removed. Input is Windows SendInput: real mouse and key events; words go in as Unicode.
Each command prints what it did and the window in front after it, with that window's corners:
  "pressed enter | front window: Untitled - Notepad (3878,350 to 4828,1458)"

Click and move
  laptop-click X Y              left click at pixel X Y
  laptop-click X Y --right      right click        laptop-click X Y --double     double click
  laptop-move X Y               move the pointer only
  X Y are the same pixels as a `screen snap --target laptop` picture (card screen): 2560 x 1440 on the
  main monitor. The laptop has a second monitor to the right of it; that picture does not show it.
  The corners printed after each action say where the front window is.

Type words
  laptop-type 'harness proof from the phone'      into whatever has the focus. Any language, any symbol.

Press keys
  laptop-key enter      laptop-key ctrl+s      laptop-key alt+tab      laptop-key win+r
  laptop-key ctrl+shift+esc      laptop-key f5      laptop-key a
  Names: letters, digits, f1-f24, enter, tab, esc, space, backspace, delete, insert, home, end, pageup,
  pagedown, up, down, left, right, ctrl, alt, shift, win, menu, printscreen, capslock, volumeup,
  volumedown, volumemute, mediaplay, medianext, mediaprev, mediastop, and ; = , - . / ` [ \ ] '.

Open a program
  laptop-key win+r ; laptop-type notepad ; laptop-key enter

Facts
  This acts on George's own laptop screen at once, in front of whatever he has open there.
  Why not plain ssh: an ssh session runs in Windows session 0, which has no desktop. There SetCursorPos
  answers False with error 1459 (Windows error 1459: interactive desktop required).
  In Windows 11 Notepad, ctrl+w closes the window; alt+f4 did not close it (2026-11-11).

Known failure
  Keys and words go to the window in front when each one lands. When another window comes to the front
  during laptop-type, the rest goes there (seen 2026-11-11: Chrome took the focus). The front window is
  printed after every action; check it before typing.
  "no answer from the desktop in 120 s": nobody is logged in on the laptop screen, or it is locked.
  "laptop: ..." with an ssh message: see the known failure on card laptop.
