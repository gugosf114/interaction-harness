# web-hands — open, click, type, wait, run JavaScript and take pictures in George's signed-in phone Chrome

Runs on: the Termux side starts it; node on the Debian side drives Chrome Beta on the hidden screen "web"
(debug port 127.0.0.1:9335, card phone-browser). That Chrome is signed in as George. George does not see it.
page-open opens a new tab and remembers it; every other page command acts on that tab.

Open a page
  page-open 'https://httpbin.org/forms/post'          -> "TITLE: ..." and "URL: ..."
  page-open 'URL' 5000                                wait 5 more seconds after it loads (default 2000 ms)

Click
  page-click 'Submit order'          words on a button, link, label, tab, menu item; exact words first
  page-click '#login > button'       or a CSS selector
  -> "CLICKED button[submit] "Submit order" by tap", then TITLE and URL after the click
  A real tap in the middle of the element. When something else covers that spot, or a box it should
  tick stays as it was, the element's own click() is used ("by click()").

Type
  page-type 'E-mail address' 'gugosf@gmail.com'     a field by its label, placeholder, name, id or a CSS selector
  page-type 'q' 'sourdough' --enter                 then press Enter
  page-type 'Size' 'Large'                          a drop-down list: chooses that choice
  -> "TYPED into input[email]: "gugosf@gmail.com""   (date and time fields: "SET input[time]: "18:30"")
  Typing replaces what the field held.

Wait for words
  page-wait 'Thank you' 30000       -> "FOUND "Thank you" after 812 ms"; exit 1 when it never came

Run JavaScript
  page-eval 'document.title'        prints the value (text as it is, anything else as JSON)
  page-eval 'JSON.parse(document.body.innerText).form'

Picture of the page
  page-shot /sdcard/Download/page.png          the visible part
  page-shot /sdcard/Download/page.png --full   the whole page
  -> "/sdcard/Download/page.png  49616 bytes  1080x2253"

Close the tab
  page-close

Facts
  A click or a form sent from here acts on that site as George, at once.
  Proven 2026-11-11 on httpbin.org/forms/post: name, phone, e-mail, a radio button, a check box, a time,
  a text box, Submit; the site echoed every field back.

Known failure
  "No page is open. Run page-open URL first." or "The page opened by page-open is gone.": open it again.
  "Nothing on the page matches ...": use other words or a CSS selector (page-eval can list them).
  "phone Chrome is not up": see the known failure on card phone-browser.

Each HARNESS_STATE_DIR keeps its own selected tab. PAGE_TAB_FILE overrides its path.
Chrome error pages exit 1. Chrome Beta has battery/background network access on this phone.
