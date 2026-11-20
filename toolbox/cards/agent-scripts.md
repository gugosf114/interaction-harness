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

Hidden screens, reading texts and login codes
  The newer copies live in /root/hidden-operator: `card hidden-screens`. The copies of hidden_display.sh,
  hidden_drive.sh, ui.sh and read_sms_code.sh in this folder fail on this phone ("adb: more than one
  device/emulator", "[sms] no live adb").

Phone upkeep
  phone_trim.sh                  frees memory: force-stops idle heavy apps, restricts them in the background,
                                 disables unused apps, halves the animations. It changes the phone. Listed, not run.
  grant_termux_api.sh            grants Termux:API every permission it can hold. It changes the phone. Listed, not run.
  activate_shizuku.sh status     Shizuku's state; `start` starts it (`card shizuku`)
  wifi_debug_tile.sh             taps the Wireless debugging tile on George's visible screen. Listed, not run.
  mcp.sh, orch.sh, laptop_task.sh, voice_summon.sh       `card agent-box`, `card laptop`

Stopped on George's word on 2026-11-19. Do not start them.
  signal.sh --watch              the red, blue, amber status light in a notification, and the Summon button
  brain_beacon.sh                buzzed when the always-on box stopped answering
  status_beacon.sh               one notification that says whether the laptop is reachable
  phone_supervisor.sh            the old supervisor that kept those alive; its timer 7919 is cancelled
  signal.sh --pending            still safe to run: exit 0 when George pressed Summon, exit 1 when not

Code for other machines (read it with: deb sed -n '1,40p' /root/agent-bridge/scripts/NAME)
  conductor.py, conductor_brain.py, box_scheduler.py, telegram_bridge.py, telegram_lane.py, deploy_box.sh    the box
  laptop_agent.py, windows_desktop.ps1, install_laptop_agent.ps1, grounding_server.py, holo_serve.ps1    the laptop

Known failure (checked 2026-11-19)
  droidrun.sh status answered "Portal is installed and accessible". When it says the Portal "is not enabled as
  an accessibility service", `droidrun.sh activate` turns it back on.
  ground.sh gives x and y for the screen as it is turned at that moment; on a sideways screen they swap.
