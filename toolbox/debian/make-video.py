#!/usr/bin/python3
"""Debian side of make-video. Makes a short video with sound from words, or from words and pictures.

make-video "PROMPT" OUT.mp4 [--seconds 3-15] [--resolution 360p|720p|1080p|4k] [--aspect 16:9|9:16]
                            [--from IN.png]... [--engine gemini|openai] [--model ID]
Request shapes were checked against official documentation and live calls on 2026-11-12. No key is printed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import base64

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import makers_common as common  # noqa: E402
from makers_common import MakerError  # noqa: E402

# Gemini Omni Flash is the one video model either key can call (live model lists, 2026-11-12).
# OpenAI's Videos API answers HTTP 404 with an empty body; its guide says Sora was shut down on 2026-09-24.
MODELS = {'gemini': 'gemini-omni-1.2-flash', 'openai': 'sora-2-pro'}
ORDER = ['gemini', 'openai']
RESOLUTIONS = ['360p', '720p', '1080p', '4k']
ASPECTS = ['16:9', '9:16']
GOOGLE = 'https://generativelanguage.googleapis.com/v1beta/'
USAGE = ('usage: make-video "PROMPT" OUT.mp4 [--seconds 3-15] [--resolution 360p|720p|1080p|4k] [--aspect 16:9|9:16] '
         '[--from IN.png]... [--engine gemini|openai] [--model ID]')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise MakerError(message + '\n' + USAGE)


def parse(argv):
    parser = Parser(prog='make-video', add_help=False)
    parser.add_argument('prompt')
    parser.add_argument('out')
    parser.add_argument('--seconds', type=int, default=15)
    parser.add_argument('--resolution', choices=RESOLUTIONS, default='4k')
    parser.add_argument('--aspect', choices=ASPECTS, default='16:9')
    parser.add_argument('--from', dest='sources', action='append', default=[])
    parser.add_argument('--engine', choices=ORDER)
    parser.add_argument('--model')
    args = parser.parse_intermixed_args(argv)
    if not args.prompt.strip():
        raise MakerError('PROMPT is empty.\n' + USAGE)
    if not 3 <= args.seconds <= 15:
        raise MakerError('--seconds is a whole number from 3 to 15.\n' + USAGE)
    if len(args.sources) > 6:
        raise MakerError('At most six --from pictures.\n' + USAGE)
    if args.model and not args.engine:
        raise MakerError('--model needs --engine.\n' + USAGE)
    return args


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
        pictures.append((kind, data))
    return pictures


def gemini_video(args, pictures, model, http=common.http, key=None, sleep=time.sleep):
    key = key or common.load_key('gemini')
    auth = {'x-goog-api-key': key, 'Api-Revision': '2026-05-20'}
    parts = [{'type': 'image', 'mime_type': kind, 'data': base64.b64encode(raw).decode()} for kind, raw in pictures]
    body = {'model': model, 'input': parts + [{'type': 'text', 'text': args.prompt}] if parts else args.prompt,
            # delivery uri: the video is handed over as a hosted file, which also works above 4 MB.
            'response_format': {'type': 'video', 'duration': f'{args.seconds}s', 'resolution': args.resolution,
                                'aspect_ratio': args.aspect, 'delivery': 'uri'}}
    status, raw = http(GOOGLE + 'interactions', headers=auth, body=body, timeout=1800)
    if status != 200:
        raise MakerError(common.provider_error(status, raw))
    link = inline = None
    try:
        answer = json.loads(raw)
        for step in answer.get('steps', []):
            for block in step.get('content') or [] if step.get('type') == 'model_output' else []:
                if block.get('type') == 'video':
                    link, inline = block.get('uri'), block.get('data')
    except (ValueError, AttributeError, TypeError) as exc:
        raise MakerError('the answer could not be read.') from exc
    if inline:
        return base64.b64decode(inline)
    found = re.search(r'/files/([A-Za-z0-9_-]+)', link or '')
    if not found:
        raise MakerError('the answer held no video (status: ' + str(answer.get('status')) + ').')
    for _ in range(360):  # the hosted file turns ACTIVE when it can be downloaded
        status, raw = http(GOOGLE + 'files/' + found.group(1), headers=auth, timeout=60)
        if status != 200:
            raise MakerError(common.provider_error(status, raw))
        state = json.loads(raw).get('state')
        if state == 'ACTIVE':
            break
        if state == 'FAILED':
            raise MakerError('the provider reports the video file as FAILED.')
        sleep(5)
    else:
        raise MakerError('the video file did not become ready in 30 minutes.')
    status, raw = http(GOOGLE + 'files/' + found.group(1) + ':download?alt=media', headers=auth, timeout=1800)
    if status != 200:
        raise MakerError(common.provider_error(status, raw))
    return raw


def openai_video(args, pictures, model, http=common.http, key=None, sleep=time.sleep):
    key = key or common.load_key('openai')
    status, raw = http('https://api.openai.com/v1/videos', headers={'Authorization': 'Bearer ' + key},
                       body={'model': model, 'prompt': args.prompt})
    # No call to this API has succeeded since the shutdown, so there is no download step to build against.
    raise MakerError('POST https://api.openai.com/v1/videos answered ' + common.provider_error(status, raw)
                     + '. OpenAI shut down its Videos API on 2026-09-24.')


ENGINES = {'gemini': gemini_video, 'openai': openai_video}


def main(argv, engines=None):
    try:
        args = parse(argv)
        out = common.out_path(args.out, ['.mp4'])
        pictures = load_sources(args.sources)
    except MakerError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    failures = []
    for engine in [args.engine] if args.engine else ORDER:
        model = args.model or MODELS[engine]
        try:
            data = (engines or ENGINES)[engine](args, pictures, model)
            if b'ftyp' not in data[:16]:
                raise MakerError('the provider sent bytes that are not an MP4 video.')
            common.write_whole(out, data)
        except MakerError as exc:
            failures.append(f'{engine} ({model}): {exc}')
            continue
        for line in failures:
            print(line, file=sys.stderr)
        print(f'{out}  {len(data)} bytes  {args.seconds}s {args.resolution} {args.aspect}  {engine} {model}')
        return 0
    for line in failures:
        print(line, file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
