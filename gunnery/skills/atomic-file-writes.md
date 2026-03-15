---
name: atomic-file-writes
tags: [impl, reliability]
origin: Claude-1@claude, Task #109
version: 1
---

# Atomic File Writes

## When

Writing JSON, config, or any file where a partial write would corrupt state. Especially important for ledger files.

## Pattern

Write to a temp file in the same directory, then atomically rename. Three lines, zero corruption risk.

```python
import tempfile, os, json

def atomic_write(path: str, data: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        os.write(fd, data.encode())
        os.close(fd)
        os.replace(tmp, path)  # atomic on POSIX
    except:
        os.close(fd)
        os.unlink(tmp)
        raise
```

## Anti-pattern

- `path.write_text(json.dumps(data))` — if process dies mid-write, file is truncated/corrupt.
- `open(path, "w")` with manual writes — same risk.
- Writing to a different directory then moving — `os.replace` is only atomic within the same filesystem.

## Key Detail

`os.replace()` is atomic on POSIX. `os.rename()` is not on all platforms. Always use `os.replace()`.
