# pictures — make or edit a picture, make a short video with sound

Runs on: the Termux side starts it; the work is done on the Debian side. Keys: OpenAI key in the harness state
folder; Gemini key in Secret Manager (gemini-api-key, project bakers-agent), read for the one run.

Make a picture
  make-image "A BLUE TEAPOT ON A WOODEN TABLE" /sdcard/Download/teapot.png
  -> "/sdcard/Download/teapot.png  2368251 bytes  1536x1024  openai gpt-image-2.6-sunburst"
  --size 1536x1024        width x height in pixels (default: 3840x2160; Gemini 4K)
  --engine openai|gemini  default: openai first, Gemini if OpenAI fails
  --quality low|medium|high|xhigh|max|auto     default max, complexity high (OpenAI)
  --model ID              another model on the chosen engine
  OUT may end in .png, .jpg, .jpeg or .webp; the picture is converted to match.
  Models (live model lists, 2026-11-12): OpenAI gpt-image-2.6-sunburst; Gemini gemini-3-pro-image.

Edit a picture
  make-image "MAKE THE TEAPOT RED" /sdcard/Download/red.png --from /sdcard/Download/teapot.png
  --from can be given more than once (several pictures go in together).

See what came out
  look /sdcard/Download/teapot.png        the picture is attached to the next loop turn
  Claude accepts at most 10 MB of base64 per image. A 4K PNG can exceed this.
  To view it at the same pixel size, keep the PNG and make a JPEG copy:
  deb python3 -c 'from PIL import Image; Image.open("/sdcard/Download/teapot.png").convert("RGB").save("/sdcard/Download/teapot-view.jpg",quality=99,subsampling=0)'
  look /sdcard/Download/teapot-view.jpg

Make a video (with sound)
  make-video "A BLUE TEAPOT POURING TEA, SLOW MOTION" /sdcard/Download/tea.mp4
  -> "/sdcard/Download/tea.mp4  25358128 bytes  15s 4k 16:9  gemini gemini-omni-1.2-flash"
  --seconds 3-15 (default 15)   --resolution 360p|720p|1080p|4k (default 4k)   --aspect 16:9|9:16
  --from IN.png (up to six pictures to start from)   --engine gemini|openai
  The default live proof decoded as 3840x2160 H.264, 15.04 seconds, with AAC sound.

Facts
  Each run is a paid provider call.
  Exit 0: made. Exit 1: every engine failed; each engine's own error is printed. Exit 2: wrong use.

Known failure
  make-video --engine openai answers: "POST https://api.openai.com/v1/videos answered HTTP 404, empty body.
  OpenAI shut down its Videos API on 2026-09-24." That is OpenAI's own shutdown; Gemini makes the video.
