#!/bin/bash
# Debian side of cloud-check. One read-only call per service, with the key read from its own file.
# No key value is printed.
set -u -o pipefail
get() { curl -s -m 30 "$@"; }
case "${1:-}" in
  cloudflare)   # key: /root/.cloudflare-api-token (also Secret Manager cloudflare-api-token)
    get -H "Authorization: Bearer $(cat /root/.cloudflare-api-token)" https://api.cloudflare.com/client/v4/user/tokens/verify \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print("cloudflare token:", (d.get("result") or {}).get("status", d.get("errors")))' ;;
  bing)         # key: /root/.bing/apikey
    get "https://ssl.bing.com/webmaster/api.svc/json/GetUserSites?apikey=$(cat /root/.bing/apikey)" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print("bing sites:", [s.get("Url") for s in d.get("d", [])] if isinstance(d.get("d"), list) else d)' ;;
  huggingface)  # key: /root/.huggingface/token
    get -H "Authorization: Bearer $(cat /root/.huggingface/token)" https://huggingface.co/api/whoami-v2 \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print("hugging face user:", d.get("name", d))' ;;
  runpod)       # key: /root/.runpod/config.toml (apikey)
    key=$(python3 -c 'import re; print(re.search(r"apikey\s*=\s*[\x27\x22]?([^\x27\x22\s]+)", open("/root/.runpod/config.toml").read()).group(1))')
    get "https://api.runpod.io/graphql?api_key=$key" -H 'Content-Type: application/json' \
      -d '{"query":"query { myself { clientBalance pods { id name desiredStatus costPerHr } } }"}' \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); me=(d.get("data") or {}).get("myself"); print("runpod balance:", me.get("clientBalance"), "| pods:", [(p["name"], p["desiredStatus"], p["costPerHr"]) for p in me.get("pods", [])]) if me else print(d)' ;;
  modal)        # key: /root/.modal.toml
    modal app list 2>&1 | tail -12 ;;
  brightdata)   # sign-in: /root/.brightdata/account.env ; the bdata command keeps its own sign-in
    bdata zones 2>&1 | tail -12 ;;
  *) echo 'usage: cloud-check cloudflare|bing|huggingface|runpod|modal|brightdata' >&2; exit 2 ;;
esac
