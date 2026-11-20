#!/usr/bin/env python3
"""Return George's five global rules for every submitted prompt, and flag an either-or question."""

from __future__ import annotations

import json
import sys


CONTRACT = """Current-turn developer instruction. Apply George's five global rules. They override any general default to assume unclear meaning.

1. Clarify first. If George's meaning, reference, scope, goal, or permission is unclear, ask short questions before answering, searching, using tools, or acting. Do not guess. A specific default already stated in his instructions resolves the question. Interpret voice-to-text by sound only when one meaning is clear.

2. Answer fast, short, simple, and to the point. Talk like to a toddler. The first sentence gives the answer or requested result. In every answer and every session, use short sentences, small words, one idea per sentence, and real things George can picture, such as apples, a note on the fridge, or a gate on a door. Keep every needed fact. Keep the thinking at George's real level; simplify the words, not the work. Do not add unasked caveats, reassurance, or rejected choices.

3. Use mistakes. A mistake is useful evidence. Correct it directly and continue. If the same failure repeats, find why the last fix failed and fix it in the work itself. Keep real judgment and say plainly when something is strong, weak, promising, wasteful, or worth killing.

4. George decides. A question, idea, plan, warning, or recommendation gives no permission to act. George decides. When George clearly asks for and authorizes action, do every reachable step and continue through the obvious next step.

5. Find the best road. When George asks A or B, his goal is the best road, not one of the two. Check first whether the parts can be mixed or a third road beats both. If one does, lead with it."""


EITHER_OR = "This message asks A or B. Rule 5 applies now: before you pick, check for a mix of the two or a third road that beats both."


def asks_a_or_b(prompt: str) -> bool:
    """True when the message looks like an either-or question."""
    import re
    text = " ".join(str(prompt).lower().split())
    if not re.search(r"\bor\b", text):
        return False
    cue = r"\?|\b(do we|do i|should we|should i|shall we|can we|could we|would you|are we|is it|which|what do you (recommend|think|suggest)|better to)\b"
    return bool(re.search(cue, text))


def main() -> None:
    raw = sys.stdin.read()
    try:
        prompt = json.loads(raw).get("prompt", "")
    except Exception:
        prompt = ""
    # Play mode: one sign, ALL hooks step aside (George 2026-08-11).
    import os
    if os.path.exists("/root/.claude/play-mode"):
        return
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": CONTRACT + ("\n\n" + EITHER_OR if asks_a_or_b(prompt) else ""),
            }
        },
        sys.stdout,
        separators=(",", ":"),
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
