---
name: extract-text
description: Extract plain text from PDF, DOCX, HTML, TXT/MD/JSON/CSV files or URLs into output/, using pdftotext/pandoc directly (no LLM ingestion of document content).
argument-hint: <path-or-url> [path-or-url ...]
---

# extract-text

Extract plain text from one or more documents or URLs into `$LOCAL_DIR/output/`, using shell tools only — never read the source document content yourself via the Read tool. The whole point is zero-token extraction: pipe bytes through `pdftotext`/`pandoc`/`cp` straight to disk.

## Inputs

`$ARGUMENTS` is a space-separated list of local file paths and/or URLs (`http://`/`https://`). Process each one in turn using the pipeline below. Do not skip inputs silently — every input gets a result line in the final summary (success with output path, or skip with reason).

## Setup

`mkdir -p $LOCAL_DIR/output` once, before processing any input (idempotent, safe every run).

Timestamp for filenames: `TZ=Europe/London date +%Y%m%d_%H%M%S` — compute fresh per input (not once for the whole batch), so outputs from the same run don't collide if you re-run part of a batch.

## Per-input pipeline

For each item in `$ARGUMENTS`:

1. **URL or local path?** If it starts with `http://` or `https://`, download it first: `curl -sL -o <tmpfile> "<url>"` (use `mktemp` for `<tmpfile>`). If curl fails (non-200, timeout, DNS failure), report `"failed to fetch <url>: <error>"` and move to the next input — don't retry indefinitely. On success, treat `<tmpfile>` as the local file for the rest of this pipeline, and delete it (`rm`) once you're done with this input, whether it succeeded or failed.

   Derive a base name for the output file:
   - If the URL path ends in a filename with an extension (e.g. `.../report.pdf`), use that basename (without extension).
   - Otherwise, build a sanitized slug from the domain + path (e.g. `example.com/docs/page` → `example.com_docs_page`), stripping characters that aren't safe in filenames.

   For a local path, verify it exists first (`test -f`) — if not, report `"file not found: <path>"` and move to the next input. Base name = the file's name without its extension.

2. **Detect format.** Use the file extension first (`.pdf`, `.docx`, `.html`/`.htm`, `.txt`, `.md`, `.json`, `.csv`). If there's no extension or it's ambiguous, fall back to `file --mime-type <file>` and map the MIME type (`application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `text/html`, `text/plain`, etc.).

3. **Extract, by detected type:**
   - **PDF** → `pdftotext "<input>" "$LOCAL_DIR/output/<basename>_<timestamp>.txt"`
   - **DOCX** → `pandoc "<input>" -t plain -o "$LOCAL_DIR/output/<basename>_<timestamp>.txt"`
   - **HTML** → `pandoc -f html -t plain "<input>" -o "$LOCAL_DIR/output/<basename>_<timestamp>.txt"`
   - **TXT / MD / JSON / CSV** → `cp "<input>" "$LOCAL_DIR/output/<basename>_<timestamp>.txt"` (already plain text, no conversion needed)
   - **Anything else** → report `"unsupported format: <extension-or-mime>"` for this input and move to the next one. Do not guess, do not attempt a fallback conversion.

4. **Verify** the output file exists and is non-empty after extraction (`test -s`). If the extraction command succeeded but produced an empty file (e.g. a PDF that's all images with no embedded text layer), report `"extracted but empty — <input> may have no text layer (scanned/image-only PDF?)"` rather than silently claiming success.

## Never do this

- Never use the Read tool on the source document to "look at it first" — that defeats the entire point of this command (zero-token extraction). If you need to sanity-check output, read the small `.txt` result file instead, not the original.
- Never fall back to guessing a format for an unrecognized extension/MIME type — report it as unsupported and move on.
- Never let one failed input abort the rest of the batch.

## Output

After processing all inputs, report a summary table: one line per input, either `<input> → output/<result>.txt` (success) or `<input> → skipped: <reason>` (failure/unsupported). State the total count processed vs. skipped.
