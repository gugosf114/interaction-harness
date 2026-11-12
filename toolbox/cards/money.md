# money — PayPal, the bakery's live account

Read (Termux command; it can only read)
  paypal-get '/v2/invoicing/invoices?page_size=10&total_required=true'
      JSON: total_items (210 on 2026-11-11) and items[], newest first. Each item has id, status,
      detail.invoice_number, detail.invoice_date, amount.value, primary_recipients.
  paypal-get '/v2/invoicing/invoices?page_size=10&page=2&total_required=true'      the next page
  paypal-get '/v2/invoicing/invoices/INVOICE_ID'                                   one invoice, every field
  Shorter view:
  paypal-get '/v2/invoicing/invoices?page_size=10' | jq -r '.items[] | [.detail.invoice_date, .status, .amount.value, .detail.invoice_number] | @tsv'

Transactions
  paypal-get '/v1/reporting/transactions?start_date=2026-11-01T00:00:00Z&end_date=2026-11-11T00:00:00Z'
  Not working (checked 2026-11-11): {"name":"NOT_AUTHORIZED","message":"Authorization failed due to
  insufficient permissions."}. The PayPal app "Invoice Tool" has no transaction-search permission.

Create a draft invoice (Debian side; the invoice is a JSON file)
  deb bash -c 'set -a; . /root/.paypal/live.env; set +a; T=$(curl -s -u "$PAYPAL_CLIENT_ID:$PAYPAL_SECRET" -d grant_type=client_credentials https://api-m.paypal.com/v1/oauth2/token | jq -r .access_token); curl -s -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d @/FULL/PATH/invoice.json https://api-m.paypal.com/v2/invoicing/invoices'
  This creates a draft invoice on the live account. The customer is not told.

Send an invoice
  The same command with this ending in place of the last curl:
  curl -s -X POST -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "{}" https://api-m.paypal.com/v2/invoicing/invoices/INVOICE_ID/send
  This emails a real invoice to the customer at once.

House rules for bakery invoices
  deb cat /root/.claude/projects/-root/memory/paypal-invoice-house-rules.md
  deb cat /root/.claude/projects/-root/memory/mbc-invoice-email-shape.md

Where the key lives
  /root/.paypal/live.env (client id and secret of the PayPal app "Invoice Tool"). A token lasts 9 hours;
  paypal-get asks for a fresh one on every run.

Known failure
  "PayPal did not return a token.": the key file is missing or PayPal is unreachable.
