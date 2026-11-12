# publish — put a page on a public web address and get the link

Runs on: the Termux side starts it; the Debian side writes to the public GitHub repo
abrahamyants/harness-pages with gh (signed in as gugosf114). GitHub Pages serves it.

Publish
  publish /sdcard/Download/report.md                 a Markdown file becomes a page
  publish /FULL/PATH/page.html bread-prices          an HTML file goes up as it is; NAME is optional
  -> "https://abrahamyants.github.io/harness-pages/report/  live (HTTP 200, 978 bytes)"
  NAME (default: the file name) is letters, digits and dashes. Publishing the same NAME again replaces it.
  It waits until the link really serves the new page (about a minute), then prints the link.

List
  publish --list          -> "NAME  https://abrahamyants.github.io/harness-pages/NAME/" per page

Remove
  publish --remove NAME   -> "https://abrahamyants.github.io/harness-pages/NAME/  removed; the link answers 404"

Facts
  The page is public on the internet the moment it is live. Anyone with the link can read it.
  The repo keeps every published version in its git history, also after a remove.
  One HTML or Markdown file per page. Pictures must be on the web already, linked by full address.

Known failure
  "...sent; GitHub Pages had not served it after 5 minutes": GitHub's Pages build is slow; the link
  usually works a few minutes later. Exit 1.
