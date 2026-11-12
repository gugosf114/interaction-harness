# github — gh and git, signed in as gugosf114

Runs on: the Termux side. `gh auth status` shows the sign-in.

Look
  gh repo list gugosf114 --limit 20                  George's own repos
  gh repo list abrahamyants --limit 20               the organization's repos (WiM Android lives here)
  gh pr list --repo OWNER/REPO
  gh pr view 12 --repo OWNER/REPO
  gh issue list --repo OWNER/REPO
  gh run list --repo OWNER/REPO --limit 5            the newest CI runs
  gh api repos/OWNER/REPO/commits/main --jq .sha     the newest commit on main

Read one file without cloning
  gh api repos/OWNER/REPO/contents/PATH/TO/FILE --jq .content | base64 -d

Get the code
  gh repo clone OWNER/REPO ~/FOLDER
  git -C ~/FOLDER log --oneline -5
  git -C ~/FOLDER status --short

Change GitHub (each line acts on GitHub at once)
  git -C ~/FOLDER push
  gh pr create --repo OWNER/REPO --title 'TITLE' --body 'TEXT'
  gh pr merge 12 --repo OWNER/REPO --squash
  gh issue create --repo OWNER/REPO --title 'TITLE' --body 'TEXT'

Facts
  GitHub shows times in UTC. Pacific time is 8 hours earlier in winter and 7 in summer.
  The main repos: gugosf114/interaction-harness (this tool), gugosf114/bakers-agent,
  gugosf114/gugosf114.github.io (the bakery site), abrahamyants/wim-android.

Known failure
  `gh pr list` with no --repo fails outside a git folder. Name the repo.
