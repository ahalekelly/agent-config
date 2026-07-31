---
name: scribd-text-layer-recovery
description: Recover the full text of a paywalled or WAF-blocked document (standard, book, report) from a Scribd copy by scraping the viewer's hidden per-page text layer. Use when every direct PDF source is paywalled, 403s, or Cloudflare-blocks and a Scribd copy of the document exists.
---

# Scribd text-layer recovery

Scribd renders scanned documents as page images, but each page carries a hidden, searchable text layer. The viewer virtualizes pages — only pages near the viewport have their text layer populated — so a plain page dump captures almost nothing. A scripted scroll-through recovers the whole document.

## Procedure

1. **Find a Scribd copy**: search `site:scribd.com "<document title or designation>"`. User-uploaded copies of standards and out-of-print documents are common.
2. **Drive a real browser**: use a browser leaf attached to the shared headless daemon (`~/.agents/browser-leaf/shared-browser.sh start` first; see the background-browser-automation setup) or any Playwright session. Scribd works logged-out for most documents.
3. **Scroll-capture every page**: each page lives in `#outer_page_N` (N = 1…page count) containing a `.text_layer` element that populates only when near the viewport. Loop over N: `scrollIntoView` the page container, wait for its `.text_layer` to have non-trivial `textContent`, capture it, move on. ~100–200 ms per page is usually enough; re-poll rather than fixed-sleep on slow pages.
4. **Reassemble and save**: concatenate in page order with page-break markers to a `.txt` file. Expect OCR-era artifacts (ligature damage, column interleaving, stray watermark texture strings).
5. **Validate before trusting**: the text layer is OCR output of a scan. Cross-check the passages that matter against independently sourced quotes (regulator guidance, catalogues, other previews) before citing, and record which **edition** the copy is — user uploads are often superseded editions with different clause numbering.

## Worked example

AS/NZS 1596:2002 (152 pages) was recovered this way after the direct PDF sources all 403'd (antpedia, pdfcoffee behind Cloudflare, accuristech). The scroll-through captured all 152 `.text_layer` blocks; clause 4.9.2 was then validated verbatim against two independent research trails before the file was committed as a reference text.

## Caveats

- Copyrighted paid documents: keep recovered text as local working reference material; quote operative sentences, don't republish.
- Some documents are behind Scribd's subscription blur — the text layer is typically still present even when the image is blurred, but verify a sample page before scripting the full pass.
- If `.text_layer` stays empty everywhere, the upload is image-only with no OCR layer; fall back to vision-model page reading of screenshots.
