# Hook Patterns Reference

## Auto-Formatting Hooks

### Python (Black/Ruff)
- **Detect**: `pyproject.toml` with `[tool.black]` or `[tool.ruff]`
- **Hook**: PostToolUse on Edit/Write → `ruff format <file>` or `black <file>`
- **Config**:
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "command": "ruff format $FILE"
    }]
  }
}
```

### JavaScript/TypeScript (Prettier)
- **Detect**: `.prettierrc`, `prettier` in package.json
- **Hook**: PostToolUse on Edit/Write → `npx prettier --write <file>`

## Type Checking Hooks

### Python (mypy/pyright)
- **Detect**: `pyproject.toml` with `[tool.mypy]` or `[tool.pyright]`, or `pyrightconfig.json`
- **Hook**: PostToolUse on Edit/Write → `pyright <file>` or `mypy <file>`

## Protection Hooks

### Block Sensitive File Edits
- **Detect**: `.env`, `credentials.json`, `*.key` files exist
- **Hook**: PreToolUse on Edit/Write → check if file matches sensitive patterns → block

### Block Lock File Edits
- **Detect**: `package-lock.json`, `poetry.lock`, `uv.lock` exist
- **Hook**: PreToolUse on Edit/Write → block edits to lock files

## Test Runner Hooks

### pytest
- **Detect**: `pytest.ini`, `pyproject.toml` with `[tool.pytest]`, `conftest.py`
- **Hook**: PostToolUse on Edit → run relevant tests

## Notification Hooks

### Permission Prompt
- **Matcher**: `permission_prompt` event
- **Use**: Auto-approve safe patterns, block dangerous ones
