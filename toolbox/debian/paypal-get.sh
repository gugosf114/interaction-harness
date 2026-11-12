#!/bin/bash
# Debian side of paypal-get. One read-only GET on the live PayPal API. The key file is /root/.paypal/live.env.
set -u
case "${1:-}" in /v1/*|/v2/*) ;; *) echo "usage: paypal-get '/v2/invoicing/invoices?page_size=5&total_required=true'" >&2; exit 2 ;; esac
set -a; . /root/.paypal/live.env; set +a
token=$(curl -s -m 30 -u "$PAYPAL_CLIENT_ID:$PAYPAL_SECRET" -d grant_type=client_credentials https://api-m.paypal.com/v1/oauth2/token \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
[ -n "$token" ] || { echo 'PayPal did not return a token.' >&2; exit 1; }
# --fail-with-body: an error answer from PayPal is still printed, and the exit code is 22.
exec curl -s --fail-with-body -m 60 -H "Authorization: Bearer $token" "https://api-m.paypal.com$1"
