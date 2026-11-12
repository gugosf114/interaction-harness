# models — ask another AI model one question from the shell

Each line is the one-shot form: it answers once and exits. Each uses that account's own plan.

Codex (OpenAI, on George's ChatGPT sign-in; Termux side)
  codex exec --skip-git-repo-check 'THE QUESTION'
  Prints a header, the answer and the token count. About 25 seconds.

Google (the Antigravity CLI on George's Google sign-in; Termux side)
  agy --print 'THE QUESTION'
  Prints the answer only. About 6 seconds.

Claude Code (George's Claude subscription; Termux side)
  claude -p 'THE QUESTION'
  Prints the answer. It also prints a notice that this sign-in ends between 2026-11-17 and 2026-11-20.

gemini (George's short name for the same Google sign-in; works on both sides)
  gemini 'THE QUESTION'     or     gemini -p 'THE QUESTION'     or     deb gemini 'THE QUESTION'
  Prints the answer only. It runs with tool permission checks off.

grok (xAI's Grok; Termux side)
  grok -p 'THE QUESTION'
  Prints the answer and exits. The program is installed (version 1.0.70).

glmchat (George's own tuned model on a rented GPU)
  deb glmchat
  It opens a chat that stays open; it has no one-shot form. It needs a running RunPod machine, which costs
  money by the hour. Checked 2026-11-11: RunPod has no machines running. See `cloud-check runpod`.

Known failure (checked 2026-11-11)
  grok answers "Not signed in. To authenticate without a browser, run: grok login --device-code".
  That command prints a web address and a code; George opens the address and types the code.
  codex exec without --skip-git-repo-check refuses to run outside a git folder.
