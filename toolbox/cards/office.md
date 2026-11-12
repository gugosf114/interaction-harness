# office — make Word, Excel, PowerPoint and PDF files; read the text out of them

Runs on: the Termux side starts it; the files are made on the Debian side with pinned Python libraries
(python-docx 1.2.0, openpyxl 3.1.5, python-pptx 1.0.2, pypdf 7.0.1, markdown-it-py 4.3.0) and WeasyPrint 70.0. All 23 Python packages are pinned in toolbox/makers-requirements.lock.
Input comes from stdin or from a named file. Each maker prints the path and the size.

Word file from Markdown or plain text
  printf '# Bread\n\n- crust\n- crumb\n- yeast\n' | make-docx /sdcard/Download/bread.docx
  -> "/sdcard/Download/bread.docx  36999 bytes"
  make-docx /sdcard/Download/notes.docx /FULL/PATH/notes.md
  Headings, bullet and numbered lists (nested), bold, italic, code, links, tables, code blocks.

Spreadsheet from CSV or JSON, several sheets
  make-xlsx /sdcard/Download/book.xlsx prices.csv stock.csv        one sheet per file, named after it
  printf 'item,usd\nloaf,6\n' | make-xlsx /sdcard/Download/b.xlsx --sheet Prices
  echo '{"Prices":[{"item":"loaf","usd":6}],"Notes":[["x"],["y"]]}' | make-xlsx /sdcard/Download/b.xlsx
  A JSON object makes one sheet per key. Rows are lists, or objects (their keys become the header row).
  Numbers stay numbers. The first row is bold and frozen.

Slides from an outline
  printf '# Bread talk\nBy George\n# Why bread\n- it is good\n  - warm\n> speaker note\n' | make-pptx /sdcard/Download/talk.pptx
  "# " starts a slide; "- " lines are points (two spaces of indent per level); "> " lines are speaker notes.
  A first slide with one plain line is a title slide. 16:9.

PDF from Markdown (headings, lists, tables, links, code)
  make-pdf /sdcard/Download/report.pdf /FULL/PATH/report.md
  cat report.md | make-pdf /sdcard/Download/report.pdf
  Letter page, one-inch margins. For plain text as it is: text-pdf (card documents).

Read the text of a file
  read-doc /sdcard/Download/bread.docx      .docx .xlsx .pptx .pdf, told apart by their bytes, not the name
  Word: "# " headings, "- " list items, tab-separated table rows. Excel: "== sheet: NAME", then tab-separated
  rows. PowerPoint: "== slide N", the words, "notes: ...". PDF: "== page N", then the page text.

Install the libraries (Debian side; safe to run again; pins only)
  deb bash ~/interaction-harness/toolbox/debian/makers-install.sh

Known failure
  "The Python module X is missing on the Debian side": run the install line above.
  Exit 2 means wrong use: OUT has the wrong ending, its folder does not exist, or no input was given.
