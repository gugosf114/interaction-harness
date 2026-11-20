# keys — where every key and sign-in lives, by name; no value is ever printed

Rule: use a key inside one command. Never cat a key file and never echo a secret. Checked 2026-11-19.

Google accounts (the list: /root/.gmail/accounts.json; the command: google-accounts)
  berkeley, gmail, bakery, gurgen, interior. Each has mail, calendar and drive signed in.
  Tokens: /root/.gmail/accounts/NAME.json. Older ones: /root/.gmail/berkeley_token.json, gmail_token.json,
  sa.json (bakery service key). OAuth app files: /root/.gmail/client_secret_*.json.
  gcloud: gugosf@gmail.com, plus service accounts for Play and Analytics (`card cloud`).

Key files on the Debian side (see names with: deb ls FOLDER)
  /root/.paypal/live.env            PayPal live app "Invoice Tool"                    `card money`
  /root/.bland/key                  the caller                                        `card calls`
  /root/.gmail/aicalls.env          Vapi keys for the voice lines; /root/.vapi/bridge/ holds line.key, drop.key
  /root/.twilio/password            the Twilio account password
  /root/.play/sa.json               Google Play publisher service key                 `card bakery`
  /root/.ga4/                       key.json (Analytics), gbp-oauth-secret.json, gsc-oauth-secret.json,
                                    fb-page-access-token.txt, four pinterest-*.txt files
  /root/.bing/apikey                Bing Webmaster      /root/.mbc-indexnow-key      IndexNow
  /root/.mbc/listings.env           the bakery's directory listings
  /root/.google-search/env          Google search API
  /root/.cloudflare-api-token       Cloudflare (gugosf account); /root/.cloudflared/ a named tunnel's file
  /root/.huggingface/token          Hugging Face        /root/.modal.toml            Modal
  /root/.runpod/                    config.toml, box_api_key, ssh/ (rented GPU machines)
  /root/.brightdata/                account.env, card.env
  /root/.openai-key                 an OpenAI key for the Debian-side tools
  /root/.keys/                      signing keys: climate-permit, heirloom, samizdat (Android apps)
  /root/.ssh/                       termux (this phone and the Flip), yana/yana_key, runpod; config names the laptop
  /root/.config/gh, ngrok, gcloud, brightdata-cli      each program's own sign-in

Key files on the Termux side
  ~/interaction-harness/state/      api-key (OpenAI lane), anthropic-api-key, gemini-api-key, doors.json
                                    (page password, Telegram token, voice key)
  ~/.config/gh                      GitHub, signed in as gugosf114
  ~/.codex, ~/.gemini               Codex and Gemini sign-ins

Secret Manager, project bakers-agent, 46 names
  deb gcloud secrets list --project bakers-agent --account=gugosf@gmail.com --format='value(name)'
  AI: anthropic-api-key, openai-api-key, gemini-api-key, perplexity-api-key, and one each for wim, yalta,
  lavrentiy (two), stratos and heirloom
  Google: ga4-service-account, gbp-, gsc-, gmail-, drive- and youtube-oauth-secret, google-places-api-key,
  play-publisher-sa, mbc-mail-reader-key
  Social: fb-app-id, fb-app-secret, fb-page-access-token, four pinterest-* names
  Other: github-pat, a Github-Connect OAuth token, cloudflare-api-token, cloudflare-mbc-email,
  cloudflare-mbc-global-key, paypal-live-credentials, resend-api-key, web3forms-api-key, webpush-vapid-private-key,
  mbc-quote-files-signing-key, three *-vapi-* names, heirloom-pipeline-shared-secret, two signal-* names,
  four glm-* names. The command above prints the exact names.
  Use one without printing it: the command is on `card cloud`.

Check that a key still works, with no value shown
  cloud-check cloudflare | bing | huggingface | runpod | modal | brightdata        `card cloud`

Not in GitHub: every file above. The backup bucket is on `card cloud`.

Known failure
  `agentd status` prints the page password in its output. Do not repeat that line to anyone.
