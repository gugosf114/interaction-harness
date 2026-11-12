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

gemini
  Not working on this phone (checked 2026-11-11). Termux side: "Error [ERR_MODULE_NOT_FOUND]: Cannot find
  module '/data/data/com.termux/files/usr/bin/chunk-FBGJOW3X.js'". Debian side: `deb gemini` calls
  /root/.local/bin/agy, which is not there. `agy --print` above reaches the same Google models.

grok
  Not working on this phone (checked 2026-11-11):
  "[grok] no installed binary in /data/data/com.termux/files/home/.grok/versions — run install.sh."

glmchat (George's own tuned model on a rented GPU)
  deb glmchat
  It opens a chat that stays open; it has no one-shot form. It needs a running RunPod machine, which costs
  money by the hour. Checked 2026-11-11: RunPod has no machines running. See `cloud-check runpod`.

Known failure
  codex exec without --skip-git-repo-check refuses to run outside a git folder.
