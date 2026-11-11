"""Explicit STT substitutions; quoted literals, code, URLs and paths stay intact."""
import re

MAP = {'NC': 'antsy', 'AIPG': 'AIGP', 'redmi': 'README', 'term units': 'Termux'}
PROTECTED = re.compile(r'```[\s\S]*?```|`[^`\n]*`|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|https?://\S+|(?:[~./][\w./-]*[/])[\w./-]+')
RULES = [
    (re.compile(r'(?<![\w/-])NC(?![\w/-])'), 'antsy'),
    (re.compile(r'(?<![\w/-])AIPG(?![\w/-])', re.I), 'AIGP'),
    (re.compile(r'(?<![\w/-])redmi(?![\w/-])', re.I), 'README'),
    (re.compile(r'\bterm\s+units\b', re.I), 'Termux'),
]


def normalize(text):
    def clean(part):
        for pattern, replacement in RULES:
            part = pattern.sub(replacement, part)
        return part
    out, start = [], 0
    for match in PROTECTED.finditer(text):
        out.extend((clean(text[start:match.start()]), match.group(0)))
        start = match.end()
    out.append(clean(text[start:]))
    return ''.join(out)
