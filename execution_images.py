"""Images travel on an inherited private descriptor, never by parsing stdout."""
import json
import os
from pathlib import Path
import tempfile

from attachments import AttachmentError, describe, media_type, phone_path, REQUEST_LIMIT

RECEIPT_LIMIT = 16384
MAX_RECEIPTS = 16


def announce(path):
    """Only an explicit local screen/look command writes this channel."""
    fd = os.environ.get('HARNESS_ATTACHMENT_FD')
    if fd is not None:
        packet = json.dumps({'path': str(phone_path(path))}, ensure_ascii=True).encode() + b'\n'
        if len(packet) > 4096:
            raise ValueError('Attachment path is too long.')
        os.write(int(fd), packet)


def read_receipts(stream):
    stream.seek(0)
    raw = stream.read(RECEIPT_LIMIT + 1)
    if not raw:
        return {}
    if len(raw) > RECEIPT_LIMIT:
        return {'attachment_errors': ['Too many attachment receipts.']}
    try:
        records = [json.loads(line) for line in raw.splitlines()]
        if len(records) > MAX_RECEIPTS or any(
            not isinstance(r, dict) or set(r) != {'path'} or not isinstance(r['path'], str)
            for r in records
        ):
            raise ValueError()
    except (ValueError, UnicodeError):
        return {'attachment_errors': ['Invalid attachment receipt.']}
    return {'attachment_receipts': records}


def prepare_execution(result, engine, state, history=()):
    """Validate, freeze the bytes, and turn any attachment failure into feedback."""
    result = dict(result)
    receipts = result.pop('attachment_receipts', [])
    if not result.get('approved'):
        result.pop('attachments', None)
        return result
    accepted = []
    errors = list(result.get('attachment_errors', []))
    used = sum(4 * ((a['size_bytes'] + 2) // 3) for m in history for a in m.get('attachments', []))
    pdf_bytes = sum(a['size_bytes'] for m in history for a in m.get('attachments', []) if a['kind'] == 'file')
    for receipt in receipts:
        try:
            path = phone_path(receipt['path'])
            if not path.is_file():
                raise AttachmentError('Attachment path must name a readable regular file.')
            with path.open('rb') as f:
                mime = media_type(f.read(16))
            kind = 'file' if mime == 'application/pdf' else 'image'
            record = describe(kind, path, engine)
            encoded = 4 * ((record['size_bytes'] + 2) // 3)
            if used + encoded >= REQUEST_LIMIT[engine] - 1_000_000:
                raise AttachmentError('Combined attachments exceed the request-size limit.')
            if engine == 'openai' and kind == 'file' and pdf_bytes + record['size_bytes'] > 50_000_000:
                raise AttachmentError('Combined OpenAI PDF input exceeds 50 MB.')
            # A later screenshot can overwrite --out. History keeps these exact bytes.
            folder = Path(state) / 'execution-attachments'
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            suffix = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp',
                      'image/gif': '.gif', 'application/pdf': '.pdf'}[mime]
            dest = folder / (record['sha256'] + suffix)
            with tempfile.NamedTemporaryFile(dir=folder, delete=False) as tmp:
                temp = Path(tmp.name)
                try:
                    with path.open('rb') as source:
                        left = record['size_bytes'] + 1
                        while left:
                            chunk = source.read(min(left, 1_048_576))
                            if not chunk:
                                break
                            tmp.write(chunk); left -= len(chunk)
                    tmp.flush()
                    copied = describe(kind, temp, engine)
                    if any(copied[k] != record[k] for k in ('sha256', 'size_bytes', 'media_type')):
                        raise AttachmentError('Attachment changed while copying.')
                    os.replace(temp, dest)
                finally:
                    temp.unlink(missing_ok=True)
            accepted.append(describe(kind, dest, engine))
            used += encoded
            if kind == 'file': pdf_bytes += record['size_bytes']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc) if isinstance(exc, AttachmentError) else 'Cannot read attachment file.')
    if accepted: result['attachments'] = accepted
    if errors: result['attachment_errors'] = errors
    return result


def look_main(argv):
    import sys
    if len(argv) != 1:
        print('usage: look PATH', file=sys.stderr); return 2
    try:
        path = phone_path(argv[0])
        # The engine applies its own size/type checks after execution. Failed
        # reads still produce a receipt so the next model turn can repair them.
        announce(path)
        print(path)
        return 0
    except (OSError, ValueError):
        print('look: attachment receipt failed.', file=sys.stderr); return 1
