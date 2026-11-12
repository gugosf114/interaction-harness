# lessons — George's corrections kept for good: a fact on every later call, a rule in the gate

Runs on: either side. Both commands do their work on the Debian side.

When
  George types /wrong WORDS in a chat. The client saves the case as a history row and hands it to you
  with the row number N. A fact goes on the lessons page. A habit becomes a gate rule. Both take --row N.

A fact: the lessons page
  lesson add --row N 'The harness repo is gugosf114/interaction-harness.'
      One plain sentence. Prints "Added lesson 3: 2026-11-11 (row N): ..."  exit 0
      The line goes into state/lessons.md. Every later call carries that page: every session, both lanes.
  lesson list                      numbered lines: date, row, fact
  lesson drop 3                    removes line 3 as `lesson list` numbers it

A habit: a gate rule
  rule add NAME --row N --action strip_sentence --pattern 'REGEX' --bad 'A SENTENCE TO STOP' [--bad 'ANOTHER']
      NAME      lower-case letters, digits and hyphens
      --action  strip_sentence cuts every sentence the pattern matches and keeps the rest of the answer.
                reject sends the whole reply back to the model for one corrected try.
      --pattern a Python regular expression, matched inside one sentence at a time, case ignored
      --bad     a sentence the rule must match; take it from the corrected answer
      The command tests the rule before it stores it.
      Works:    Added rule "NAME" (strip_sentence) for history row N. ...   exit 0
      Refuses:  Rule "NAME" was refused. It does not match its own bad sentence: ...   exit 1
                Rule "NAME" was refused. It matches 12 known-good sentences: ...   exit 1
                No history row N. ...   exit 1
  rule list                        every rule: name, action, date, row, pattern, bad sentences
  rule test                        tests every stored rule again; exit 1 when one fails
  rule test --text 'WORDS'         shows what the gate would cut from WORDS
  rule drop NAME

Writing the pattern
  Name the words that make the sentence what it is: '\bstay hydrated\b'   '^good luck\b'   '\bhappy (coding|building)\b'
  Inside single quotes the shell passes a backslash through as written.
  A single quote inside a quoted sentence: close, add \', open again:   --bad 'Let'\''s keep going.'
  The gate uses a new rule from the next reply. An open chat needs no restart.

A habit no pattern can express
  card self        the check is written in code, in habit_checks.py

Known failure
  "It matches N known-good sentences" means the pattern is too wide. gate_known_good.txt lists sentences that
  must stay; the fix is a narrower pattern.
