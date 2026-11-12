#!/usr/bin/python3
"""Debian side of make-image. Makes a picture from words, or edits pictures when --from is given.

make-image "PROMPT" OUT.png [--size WIDTHxHEIGHT] [--from IN.png]... [--engine openai|gemini]
                            [--quality low|medium|high|xhigh|max|auto] [--model ID]
Request shapes were checked against official documentation and live calls on 2026-11-12. No key is printed.
"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import makers_common as common  # noqa: E402
from makers_common import MakerError  # noqa: E402

# The strongest picture model each key can call, found with a live model list on 2026-11-12.
MODELS = {'openai': 'gpt-image-2.6-sunburst', 'gemini': 'gemini-3-pro-image'}
ORDER = ['openai', 'gemini']
QUALITIES = ['low', 'medium', 'high', 'xhigh', 'max', 'auto']
ENDINGS = {'.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg', '.webp': 'webp'}
SIZE = re.compile(r'([1-9][0-9]{1,4})x([1-9][0-9]{1,4})')
GEMINI_RATIOS = ['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9']
USAGE = ('usage: make-image "PROMPT" OUT.png [--size WIDTHxHEIGHT] [--from IN.png]... [--engine openai|gemini] '
         '[--quality low|medium|high|xhigh|max|auto] [--model ID]')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise MakerError(message + '\n' + USAGE)


def parse(argv):
    parser = Parser(prog='make-image', add_help=False)
    parser.add_argument('prompt')
    parser.add_argument('out')
    parser.add_argument('--size', default='3840x2160')
    parser.add_argument('--from', dest='sources', action='append', default=[])
    parser.add_argument('--engine', choices=ORDER)
    parser.add_argument('--quality', choices=QUALITIES, default='max')
    parser.add_argument('--model')
    args = parser.parse_intermixed_args(argv)
    if not args.prompt.strip():
        raise MakerError('PROMPT is empty.\n' + USAGE)
    if args.size != 'auto' and not SIZE.fullmatch(args.size):
        raise MakerError('--size is WIDTHxHEIGHT, for example 1536x1024, or auto.\n' + USAGE)
    if args.model and not args.engine:
        raise MakerError('--model needs --engine.\n' + USAGE)
    return args


def gemini_shape(size):
    """Gemini takes a shape and a size class, not pixels: the nearest of its ten shapes, and 1K, 2K or 4K."""
    width, height = (int(n) for n in SIZE.fullmatch(size).groups())
    def distance(ratio):
        a, b = (int(n) for n in ratio.split(':'))
        return abs(width / height - a / b)
    longest = max(width, height)
    return min(GEMINI_RATIOS, key=distance), '1K' if longest <= 1536 else '2K' if longest <= 3072 else '4K'


def load_sources(paths):
    pictures = []
    for name in paths:
        try:
            data = Path(os.path.expanduser(name)).read_bytes()
        except OSError as exc:
            raise MakerError(f'Cannot read {name}: {exc.__class__.__name__}.') from exc
        kind = common.image_kind(data)
        if kind not in ('image/png', 'image/jpeg', 'image/webp'):
            raise MakerError(f'{name} is not a PNG, JPEG or WebP picture.')
        pictures.append((os.path.basename(name), kind, data))
    return pictures


def openai_image(prompt, pictures, size, quality, form, model, http=common.http, key=None):
    key = key or common.load_key('openai')
    auth = {'Authorization': 'Bearer ' + key}
    fields = {'model': model, 'prompt': prompt, 'quality': quality, 'output_format': form,
              'complexity': 'high'}
    if size != 'auto':
        fields['size'] = size
    if pictures:
        data, kind = common.multipart(list(fields.items()), [('image[]', name, mime, raw) for name, mime, raw in pictures])
        status, raw = http('https://api.openai.com/v1/images/edits', headers={**auth, 'Content-Type': kind}, data=data)
    else:
        status, raw = http('https://api.openai.com/v1/images/generations', headers=auth, body=fields)
    if status != 200:
        raise MakerError(common.provider_error(status, raw))
    try:
        return base64.b64decode(json.loads(raw)['data'][0]['b64_json'])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise MakerError('the answer held no picture.') from exc


def gemini_image(prompt, pictures, size, quality, form, model, http=common.http, key=None):
    key = key or common.load_key('gemini')
    parts = [{'type': 'text', 'text': prompt}]
    parts += [{'type': 'image', 'mime_type': mime, 'data': base64.b64encode(raw).decode()} for _, mime, raw in pictures]
    body = {'model': model, 'input': parts, 'response_format': {'type': 'image', 'image_size': '4K'}}
    # Gemini answers in JPEG only: "The value 'image/png' is not supported for 'response_format.mime_type'."
    if size != 'auto':
        ratio, tier = gemini_shape(size)
        body['response_format'] = {'type': 'image', 'aspect_ratio': ratio, 'image_size': tier}
    status, raw = http('https://generativelanguage.googleapis.com/v1beta/interactions',
                       headers={'x-goog-api-key': key, 'Api-Revision': '2026-05-20'}, body=body)
    if status != 200:
        raise MakerError(common.provider_error(status, raw))
    try:
        for step in json.loads(raw).get('steps', []):
            for block in step.get('content') or [] if step.get('type') == 'model_output' else []:
                if block.get('type') == 'image' and block.get('data'):
                    return base64.b64decode(block['data'])
    except (ValueError, AttributeError, TypeError) as exc:
        raise MakerError('the answer could not be read.') from exc
    raise MakerError('the answer held no picture.')


ENGINES = {'openai': openai_image, 'gemini': gemini_image}


def fit_format(data, form):
    """Make the bytes match the file ending. Returns (bytes, width, height)."""
    have = common.image_kind(data)
    if have is None:
        raise MakerError('the provider sent bytes that are not a picture.')
    try:
        common.need('PIL')
        from PIL import Image
    except ImportError:
        if have == 'image/' + form:
            return data, None, None
        raise MakerError(f'the provider sent {have}; converting it to {form} needs the Python module PIL on the Debian side.')
    with Image.open(io.BytesIO(data)) as picture:
        width, height = picture.size
        if have == 'image/' + form:
            return data, width, height
        buffer = io.BytesIO()
        (picture.convert('RGB') if form == 'jpeg' else picture).save(buffer, format=form.upper())
        return buffer.getvalue(), width, height


def main(argv, engines=None):
    try:
        args = parse(argv)
        out = common.out_path(args.out, list(ENDINGS))
        form = ENDINGS[out.suffix.lower()]
        pictures = load_sources(args.sources)
    except MakerError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    failures = []
    for engine in [args.engine] if args.engine else ORDER:
        model = args.model or MODELS[engine]
        try:
            data = (engines or ENGINES)[engine](args.prompt, pictures, args.size, args.quality, form, model)
            data, width, height = fit_format(data, form)
            common.write_whole(out, data)
        except MakerError as exc:
            failures.append(f'{engine} ({model}): {exc}')
            continue
        for line in failures:
            print(line, file=sys.stderr)
        shape = f'  {width}x{height}' if width else ''
        print(f'{out}  {len(data)} bytes{shape}  {engine} {model}')
        return 0
    for line in failures:
        print(line, file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
