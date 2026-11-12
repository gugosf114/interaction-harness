# bakery — My Baking Creations: numbers, Google listings, the Play apps

The numbers (Termux command, about 15 seconds)
  bakery-stats 7            the last 7 days; any number of days works
  First line, for example: "GA4 last 7d: sessions 492 | users 422 | conversions 2415".
  Then: visits by channel, top pages, Search Console clicks, impressions and top queries,
  Business Profile views, website clicks, calls and directions for Daly City and for San Francisco,
  then Instagram, Facebook and Pinterest. It only reads.

Business Profile
  The two "Business Profile" lines of bakery-stats are the Google listing numbers for each location.

Google Play (the official API, Debian side)
  deb play apps                       the five apps and their tracks
  deb play tracks PACKAGE             releases on each track
  deb play state PACKAGE              review and publishing state
  deb play testers PACKAGE TRACK
  deb play get PATH                   any read call of the Play Developer API
  deb play upload PACKAGE FILE.aab TRACK     This uploads a build to Google Play.
  Packages: com.wimlabs.wim, app.climatepermit.android, com.wimlabs.heirloom, com.wimlabs.noisefile,
  me.aap.fermata.auto.samizdat.

Ask search engines to crawl a page
  Bing:
  deb bash -c 'curl -s -X POST "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrl?apikey=$(cat /root/.bing/apikey)" -H "Content-Type: application/json" -d "{\"siteUrl\":\"https://mybakingcreations.com\",\"url\":\"PAGE_URL\"}"'
  This tells Bing to crawl PAGE_URL now. The answer {"d":null} means accepted.
  IndexNow and Google's "Request indexing": the steps are in
  deb cat /root/.claude/projects/-root/memory/gsc-request-indexing-recipe.md
  Google has no API for it; it is done in the signed-in browser (`card phone-browser`).

Related
  The website repo is gugosf114/gugosf114.github.io (`card github`). The bakery mailbox: `card mail`.
  PayPal invoices: `card money`. Bing key check: `cloud-check bing`.

Known failure
  `deb mbc-stats 7` answers "cannot execute: required file not found": its Python folder
  /root/.gmail/venv is gone. bakery-stats runs the same script and works.
