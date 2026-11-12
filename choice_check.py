"""The choice check: when the operator gave an instruction, the reply must not ask leave to carry it out.

Built like harness.claims_completion(): finite wording patterns, read sentence by sentence, with quoted
text removed first. It rejects a reply that asks permission for the ordered work ("Do you want me to...",
"Should I proceed?", "Shall I...", "Would you like me to...", "Let me know when...") and a reply that ends
by offering the work instead of doing it ("I can run it for you."). The gate then asks for one corrected
reply, as it does for every other rejection.

A question about a missing fact stays: a question that opens with which, what, where, when, who or how,
and a question that offers real alternatives ("Should I use main or dev?"). The check is skipped when the
request is not an instruction, and when the operator himself asked to be asked first.
"""
from __future__ import annotations

import re

# Words that may sit in front of the order in dictated speech.
_LEAD = (r"(?:(?:ok(?:ay)?|so|now|then|and|also|well|hey|alright|all\s+right|right|yes|yeah|yep|sure|uh|um|please|"
         r"just|next|first|george|go\s+ahead\s+and)[,.!:;]?\s+)*")
# Verbs an order starts with. A finite list, not a grammar.
_VERBS = (r"(?:add|apply|archive|attach|audit|back\s+up|build|call|cancel|cast|change|check|clean|clear|clone|close|"
          r"commit|compare|compile|configure|connect|continue|convert|copy|count|create|cut|debug|delete|deploy|"
          r"describe|diff|disable|do|download|draft|drop|dump|edit|email|enable|execute|explain|export|extract|"
          r"fetch|fill|find|finish|fix|format|forward|generate|get|give|go|grab|grep|import|inspect|install|kill|"
          r"land|launch|link|list|load|lock|log|look|make|mark|merge|mount|move|open|patch|pick|ping|play|post|"
          r"prepare|print|proceed|pull|push|put|read|rebase|record|refresh|register|reinstall|reload|remove|rename|"
          r"repair|replace|reply|report|rerun|reset|resolve|restart|restore|resume|retry|revert|review|rewrite|run|"
          r"save|scan|schedule|search|send|set|show|sign|sort|start|stop|submit|summarize|switch|sync|tag|take|"
          r"tell|test|text|trace|translate|trim|try|turn|type|undo|uninstall|unlock|unmount|update|upgrade|upload|"
          r"use|verify|wipe|wire|write|zip)")
# An order: an imperative, a polite request, or "I want / I need". "Do you know..." is a question, not "do".
ORDER = re.compile(
    r"^" + _LEAD + r"(?:"
    + _VERBS + r"\b(?!\s+(?:you|we|they|i)\b)|"
    r"(?:can|could|would|will|won['’]t)\s+you\s+(?:please\s+|kindly\s+|just\s+|also\s+|now\s+)*" + _VERBS + r"\b|"
    r"i\s+(?:want|need|would\s+like|['’]d\s+like)\b|"
    r"you\s+(?:should|must|need\s+to|have\s+to)\s+" + _VERBS + r"\b|"
    r"let['’]?s\s+" + _VERBS + r"\b|"
    r"(?:do\s+not|don['’]?t|never)\s+(?:stop|ask|wait|pause|quit)\b"
    r")", re.IGNORECASE)
# The operator asked to be asked: "ask me first", "before you delete", "don't run it yet", "plan only".
# Then a permission question is the answer he ordered.
ASKED_TO_ASK = re.compile(
    r"\b(?:ask|check\s+with|confirm\s+with|run\s+it\s+by|clear\s+it\s+with)\s+me\b|"
    r"\b(?:ask|check|confirm)\s+(?:first|before)\b|"
    r"\bwait\s+for\s+(?:me|my)\b|\b(?:until|unless|before|after)\s+i\s+(?:say|approve|confirm|ok(?:ay)?|agree|tell|review|look)\b|"
    r"\bbefore\s+you\b|\bmy\s+(?:ok(?:ay)?|approval|go[- ]ahead|permission|sign[- ]off|say[- ]so)\b|"
    r"\b(?:do\s+not|don['’]?t|never)\s+(?:\w+\s+){0,4}?(?:yet|until|unless|before|without\s+asking)\b|"
    r"\b(?:do\s+not|don['’]?t|never)\s+(?:actually\s+)?(?:run|do|start|change|delete|send|push|touch|execute|install|"
    r"apply)\s+(?:it|this|that|them|anything|a\s+thing)\b|"
    r"\b(?:dry\s+run|plan\s+only|only\s+(?:the\s+)?plan|no\s+changes\s+yet|hold\s+off|not\s+yet)\b|"
    r"\b(?:show|give|tell)\s+me\s+(?:\w+\s+){0,4}?first\b|\bfirst\s+(?:show|give|tell)\s+me\b|"
    r"\bwithout\s+(?:running|doing|changing|executing|sending)\b", re.IGNORECASE)

# Permission-asking, anywhere in a sentence.
ASKS_LEAVE = re.compile(
    r"\b(?:do|did|would|will)\s+you\s+(?:want|like|need|prefer|wish)\s+(?:for\s+)?me\s+to\b|"
    r"\bwould\s+you\s+(?:like|prefer)\s+(?:it|this|that|them|these|those|a|an|the|to\s+have)\b|"
    r"(?:^|[,;:—–-]\s*)want\s+me\s+to\b|"
    r"\blet\s+me\s+know\s+(?:if|whether|when|once)\b|"
    r"\b(?:just\s+)?say\s+(?:the\s+word|go|yes)\b|"
    r"\b(?:tell|ping|message)\s+me\s+(?:if|when|whether|once)\s+(?:you(?:['’]d|\s+would)?\s+(?:like|want)|i\s+should)\b|"
    r"\bif\s+you(?:['’]d|\s+would)?\s+(?:like|want|prefer|wish|need)\b[^.!?\n]*?\bi\s*(?:can|could|will|['’]ll|would|may)\b|"
    r"\bi\s*(?:can|could|will|['’]ll|would)\b[^.!?\n]*?\bif\s+you(?:['’]d|\s+would)?\s+(?:like|want|prefer|wish)\b|"
    r"\b(?:ready|happy|glad)\s+(?:to\s+\w+\s+)?(?:when|whenever|once)\s+you\b|"
    r"\b(?:confirm|approve)\b[^.!?\n]*?\b(?:(?:and|then|so)\s+i(?:['’]ll|\s+will|\s+can)\b|before\s+i\s+\w+)|"
    r"\b(?:awaiting|waiting\s+(?:for|on)|pending)\s+your\s+(?:confirmation|approval|go[- ]ahead|ok(?:ay)?|permission|"
    r"answer|decision|call|word)\b|"
    r"\b(?:with|on|upon|after|given)\s+your\s+(?:confirmation|approval|go[- ]ahead|ok(?:ay)?|permission)\b|"
    r"\bdo\s+i\s+have\s+your\s+(?:permission|approval|ok(?:ay)?|go[- ]ahead)\b|"
    r"\bis\s+(?:it|that)\s+ok(?:ay)?\s+(?:if\s+i|to|for\s+me\s+to)\b", re.IGNORECASE)
# The same, as a direct question. These count only in a sentence that ends in a question mark.
ASKS_LEAVE_QUESTION = re.compile(
    r"(?:^|[,;:—–-]\s*|\b(?:so|and|but|now|then)\s+)(?:should|shall)\s+i\b|"
    r"(?:^|[,;:—–-]\s*|\b(?:so|and|but|now|then)\s+)(?:can|could|may)\s+i\s+(?:go\s+ahead|proceed|continue|start|begin|run|"
    r"do|delete|remove|install|send|push|make|apply|execute|change|overwrite|merge|deploy)\b|"
    r"(?:^|[,;:—–-]\s*)(?:ready\s+to\s+)?(?:proceed|continue|go\s+ahead)\s*\?", re.IGNORECASE)
# The last sentence offers the work instead of doing it. "I can tell that..." and "I can find no..." are observations.
OFFER = re.compile(
    r"^(?:(?:next|then|also|alternatively|from\s+here|after\s+that|if\s+needed)[,:]?\s+)?"
    r"i\s+(?:can|could)\s+(?:also\s+|then\s+|now\s+|next\s+|easily\s+|just\s+)*(?!tell\b(?!\s+you\b))" + _VERBS
    + r"\b(?!\s+(?:no|nothing|none|neither)\b)|"
    r"^i(?:['’]m|\s+am)\s+(?:ready|able|happy|glad|standing\s+by)\s+to\b|"
    r"^i(?:['’]ll|\s+will)\s+[^.!?\n]*?\b(?:once|when|as\s+soon\s+as|after|if)\s+you\b", re.IGNORECASE)
# A question about a missing fact opens with one of these.
FACT_QUESTION = re.compile(r"^(?:[*_#>\s-]|\d+[.)]\s)*(?:and\s+|so\s+|but\s+)?(?:which|what|where|when|who|whom|whose|how)\b",
                           re.IGNORECASE)
# A question that opens that way and still only asks for a go-ahead: "How would you like me to proceed?"
HOLLOW_QUESTION = re.compile(
    r"\b(?:like|want|prefer)\s+me\s+to\s+(?:proceed|continue|go\s+ahead|do\s+(?:next|now|here)|do\s*\?|handle\s+(?:it|this|that))|"
    r"^(?:how|what)\s+about\s+i\b|^what\s+if\s+i\b|\bwhat\s+(?:should|shall)\s+i\s+do\b|"
    r"\bwhat\s+(?:would|do)\s+you\s+(?:like|want)\s+(?:me\s+to\s+do|next|to\s+do\s+next)\b|^what\s+next\b",
    re.IGNORECASE)
# After "or", these words mean "or not": the question is still yes or no.
_NO_CHOICE = re.compile(
    r"^\s*(?:not\b|no\b|(?:should|shall|do|would|will|can)\s+(?:i|you)\s+(?:\w+\s+){0,3}?"
    r"(?:wait|hold|stop|skip|leave|cancel|abort|pause|rather|prefer|not)\b|"
    r"(?:wait|hold|stop|skip|leave|cancel|abort|pause|nothing)\b)", re.IGNORECASE)
QUOTED = re.compile(r'```[\s\S]*?```|`[^`\n]*`|"[^"\n]*"|“[^”\n]*”|(?<!\w)\x27[^\x27\n]*\x27(?!\w)')
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def is_instruction(asked: str) -> bool:
    """True when the operator's request holds an order: an imperative, a polite request, or "I want"."""
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", asked or ''):
        if ORDER.match(sentence.strip(' \t"\x27“”‘’*_-')):
            return True
    return False


def offers_real_choice(sentence: str, start: int) -> bool:
    """True when the question names alternatives after the match: "main or dev", not "or not"."""
    rest = sentence[start:]
    found = re.search(r"\bor\b", rest, re.IGNORECASE)
    return bool(found) and not _NO_CHOICE.match(rest[found.end():])


def permission_phrase(answer: str) -> str | None:
    """The words that ask leave or offer the work, or None. Quoted text and fact questions are not counted."""
    sentences = [part.strip() for part in SENTENCE_BREAK.split(QUOTED.sub(' ', answer)) if part.strip(' \t.!?*_')]
    for sentence in sentences:
        core = sentence.lstrip(' \t*_#>-')
        if FACT_QUESTION.match(core):
            hollow = HOLLOW_QUESTION.search(core)
            if hollow:
                return ' '.join(hollow.group(0).split())
            continue
        found = ASKS_LEAVE.search(core)
        if found is None and core.rstrip(' *_').endswith('?'):
            found = ASKS_LEAVE_QUESTION.search(core)
        if found and not offers_real_choice(core, found.start()):
            return ' '.join(found.group(0).split()).strip(' ,;:—–-')
    if sentences:
        offer = OFFER.match(sentences[-1].lstrip(' \t*_#>-'))
        if offer:
            return ' '.join(offer.group(0).split())
    return None


def violation(answer: str, asked: str | None) -> str | None:
    """The reason for the gate's corrective retry, or None when the reply stands."""
    if not asked or not is_instruction(asked) or ASKED_TO_ASK.search(asked):
        return None
    phrase = permission_phrase(answer)
    if phrase is None:
        return None
    return ('The operator gave an instruction, and the reply asks leave or offers the work instead of doing it: '
            + repr(phrase[:100]) + '. Do the ordered work in this reply: give the command, or state the result. '
            'Ask a question only for a missing fact the work cannot go on without.')
