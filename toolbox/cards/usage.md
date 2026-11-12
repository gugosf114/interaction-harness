# usage — tokens and calls on the two API accounts

  usage              today, this week (from Monday) and this month, for george (Anthropic) and g1 (OpenAI)
  usage --local      the same from the phone's own records only, with no provider call
  In a george or g1 chat: /usage
  usage-watch         saves the local meter now; phone timer 7743 runs it every 15 minutes
  usage-watch test    saves the meter and sends a phone notification with today's counts
  In chat: /usage-alarm [test], /on usage-alarm, /off usage-alarm

What it prints
  Usage logs (usage.jsonl and judge.jsonl): API calls, input tokens, output tokens, cache-read tokens.
    Every request counts: lane turns, gate retries, second-opinion calls and the mods' small-model calls.
  Saved turns: the same from history.db, one row per model turn.
  Phone time-zone rules set midnight, Monday and month boundaries, including DST.
  The timer saves state/usage-alarm/latest.json. It starts no tasks.
  Anthropic usage report / OpenAI usage report: the provider's own numbers for the whole account.

Keys
  The provider reports need an admin key: state/anthropic-admin-key or ANTHROPIC_ADMIN_KEY,
  state/openai-admin-key or OPENAI_ADMIN_KEY. Without one it tries the lane key.

Known failure (Nov 11, 2026)
  The lane keys cannot read the provider reports. Anthropic answers HTTP 401 "The Admin API requires an
  Admin API key or an organization-scoped API key." OpenAI answers HTTP 403 "Missing scopes: api.usage.read."
