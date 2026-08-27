# _archive — deprecated & duplicate files

This folder holds files that are **no longer part of the running application**
but are kept for reference/history. `server.py` (in the parent folder) is the
single canonical Flask entry point.

## What belongs here and why

| File | Why it's deprecated |
| :--- | :--- |
| `app.py` | Earliest Flask prototype. Imports scrapers as top-level modules (`import amazon`), which now live in the `amazon_scraper/` package — so it can no longer run. Superseded by `server.py`. |
| `main.py` | Near-duplicate of `server.py` but with fewer routes. `server.py` is a strict superset (it has every route `main.py` had, plus health, validate, gifts, detailed products, etc.). |
| `tempCodeRunnerFile.py` | Auto-generated scratch file from the VS Code "Run Selected Code" feature. Not real source. |
| `rag_compliance.py` | Experimental RAG (retrieval-augmented generation) module. Imported by **nothing** in the codebase. Kept in case RAG grounding is integrated later. |

The active compliance modules (`compliance.py`, `compliance_copy.py`,
`comply.py`, `chatbot_compliance.py`) are **NOT** archived — `server.py` imports
all of them.

## How these files got here

They were moved with the `cleanup_duplicates` script at the repository root,
which uses `git mv` so version history is preserved. To restore any file:

```bash
git mv _archive/main.py ../main.py     # from inside legal_metrology/
```

## Note

Because these files are duplicates of logic that already lives in `server.py`,
you can safely delete this whole folder once you're confident nothing here is
needed — git retains the full history either way.
