# research — a long web research run that writes a report file with its sources

Runs on: the Termux side. It starts this harness itself, in its own state folder, with --loop -y,
web search and fetch on, 50 lookups per model turn and up to 1,000 model turns, at max effort.

Run it
  deep-research "WHEN WAS DALY CITY INCORPORATED?" --out /sdcard/Download/dalycity.pdf
  --out FILE        .pdf makes a PDF, .docx a Word file, anything else Markdown
                    (default /sdcard/Download/research-STAMP-UNIQUE.md)
  --engine openai|anthropic      default: the harness default
  --web-max 2-50    lookups per model turn (default 50)
  --max-turns N     (default 1000)      --effort LEVEL (default max)
  --retries N       a model turn that ends on a failed web lookup loses only that turn; the run goes on
                    in the same session, up to N times (default 6)

What the report holds
  The model's report (a title, the short answer first, then findings with the URL of each fact), then
  "## Sources": the cited recorded sources, numbered, with title and link. All recorded sources stay in history.db.
  Every link in the report is checked against the recorded sources. A link that is not one is cut out,
  and its address is printed after "links dropped".
  The run folder keeps history.db, usage.jsonl and run.log.

Facts
  Each model turn is a paid call. A failed run or report with no recorded source exits nonzero and writes no report.

Known failure
  "Claude web lookup failed: url_not_accessible" ends that model turn: one page refused the fetch.
  The run continues by itself (--retries). With --retries 0 it stops there.
