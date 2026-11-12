#!/usr/bin/env python3
"""Provider-requested zoom, with the crop named explicitly in the tool result."""
import json
import sys
from PIL import Image
region=json.loads(sys.argv[3])
with Image.open(sys.argv[1]) as picture:
    if len(region)!=4 or not (0<=region[0]<region[2]<=picture.width and 0<=region[1]<region[3]<=picture.height):
        raise SystemExit('Zoom region is outside the captured image.')
    picture.crop(region).save(sys.argv[2])
