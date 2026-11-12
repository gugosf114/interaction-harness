"""Byte-sniffed, hash-checked inline attachments. Persist metadata, never bytes."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

PHONE_HOME = Path('/data/data/com.termux/files/home')
# Official first-party API limits, checked 2026-11-11; see README Senses.
REQUEST_LIMIT = {'openai':512_000_000, 'anthropic':128_000_000}
ANTHROPIC_IMAGE_BASE64_LIMIT = 10_000_000
OPENAI_PDF_LIMIT = 50_000_000


class AttachmentError(ValueError): pass


def phone_path(value):
    value=str(value)
    if value=='~':return PHONE_HOME
    if value.startswith('~/'):return PHONE_HOME/value[2:]
    path=Path(value)
    if not path.is_absolute():path=Path(os.environ.get('HARNESS_CALLER_CWD',os.getcwd()))/path
    return path.resolve()


def media_type(head):
    if head.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if head.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if head[:6] in (b'GIF87a',b'GIF89a'):return 'image/gif'
    if head.startswith(b'RIFF') and head[8:12]==b'WEBP':return 'image/webp'
    if head.startswith(b'%PDF-'):return 'application/pdf'
    raise AttachmentError('Unsupported attachment bytes; use PNG, JPEG, WebP, GIF, or PDF.')


def check_size(kind,size,engine):
    encoded=4*((size+2)//3)
    if kind=='file' and engine=='openai' and size>=OPENAI_PDF_LIMIT:
        raise AttachmentError('OpenAI PDFs must be under 50 MB.')
    if kind=='image' and engine=='anthropic' and encoded>ANTHROPIC_IMAGE_BASE64_LIMIT:
        raise AttachmentError('Claude images must fit its 10 MB base64 limit.')
    if encoded>=REQUEST_LIMIT[engine]:
        raise AttachmentError(f'Attachment exceeds the {engine} request-size limit.')


def describe(kind,value,engine):
    path=phone_path(value)
    try:
        size=path.stat().st_size
        if not path.is_file():raise AttachmentError('Attachment path must name a regular file.')
        check_size(kind,size,engine)
        with path.open('rb') as f:
            mime=media_type(f.read(16));f.seek(0)
            digest=hashlib.file_digest(f,'sha256').hexdigest()
    except OSError as exc:raise AttachmentError(f'Cannot read attachment: {path.name}.') from exc
    if (kind=='image') != mime.startswith('image/'):
        raise AttachmentError('--image needs image bytes; --file needs PDF bytes.')
    return {'path':str(path),'sha256':digest,'size_bytes':size,'media_type':mime,'kind':kind}


def collect(images,files,engine):
    return [describe(kind,path,engine) for kind,paths in [('image',images),('file',files)] for path in paths]


def chat_attachment(line):
    match=re.match(r'^/(image|file)\s+("(?:\\.|[^"\\])*"|\x27[^\x27]*\x27|\S+)(?:\s+(.*))?$',line,re.S)
    if not match:raise AttachmentError('Use /image PATH question or /file PATH question; quote paths with spaces.')
    kind,quoted,question=match.groups()
    if not question or not question.strip():raise AttachmentError('Add a question after the attachment path.')
    return kind,shlex.split(quoted)[0],question


def materialize(messages,engine):
    records=[a for message in messages for a in message.get('attachments',[])]
    if sum(4*((a['size_bytes']+2)//3) for a in records)>=REQUEST_LIMIT[engine]:
        raise AttachmentError(f'Combined attachments exceed the {engine} request-size limit.')
    if engine=='openai' and sum(a['size_bytes'] for a in records if a['kind']=='file')>OPENAI_PDF_LIMIT:
        raise AttachmentError('Combined OpenAI PDF input exceeds 50 MB.')
    result=[];pdf_size=0
    for original in messages:
        message={k:v for k,v in original.items() if k!='attachments'}
        attached=original.get('attachments') or []
        if attached:
            content=[{'type':'input_text' if engine=='openai' else 'text','text':message['content']}]
            for record in attached:
                current=describe(record['kind'],record['path'],engine)
                if current!=record:raise AttachmentError('A saved attachment changed; restore it or start a new session.')
                data=Path(record['path']).read_bytes()
                if hashlib.sha256(data).hexdigest()!=record['sha256']:raise AttachmentError('Attachment changed while reading.')
                encoded=base64.b64encode(data).decode('ascii');mime=record['media_type']
                if record['kind']=='file':pdf_size+=len(data)
                if engine=='openai':
                    if record['kind']=='image':content.append({'type':'input_image','image_url':f'data:{mime};base64,{encoded}','detail':'high'})
                    else:content.append({'type':'input_file','filename':Path(record['path']).name,'file_data':f'data:{mime};base64,{encoded}'})
                else:content.append({'type':'image' if record['kind']=='image' else 'document',
                    'source':{'type':'base64','media_type':mime,'data':encoded}})
            message['content']=content
        result.append(message)
    if engine=='openai' and pdf_size>OPENAI_PDF_LIMIT:raise AttachmentError('Combined OpenAI PDF input exceeds 50 MB.')
    return result


def check_request_size(params,engine):
    if len(json.dumps(params,ensure_ascii=False,separators=(',',':')).encode())>=REQUEST_LIMIT[engine]:
        raise AttachmentError(f'{engine} request exceeds {REQUEST_LIMIT[engine]//1_000_000} MB; remove attachments.')
