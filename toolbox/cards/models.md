# models — ask another AI model one question from the shell

Each line is the one-shot form: it answers once and exits. Each uses that account's own plan.

Codex (OpenAI, on George's ChatGPT sign-in; Termux side)
  codex exec --skip-git-repo-check 'THE QUESTION'
  Prints a header, the answer and the token count. About 25 seconds. Model on 2026-11-19: gpt-6.2-astra.

Google (the Antigravity CLI on George's Google sign-in; Termux side)
  agy --print 'THE QUESTION'
  Not working (checked 2026-11-19): "Authentication required. Please visit the URL to log in", then
  "Error: authentication timed out." George opens that address once and signs in. Use gemini below meanwhile.

Claude Code (George's Claude subscription; Termux side)
  claude -p 'THE QUESTION'
  Prints the answer. Checked 2026-11-19: it answered, with no sign-in notice.

gemini (George's short name for the same Google sign-in; works on both sides)
  gemini 'THE QUESTION'     or     gemini -p 'THE QUESTION'     or     deb gemini 'THE QUESTION'
  Prints the answer only. It runs with tool permission checks off.

grok (xAI's Grok; Termux side)
  grok -p 'THE QUESTION'
  Prints the answer and exits. The program is installed (version 1.0.70).

glmchat (George's own tuned model on a rented GPU)
  deb glmchat
  It opens a chat that stays open; it has no one-shot form. It needs a running RunPod machine, which costs
  money by the hour. Checked 2026-11-19: RunPod has no machines running. See `cloud-check runpod`.
  glm, glmplain (Termux side): chat with the same model through ~/.glm_url. That file is gone, so both
  answer "GLM not live yet". glmoff ends the rented GPU machine at once (listed, not run). deb glm-mirror
  follows the model's log.

This client's other engines (each is one paid call; no shortcut word is installed for them)
  ~/interaction-harness/harness --engine gemini 'THE QUESTION'        answered 2026-11-19
  --engine openrouter (no key saved), --engine glm (cold start 6 to 10 minutes), --engine vertex (quota 0
  on 2026-11-11). Listed, not run today.

Known failure (checked 2026-11-19)
  grok answers "Not signed in. To authenticate without a browser, run: grok login --device-code".
  That command prints a web address and a code; George opens the address and types the code.
  codex exec without --skip-git-repo-check refuses to run outside a git folder.
