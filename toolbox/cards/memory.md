# memory — George's notes and his past chats

On every call already
  George's core rules and his one-page profile ride along as two pages (state/pages.json). No command needed.

The notes (plain files on the Debian side)
  deb cat /root/.claude/projects/-root/memory/MEMORY.md             the index: one line per note, with its file name
  deb cat /root/.claude/projects/-root/memory/NOTE_FILE.md          one note
  deb rg -il 'WORD' /root/.claude/projects/-root/memory             which notes mention a word
  The index is about 18,700 characters. Read it in two slices:
  deb sed -n '1,60p' /root/.claude/projects/-root/memory/MEMORY.md

recall: the best lines from past chats
  deb python3 /root/.claude/recall.py "bakery voicemail"
  Up to six lines, each with its date and source: "- [2026-10-27 me · claude#36282] Found it. ..."
  It searches the turn index /root/corpus.db (June 2026 to now). It changes nothing.

search-chats: a full search of every saved transcript
  deb search-chats 'WORDS'          (the same as: deb po find 'WORDS')
  Searches every Claude and Codex transcript on the phone, and the laptop's when it is reachable.
  It writes a digest file to ~/postoffice/MMDD-HHMM-words.md and shows a phone notification.
  deb po list                       the newest digests

The full archive
  /data/data/com.termux/files/home/conversation-corpus : 2,108 conversations, August 2024 to November 2026.

Known failure
  `deb recall "WORDS"` hangs until the timeout (exit 124, no output). The file /usr/local/bin/recall is
  broken. The python3 form above is the same tool and works.
