#!/usr/bin/env python3
"""Read the full PNG with Debian's installed Pillow, including its pixel data."""
import json
import sys
from PIL import Image
try:
    with Image.open(sys.argv[1]) as image:
        if image.format != 'PNG': raise ValueError()
        image.load()
        rgba = image.convert('RGBA')
        background = Image.new('RGBA', rgba.size, (0, 0, 0, 255))
        rgb = Image.alpha_composite(background, rgba).convert('RGB')
        print(json.dumps({'width': image.width, 'height': image.height,
                          'black': not any(high for low, high in rgb.getextrema())}))
except Exception:
    print('Unreadable PNG.', file=sys.stderr)
    raise SystemExit(1)
