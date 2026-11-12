# skills — George's skill packs: written instructions for a kind of job, with their scripts

What a skill is
  A folder with a SKILL.md: how to do one kind of job well (a Word file, a spreadsheet, a slide deck, a PDF,
  deep research, a code review, legal and data work, design critique, scraping, and more), and sometimes
  scripts and reference files. The current count is printed by skill groups, from George's Claude Code,
  its plugins, Codex, grok, Antigravity, his own projects and some Python packages.

Before a job that matches a skill, print the skill and follow it.
  skill find WORDS            the 10 best matches: name and purpose      skill find spreadsheet
  skill show NAME --all       LANE NOTES first, then all instructions in one call      skill show xlsx --all
  skill show NAME 2           a long skill comes in parts of 7,000 characters; the first line says how many
  skill files NAME            its scripts and reference files, with the full path and how to run each
  skill list GROUP            every skill of one group, one line each      skill groups   the groups and folders
  skill list                  all skills; use GROUP or find to narrow the output
  A short name works when only one skill has it (xlsx, analyze, brief); otherwise use the full name (data:analyze).

The lane notes
  They turn the skill's words into this client's commands: Read, Write, Edit, WebSearch, subagents, MCP
  connectors, Artifacts, and the skill's own folder. They also say what the phone has and what it lacks.
  Follow them where they differ from the skill's text.

Running a skill's work
  The tools live on the Debian side. Write the script to a file, then run it with deb, full paths only:
    deb python3 /sdcard/Download/make_sheet.py
    deb node /sdcard/Download/make_deck.js
    deb python3 SKILL_FOLDER/scripts/recalc.py /sdcard/Download/out.xlsx
  Installed (2026-11-11): LibreOffice 25.2 (soffice), pandoc, Poppler (pdftoppm, pdftotext), qpdf, weasyprint,
  ffmpeg; Python openpyxl, pandas, python-docx, python-pptx, markitdown, pypdf, pdfplumber, reportlab,
  matplotlib, Pillow, pdf2image, pytesseract; npm docx, pptxgenjs, react, react-dom, react-icons, sharp.
  Node finds the npm packages from any folder. Put files for George in /sdcard/Download.
  To look at a page or picture you made: deb pdftoppm -png -r 60 FILE.pdf /sdcard/Download/page, then look PATH.

The main ones
  docx (Word)   xlsx (Excel)   pptx (PowerPoint)   pdf   deep-research   grok:code-review
  Others: data:analyze, data:create-viz, legal:review-contract, legal:triage-nda, design:design-critique,
  operations:runbook, brightdata-plugin:scrape, frontend-design:frontend-design, claude-api (API reference).

Not files on this phone
  Claude Code's built-in /code-review, /security-review, /simplify and the like live inside the Claude Code
  program. grok:code-review and codex-source:code-review are the code review skills on disk.

Known failure
  Skills of the Adobe, Figma, Slack and other connectors call tools the lanes do not have.
  The lane notes name each one; there is no command that stands in for them.
