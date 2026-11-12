# self — change this harness's own code, test it, and land it on main

Runs on: the Termux side. The tests run on the Debian side; self-update goes there itself.

The code
  The live folder is ~/interaction-harness: the installation this chat runs from. It is never edited in place.
  The repo is gugosf114/interaction-harness on GitHub. main is what George runs.

The move, start to finish
  1. self-clone
       Makes the working copy ~/harness-self at the tip of main, or refreshes it. Prints its path.  exit 0
  2. Read before you change:
       sed -n '1,60p' ~/harness-self/habit_checks.py
       rg -n 'PATTERN' ~/harness-self --glob '*.py'
  3. Make the change with exact edits:
       edit-exact ~/harness-self/FILE.py 'OLD TEXT' 'NEW TEXT'
     A new file:   set -C; cat > ~/harness-self/NAME.py <<'END'  ...  END
  4. Add a test that fails without the change, in a test_*.py file in ~/harness-self. Run one test file:
       deb sh -c 'cd /data/data/com.termux/files/home/harness-self && .venv/bin/python -B -m unittest test_habit_checks'
  5. self-update 'fix: one line that says what changed'
       Commits the working copy, rebases it onto main, runs the full suite, pushes to main,
       and fast-forwards the live folder.
       Works:     Landed abc1234 on main: ...
                  The live folder is at abc1234, the commit the suite passed on: Ran N tests in Ns, all passed.   exit 0
       Refuses:   Tests failed in the working copy (exit 1). Nothing was pushed.   exit 1   (the failing output is above it)
       Conflict:  The change conflicts with main in: FILE. Nothing was pushed.   exit 3
  6. Tell George to type exit and reopen the chat with -c. The open chat runs the old code until then.

Where a new filter goes
  A sentence to cut wherever it stands: add it to CUT_SENTENCES in habit_checks.py, with a test in test_habit_checks.py.
  A habit that needs logic: write a function (answer, asked) that returns None or one sentence saying what is wrong,
  add it to CHECKS in habit_checks.py, with a test. The gate asks the model for one corrected reply when it returns a sentence.
  A habit a regular expression can hold needs no code: card lessons.

Facts
  self-clone on a working copy that holds unlanded work prints that work and leaves it alone.
  prefix_block.txt is pinned by a hash in harness.py. A changed page stops every call until the hash matches.
  self-update takes about as long as one full test run. When more landed on main meanwhile, the suite runs in the live folder too.

Known failure
  A command gets at most 600 seconds. A suite that runs longer cuts self-update off part way. See where it stopped:
    git -C ~/harness-self status --short ; git -C ~/harness-self log origin/main..HEAD --oneline
  Then run self-update again.
