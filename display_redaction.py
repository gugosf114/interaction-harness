"""Hide recognizable credentials in transcript displays; source records stay intact."""
import re

TOKEN = re.compile(r'\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,})\b')
BEARER = re.compile(r'(?i)(\b(?:Bearer|Basic)\s+)[A-Za-z0-9._~+/=-]{6,}')
ASSIGN = re.compile(r'''(?ix)
(\b(?:[A-Z][A-Z0-9_]*_)?(?:API[_-]?KEY|ACCESS[_-]?TOKEN|AUTH[_-]?TOKEN|SECRET|PASSWORD|TOKEN)
 ["']?\s*[:=]\s*)
 (?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)
''')
HEADER = re.compile(r'''(?ix)(\b(?:x-api-key|x-line-key|authorization)["']?\s*:\s*)
(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+(?:\s+[^\s,;}]+)?)''')


def redact(text):
    text=TOKEN.sub('[credential]',str(text))
    text=BEARER.sub(r'\1[credential]',text)
    text=ASSIGN.sub(r'\1[credential]',text)
    return HEADER.sub(r'\1[credential]',text)
