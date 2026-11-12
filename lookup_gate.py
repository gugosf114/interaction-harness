"""Deterministic provenance checks, shared by live answers and recall."""
import re

URL=re.compile(r'https?://[^\s<>"\x27`]+',re.I)
QUOTED=re.compile(r'```[\s\S]*?```|`[^`]*`|"[^"\n]*"|“[^”\n]*”|(?<!\w)\x27[^\x27\n]*\x27(?!\w)')
CLAIM=re.compile(r'\b(?:I|we)(?:(?:[\x27’]ve| have))?(?:\s+(?:just|already|also|now|successfully))*\s+'
                 r'(?:searched|browsed|fetched|looked\s+up|checked\s+(?:online|the\s+web(?:\s+page)?|the\s+website))\b',re.I)
PASSIVE=re.compile(r'\b(?:web|online|internet)\s+(?:search|lookup)\s+(?:shows?|found|confirms?)\b|'
                   r'\b(?:after|having)\s+(?:searching|browsing|fetching|looking\s+up|checking\s+online)\b',re.I)
DENIAL=re.compile(r'\b(?:no|not|never|cannot|can[\x27’]t|didn[\x27’]t|haven[\x27’]t|without|unknown|whether|if|may|might)\b',re.I)


def urls(text):return {m.group(0).rstrip('.,;:!?)]}') for m in URL.finditer(text or '')}


def claims_lookup(answer):
    for sentence in re.split(r'(?<=[.!?])\s+|\n+',QUOTED.sub(' ',answer)):
        for match in list(CLAIM.finditer(sentence))+list(PASSIVE.finditer(sentence)):
            if not DENIAL.search(sentence[:match.start()]):return True
    return False


def violation(answer,counts,sources,allowed_text):
    if re.search(r'(?im)^\s*(?:\*\*)?Sources\s*:',answer):return 'Sources are printed by the client; remove the model-written Sources block.'
    if claims_lookup(answer) and counts.get('total',0)==0:return 'The client recorded no lookup this turn. Remove the unsupported lookup claim.'
    allowed={s['url'] for s in sources}|urls(allowed_text)
    if urls(answer)-allowed:return 'The answer contains a URL absent from recorded sources, the request, and the supplied history.'
    if len(urls(answer)&{s['url'] for s in sources})>8:return 'Use at most eight source URLs in the answer.'
    return None


def unique_sources(items):
    result={}
    for item in items:
        url=item.get('url','')
        if not isinstance(url,str) or not re.match(r'^https?://[^\s\x00-\x1f]+$',url):continue
        title=item.get('title') or url
        title=re.sub(r'[\x00-\x1f\x7f]+',' ',str(title)).strip()
        if url not in result or result[url]['title']==url:result[url]={'title':title,'url':url}
    return list(result.values())


def displayed_sources(items,answer=''):
    items=unique_sources(items);linked=urls(answer)
    return ([s for s in items if s['url'] in linked]+[s for s in items if s['url'] not in linked])[:8]


def source_block(items,answer=''):
    selected=displayed_sources(items,answer)
    if not selected:return ''
    return 'Sources:\n'+'\n'.join(f'{i}. {s["title"]} — {s["url"]}' for i,s in enumerate(selected,1))


def turn_metadata(events):
    for event in reversed(events):
        if 'lookup_counts' in event:return {k:event[k] for k in ('sources','lookup_counts')}
    return {'sources':[],'lookup_counts':{'total':0,'search':0,'fetch':0,'find':0,'provider_reports':[]}}
