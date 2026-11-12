# usage — tokens and calls on the two API accounts

  usage              today, this week (from Monday) and this month, for george (Anthropic) and g1 (OpenAI)
  usage --local      the same from the phone's own records only, with no provider call
  In a george or g1 chat: /usage

What it prints
  Usage log: one line per lane and window: API calls, input tokens, output tokens, cache-read tokens.
    Every request counts: lane turns, gate retries, /advisor calls and the mods' small-model calls.
  Saved turns: the same from history.db, one row per model turn.
  Anthropic usage report / OpenAI usage report: the provider's own numbers for the whole account.

Keys
  The provider reports need an admin key: state/anthropic-admin-key or ANTHROPIC_ADMIN_KEY,
  state/openai-admin-key or OPENAI_ADMIN_KEY. Without one it tries the lane key.

Known failure (Nov 11, 2026)
  The lane keys cannot read the provider reports. Anthropic answers HTTP 401 "The Admin API requires an
  Admin API key or an organization-scoped API key." OpenAI answers HTTP 403 "Missing scopes: api.usage.read."
