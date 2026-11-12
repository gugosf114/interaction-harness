# cloud — Google Cloud, and the keys for the other cloud accounts

Google Cloud (gcloud on the Debian side)
  Add --account=gugosf@gmail.com to every gcloud command. The default account on this phone is a
  service account for Google Play, and it is refused on most calls.
  deb gcloud projects list --account=gugosf@gmail.com --format='value(projectId)'
      -> bakers-agent, bakers-agent-2, credit-burn-test-g114, gen-lang-client-0808363618,
         heirloom-gem-10140048, web-search-g114
  deb gcloud run services list --project bakers-agent --account=gugosf@gmail.com
  deb gcloud functions list --project bakers-agent --account=gugosf@gmail.com

Secrets (Secret Manager, project bakers-agent, 46 names)
  deb gcloud secrets list --project bakers-agent --account=gugosf@gmail.com --format='value(name)'
  Use a secret inside one command, so its value is never printed:
  deb bash -c 'KEY=$(gcloud secrets versions access latest --secret SECRET_NAME --project bakers-agent --account=gugosf@gmail.com); curl -s -H "Authorization: Bearer $KEY" https://API_URL'

The backup bucket
  deb gcloud storage ls gs://george-phone-backup-20261029 --account=gugosf@gmail.com
      -> folders A/ B/ C/ D/ E/ golden/ sealed-chats/
  deb gcloud storage cp gs://george-phone-backup-20261029/A/FILE /sdcard/Download/ --account=gugosf@gmail.com

The other accounts: where each key lives, and one read-only call
  cloud-check cloudflare     key /root/.cloudflare-api-token      -> "cloudflare token: active"
  cloud-check bing           key /root/.bing/apikey               -> "bing sites: ['https://mybakingcreations.com/']"
  cloud-check huggingface    key /root/.huggingface/token         -> "hugging face user: NAME"
  cloud-check runpod         key /root/.runpod/config.toml        -> "runpod balance: N | pods: [...]"
  cloud-check modal          key /root/.modal.toml                -> not working, see below
  cloud-check brightdata     sign-in /root/.brightdata/account.env -> not working, see below
  The bakery's Cloudflare account uses two secrets, cloudflare-mbc-global-key and cloudflare-mbc-email,
  sent as the headers X-Auth-Key and X-Auth-Email.

Known failure (checked 2026-11-11)
  modal: "ModuleNotFoundError: No module named 'modal'". The modal program is not installed on the Debian side.
  brightdata: "bdata: command not found". The Bright Data program is not installed, and no API token is on file.
  A gcloud call without --account answers PERMISSION_DENIED and names play-publisher@bakers-agent.
