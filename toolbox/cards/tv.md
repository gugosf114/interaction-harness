# tv — the LG TV and the Chromecast on the home wifi

Runs on: the Debian side. It works only while the phone is on the home wifi.
The LG TV is 192.168.1.66. The Chromecast is "Family Room TV", 192.168.1.215.

Find what is on this wifi
  deb tv scan
  Takes about 17 seconds. Lists Chromecasts, the LG TV and other casting devices with their addresses.

The LG TV (each line acts on the TV at once)
  deb tv say "TEXT"         shows a message on the TV screen
  deb tv vol 12             sets the volume
  deb tv off ; deb tv on    screen off ; screen on
  deb tv app youtube        opens an app on the TV

The Chromecast
  deb catt -d 192.168.1.215 status          volume and what is playing; changes nothing
  deb tv cast 'URL'                         plays that video on the Chromecast at once
  deb tv stop                               stops it
  deb catt -d 192.168.1.215 volume 40
  deb catt --help                           every catt command
  deb bscpylgtvcommand --help               the LG program behind `tv`: any other LG command

Known failure (checked 2026-11-19)
  Off the home wifi every command times out or finds nothing: `deb tv scan` printed "No devices found" at
  4:35 pm away from home, and found the Chromecast at 7:10 pm at home.
