Be pragmatic. Prefer small diffs, direct language, and low process overhead.

This repository is a minimal working knowledge repo with a strict pipeline:

- Inbox (`00_inbox/`) holds raw captures
- Capture (`01_capture/`) holds organized source material
- Distill (`02_distill/cards/` and `02_distill/threads/`) holds refined output

**Rules:**
- Do not write to `02_distill/` directly. All distill content must go through `01_capture/` first.
- Follow process docs in `99_process/` when they are referenced by a task.
- Memory files in `90_memory/` are the source of truth for initiative status.

See `99_process/document_capture.md` for capture workflow.
See `99_process/document_cleanup.md` for cleanup criteria.
