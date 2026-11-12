"""Answer checks rebuilt from George's Claude Code hooks, for the lanes' gate.

Four checks send an answer back once with a reason (the harness's usual one retry):
  length         from hooks/answer-length.sh   a yes/no question gets a short answer
  plain-words    from hooks/plain-words.sh     reading grade 5 or lower, no listed jargon
  receipts       from hooks/receipts-gate.py   a WiM behaviour claim needs a receipt this turn, or GUESS
  no-background  from hooks/no-background.sh   a command must not detach from the session
The two style hooks skip a second Stop call (stop_hook_active); the lanes keep that behavior.
Receipts and foreground execution must pass after the single retry, or the reply is withheld.

One more, undertaker (from the proof-marks mod), removes pure filler lines in code with no retry.
Every function is pure. Switches and play mode are read by the caller (soft_violation).
"""
from __future__ import annotations

import json
import os
import re

import mod_switches
import receipt_context

# The Claude Code switches these hooks already honour. Read-only; the lanes never write them.
PLAY_MODE = '/root/.claude/play-mode'
PLAIN_WORDS_OFF = ('/root/.claude/plain-words-off', '/data/data/com.termux/files/home/.claude/plain-words-off')
CONTINUATION = 'Continue the original task using the recorded execution observation.'

# ---------------------------------------------------------------- length
CLOSED_MAX, SHORT_MAX, DEFAULT_MAX = 40, 120, 250
BUILD_ORDER = re.compile(r'\b(go ahead|do it|just do it|build it|fix it|push|commit|implement|deploy|refactor|rename)\b', re.I)
CLOSED_OPEN = re.compile(
    r"^\s*(?:(?:so|and|but|ok(?:ay)?|well|yeah)\s+)*(?:is|are|was|were|isn'?t|aren'?t|wasn'?t|weren'?t|do|does|did|"
    r"don'?t|doesn'?t|didn'?t|can|can'?t|could|will|won'?t|would|should|shouldn'?t|have|has|had|haven'?t|am|any)\b", re.I)
CLOSED_TAG = re.compile(r"(isn'?t it|aren'?t they|right\??\s*$|correct\??\s*$|true\??\s*$|no\??\s*$|yes or no)", re.I)
ASKING = re.compile(r'\b(what|why|how|when|where|which|who|whose|whether|explain|describe|tell me|walk me)\b', re.I)
JAR_LINE = re.compile(r'^\[(hedges|held back|guessed|bottom line)\]', re.I)
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


def _prose(text: str) -> str:
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    lines = [l for l in text.splitlines() if not l.strip().startswith('|') and not JAR_LINE.match(l.strip())]
    return '\n'.join(lines)


def length(answer: str, asked: str) -> str | None:
    """answer-length.sh: the shape of George's message sets a word ceiling on the answer."""
    if not asked or BUILD_ORDER.search(asked):
        return None
    if CLOSED_OPEN.search(asked) or CLOSED_TAG.search(asked):
        cap, kind = CLOSED_MAX, 'a yes/no question'
    elif '?' in asked or ASKING.search(asked):
        cap, kind = SHORT_MAX, 'a question'
    else:
        cap, kind = DEFAULT_MAX, 'something that was not a build order'
    words = len(WORD.findall(_prose(answer)))
    if words <= cap:
        return None
    return (f'answer too long - He asked {kind}. The answer runs {words} words; the ceiling is {cap}. '
            'Give the direct answer and stop. Anything he did not ask for - background, what it means, why it '
            'matters, what follows from it - comes out. If something genuinely needs saying beyond the answer, '
            'offer it in one short sentence and let him ask. Do not mention this check.')


# ---------------------------------------------------------------- plain words
GRADE_MAX = 5.0
JARGON = {
    'regex', 'lambda', 'parity', 'deterministic', 'semantic', 'instantiate', 'invocation',
    'idempotent', 'concurrency', 'asynchronous', 'serialization', 'abstraction', 'heuristic',
    'predicate', 'recursion', 'refactor', 'instrumentation', 'orchestration', 'provenance',
    'granularity', 'blast', 'radius', 'architecture', 'architectural', 'implementation',
    'configuration', 'deprecated', 'ephemeral', 'persistence', 'normalization', 'validation',
    'traversal', 'enumerate', 'canonical', 'arbitrary', 'subsequent', 'respective', 'utilize',
    'leverage', 'facilitate', 'paradigm', 'stochastic', 'probabilistic', 'overhead', 'latency',
}


def _beats(word: str) -> int:
    w = word.lower()
    n = len(re.findall(r'[aeiouy]+', w))
    if w.endswith('e') and n > 1 and not w.endswith(('le', 'ee')):
        n -= 1
    return max(n, 1)


def reading(answer: str) -> tuple[float, list[str]]:
    """(Flesch-Kincaid grade, jargon words), measured the way plain-words.sh does. Grade 0 when under 25 words."""
    raw = _prose(answer)
    raw = re.sub(r'`[^`]*`', ' ', raw)
    raw = re.sub(r'https?://\S+', ' ', raw)
    raw = re.sub(r'\S*/\S*', ' ', raw)
    sentences = [s for s in re.split(r'[.!?]+(?:\s|$)', raw) if s.strip()]
    words = WORD.findall(raw)
    if len(words) < 25 or not sentences:
        return 0.0, []
    grade = 0.39 * len(words) / len(sentences) + 11.8 * sum(_beats(w) for w in words) / len(words) - 15.59
    return round(grade, 1), sorted({w.lower() for w in words if w.lower() in JARGON})


def plain_words(answer: str) -> str | None:
    grade, jargon = reading(answer)
    reason = ''
    if grade > GRADE_MAX:
        reason = f'This reads at grade {grade}. The ceiling is {GRADE_MAX:g}. Cut sentence length and swap long words for short ones.'
    if jargon:
        reason += (' ' if reason else '') + ('Jargon present: ' + ','.join(jargon) + '. Say each one in ordinary words, '
                                             'or show it with a concrete thing the reader can picture.')
    if not reason:
        return None
    return 'plain words - ' + reason + ' Rewrite the whole answer, keeping every fact. Do not mention this check.'


# ---------------------------------------------------------------- receipts
WIM_WORDS = re.compile(r'\b(wim|bubble|facehug\w*|face-hug\w*|reconstruct\w*|whisper|clarifier|'
                       r'send[_ ]?ready|l[1-4]\b|layer [1-4])\b', re.I)
BEHAVIOR_VERBS = re.compile(
    r'\b(sends?|sending|records?|recording|injects?|injecting|taps?|tapping|counts?|countdown|uploads?|listens?|'
    r'deletes?|reads?|writes?|shows?|jumps?|turns?|reverts?|falls? back|downgrades?|recognizes?|transcribes?|'
    r'translates?|syncs?|bills?|charges?)\b', re.I)
SELF_TALK = re.compile(r"\b(I|I'll|I'm|me|my)\b")
RECEIPT_MARKS = ('wim-android', 'logcat', 'BubbleService', 'WhisperClient', 'ReconstructClient', 'BubbleAffect',
                 'MeaningGuard', 'AndroidManifest', 'wim_users', 'wim-reconstruct')


def turn_evidence(history: list, current_input: str | None = None) -> str:
    """Command results of this turn: execution observations after George's latest own message."""
    def data(content):
        if not isinstance(content, str):
            return True
        if content.startswith(CONTINUATION):
            return True
        try:
            return isinstance(json.loads(content), dict)
        except ValueError:
            return False
    start = 0
    if current_input is not None and not data(current_input):
        start = len(history)
    else:
        for index, message in enumerate(history):
            if message.get('role') == 'user' and not data(message.get('content')):
                start = index
    return receipt_context.text(history[start:], {'execution_observation', 'api_tool_observations'})


def receipts(answer: str, evidence: str) -> str | None:
    claims = [s for s in re.split(r'(?<=[.!?])\s+', answer)
              if WIM_WORDS.search(s) and BEHAVIOR_VERBS.search(s) and not SELF_TALK.search(s)]
    if not claims or re.search(r'\bGUESS\b', answer):
        return None
    low = evidence.lower()
    if any(mark.lower() in low for mark in RECEIPT_MARKS):
        # Action words only: WiM nouns sit in every WiM file and would bless any unrelated read.
        words = {w.lower() for s in claims for w in BEHAVIOR_VERBS.findall(s)}
        if any(w and w in low for w in words):
            return None
    return ('receipts - This reply states how WiM behaves, but this turn read no WiM code or log matching the claim. '
            'Either read the relevant source now and answer from it, or resend with the word GUESS stamped next to '
            'the unverified claim. Do not mention this check.')


# ---------------------------------------------------------------- no background
DETACH = re.compile(r'(?:^|[;&|\s(])(nohup|setsid|disown)(?:\s|$|;)', re.M)
TRAILING_AMP = re.compile(r'(?<![&|>])&(?!&)\s*(?:$|;|\n|\))', re.M)


def no_background(payload: str | None) -> str | None:
    if not payload:
        return None
    found = DETACH.search(payload)
    if found or TRAILING_AMP.search(payload):
        how = found.group(1) if found else 'a trailing &'
        return (f'no background - Standing rule: foreground only. This command detaches from the session ({how}). '
                'Give a command that runs in the foreground, where its result comes back.')
    return None


# ---------------------------------------------------------------- undertaker
JUNK = [re.compile(p, re.I) for p in (
    r"\bdon'?t worry\b", r'no need to worry', r'nothing to worry', r'not to worry', r'rest assured', r'rest easy',
    r'\bno problem\b', r'nothing is wasted', r"that'?s not a (failure|problem|bad|mistake)", r"there'?s nothing (wrong|to)",
    r'i hope (this|that) helps', r'hope (this|that) helps', r'feel free to', r'let me know if',
    r"i want to be (transparent|clear|honest)", r'i should (note|mention|add)', r"it'?s worth noting",
    r"for what it'?s worth", r'at the end of the day', r'just to be (safe|clear|sure)', r'to be clear\b',
    r"i('| a)m happy to", r'great question', r'good question')]
SUBSTANCE = [re.compile(p) for p in (r'\d', r'[$€£]', r'/', r'`', r'(?i)https?:', r'\b[A-Z]{2,}\b')]
VERDICT = re.compile(r'\b(ship|kill|push|send|sent|merge|merged|delete|deployed|done|works?|fixed|built|live|'
                     r'pass(ed)?|fail(ed)?|green|red|stop)\b', re.I)


def is_junk(line: str) -> bool:
    """The Undertaker's rule: a junk phrase AND nothing solid. In any doubt, keep."""
    t = line.strip()
    if not t or len(t) > 200 or not any(r.search(t) for r in JUNK):
        return False
    return not (any(r.search(t) for r in SUBSTANCE) or VERDICT.search(t))


def undertaker(answer: str) -> str:
    kept = [line for line in answer.split('\n') if not is_junk(line)]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(kept)).strip()


# ---------------------------------------------------------------- the gate's entry point
def play_mode() -> bool:
    return os.path.exists(PLAY_MODE)


def soft_violation(reply, asked: str, history: list, current_input: str | None, state, tool_uses=None) -> str | None:
    """The first failing check's reason, or None. reply is the validated HarnessReply."""
    answer = reply.direct_answer
    on = lambda name: mod_switches.is_on(name, state)
    if on('no-background'):
        reason = no_background(reply.execution_payload)
        if reason:
            return reason
    if play_mode():
        return None   # George's chit-chat sign: the style gates step aside, as in Claude Code.
    words_off = any(os.path.exists(p) for p in PLAIN_WORDS_OFF)
    if on('length') and not words_off:
        reason = length(answer, asked)
        if reason:
            return reason
    if on('plain-words') and not words_off:
        reason = plain_words(answer)
        if reason:
            return reason
    if on('receipts'):
        evidence = turn_evidence(history, current_input)
        if tool_uses:
            evidence += '\n' + json.dumps({'type': 'api_tool_observations', 'uses': tool_uses}, ensure_ascii=False)
        reason = receipts(answer, evidence)
        if reason:
            return reason
    return None
