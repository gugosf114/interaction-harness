# screen — capture a screen, see the picture, then drive that screen

Capture George's Pixel 11 (the default target)
  screen snap --target phone
  Prints a PNG path. In an approved harness loop, that picture is attached to the next model turn.
  screen size --target phone
  Prints width and height in pixels, taken from a fresh capture.

A hidden screen that is already running
  screen snap --target hidden:NAME
  screen size --target hidden:NAME
  screen tap X Y --target hidden:NAME
  screen swipe X1 Y1 X2 Y2 MS --target hidden:NAME
  screen text 'WORDS' --target hidden:NAME
  screen key KEYCODE_ENTER --target hidden:NAME
  MS is optional; the default is 300. All six verbs ran on hidden:astra-screen-proof.
  Use card phone for the hidden-screen start, launch, and stop commands.
  Tap coordinates are pixels of the captured image at full size. Read the image before choosing a point.
  Capture again after an action to see its result. A successful tap alone does not prove the app changed.
  Hidden captures match the named display's unique id to its SurfaceFlinger capture id. Static screens can be captured repeatedly.
  Android text accepts printable ASCII. A literal %s and other characters return an error.

George's Windows laptop
  screen snap --target laptop
  screen size --target laptop
  Captures the primary desktop via an interactive PowerShell task, then removes the task and temporary files.
  The PNG uses native pixels. Input verbs are implemented but listed, not run on the laptop.

Other targets
  phone is George's visible screen. Input on this target acts on George's visible screen at once.
  yana is Yana's phone through Debian adb. This target is listed, not run.
  laptop input acts on its signed-in desktop at once. Laptop key names: ENTER, TAB, ESC, BACKSPACE, UP, DOWN, LEFT, RIGHT.
  Android keys use numeric keycodes or KEYCODE names.

Show the next model turn a file already on the phone
  look PATH
  Accepts PNG, JPEG, WebP, GIF, or PDF. Run it inside the approved loop's execution_payload.
  The runner sends a private file receipt, not a marker in stdout. Printed web or log text cannot attach files.
  The harness checks the file and saves fixed bytes with path, SHA-256, size and media type.
  It keeps the picture while the exchange stays in history. A file error goes back as an execution observation.
  Outside the harness, look prints the path; there is no model turn to receive it.

Known failure
  Missing target: "screen: target is missing: hidden:NAME."
  Black frame: "screen: screen is off or capture is all black."
  Deadline: "screen: timeout."
  Each failure exits nonzero. The command never substitutes George's visible screen for a missing hidden screen.
