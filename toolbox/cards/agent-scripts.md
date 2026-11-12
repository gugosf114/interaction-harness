# agent-scripts — George's own scripts that find, tap and drive things on the phone

They live on the Debian side in /root/agent-bridge/scripts. Call each one as:
  deb bash /root/agent-bridge/scripts/NAME ARGUMENTS

Where am I, what works
  transport.sh ensure            prints the live adb target for this phone ("127.0.0.1:5555") and heals a dropped door
  recap.sh                       read-only: the runbook, recent git state and transport status of agent-bridge
  shizuku.sh status              the Shizuku door: see `card shizuku`

Find a thing on George's visible screen
  ground.sh 'Home'               -> {"x":539,"y":2361,"node_id":"node_7faba97e","method":"a11y","confidence":1.0}
                                 It only looks. Three tiers: the screen's node tree, then a grounding model on the
                                 laptop, then a vision model.
Find it and tap it (each acts on George's visible screen at once)
  vision_click.sh 'Search bar'             finds the element by its words and taps it
  vision_click.sh 'Search bar' --verify    taps, then proves the screen changed; retries when it did not
  act.sh                                   the verify-and-retry library behind --verify; scripts source it and
                                           call: act_verified tap:Send 'Sent'
  droidrun.sh run "open Gmail and star the newest mail"      hands a whole goal in words to the DroidRun driver
  droidrun.sh status | activate | setup                      is its helper app reachable; re-enable it; install it

Hidden screens: drive an app George does not see
  hidden_drive.sh open NAME PACKAGE/ACTIVITY     make sure the screen exists and open the app on it
  hidden_drive.sh do NAME 'Button text'          find the button by its name, tap it, check the screen changed
  hidden_drive.sh type NAME 'words'  |  key NAME 66  |  read NAME      type; send a key; list the buttons
  ui.sh tree | find 'Text' | tap 'Text'          the reader behind it (set HD_NAME=NAME in front)
  hidden_supervisor.sh status                    which hidden screens are up; whether the keeper loop runs
  hidden_supervisor.sh ensure | boot | stop      bring every listed screen back; start or stop the keeper loop
  teach_skill.sh list                            taught skills (none so far)
  teach_skill.sh new NAME | tap NAME X Y | replay NAME | drop NAME     teach a task once by button pictures, replay it
  app_map.py --help                              maps an app's screens on a hidden screen, so a later run goes by name

Texts
  read_sms_code.sh latest 5      the last five texts: time, sender, first 70 characters
  read_sms_code.sh code          the newest login code found in the last few texts
  read_sms_code.sh wait 120      waits up to 120 s and prints a code the moment a new text brings one

Phone upkeep and signals
  phone_trim.sh                  frees memory: force-stops idle heavy apps, restricts them in the background,
                                 disables unused Samsung apps, halves the animations. It changes the phone.
  signal.sh --pending            exit 0 when George pressed the Summon button and is waiting
  signal.sh --setup | --state work|done|turn|ready | --stop      the red, blue, amber status light in a notification
  status_beacon.sh               keeps one notification that says whether the laptop is reachable

Known failure (checked 2026-11-11, on the Pixel 11 with Android 17)
  hidden_drive.sh read, hidden_drive.sh do and ui.sh print nothing: the name reader for hidden screens starts
  and never answers. hidden_display.sh start says "display exists but shared reader failed". Pictures still
  work: drive a hidden screen with `card screen`.
  droidrun.sh status answers "Mobilerun Portal is not enabled as an accessibility service on the device".
  `droidrun.sh activate` turns it back on.
