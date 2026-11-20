# laptop — George's Windows laptop (DESKTOP-760722E) over Tailscale

Runs on: the Debian side holds the ssh alias `wimlaptop`. The laptop's user folder is C:\Users\georg.

Run a command (the laptop's ssh shell is cmd.exe)
  deb ssh wimlaptop hostname                                  -> DESKTOP-760722E
  deb ssh wimlaptop 'dir /b C:\Users\georg\Downloads'

Run PowerShell
  deb ssh wimlaptop 'powershell -NoProfile -Command "Get-Date"'
  A script with quotes or pipes goes over encoded, so no quoting layer can break it:
  deb bash -c 'ssh wimlaptop "powershell -NoProfile -EncodedCommand $(printf %s "Get-ChildItem C:\\Users\\georg\\Downloads | Select-Object -First 5" | iconv -t UTF-16LE | base64 -w0)"'

Copy a file from the laptop to the phone
  deb scp wimlaptop:C:/Users/georg/Downloads/FILE /sdcard/Download/

Copy a file from the phone to the laptop
  deb scp /sdcard/Download/FILE wimlaptop:C:/Users/georg/Downloads/
  This writes a file on the laptop.

Start a long job for Claude on the laptop
  deb bash /root/agent-bridge/scripts/laptop_task.sh run "THE TASK IN PLAIN WORDS"     prints the job name
  deb bash /root/agent-bridge/scripts/laptop_task.sh watch JOB       last 40 log lines; JOB-DONE means finished
  deb bash /root/agent-bridge/scripts/laptop_task.sh ls              the 10 newest jobs
  Claude on the laptop runs with permission checks off. It acts without asking.

The laptop's two Chromes (headed on 9222, headless on 9224): `card browsers`.
  Its scheduled tasks on 2026-11-19: AgentBridgeLaptop (running), GeorgeGoogleConsoleHeadless (running),
  GeorgeJobApplicationsChrome (ready), ShowAgentChrome (ready). See them:
  deb ssh wimlaptop 'schtasks /query /fo csv /nh | findstr /i "George AgentBridge ShowAgent"'

Facts
  An admin action on the laptop needs George's Yes on the laptop screen.
  PowerShell output over ssh can end with a "#< CLIXML" block. That block is noise.

Known failure
  ssh times out: Tailscale on this phone is off (sh ~/bin/tailscale_keeper.sh once), or the laptop sleeps.
  The steps are in /root/.claude/device-control.md (deb cat /root/.claude/device-control.md).
