"""Local vault runtime — emulates BitGN MiniRuntime on a local directory.

Returns JSON strings in the exact same format as the BitGN gRPC API,
so the agent loop cannot tell the difference.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile


class LocalVaultRuntime:
    """File-based vault that mirrors BitGN's MiniRuntime interface.

    Creates a temp copy of the vault so write/delete don't modify the original.
    Each method returns a JSON string matching the BitGN protobuf→JSON format.
    """

    def __init__(self, vault_dir: str):
        if not os.path.isdir(vault_dir):
            raise FileNotFoundError(f"Vault directory not found: {vault_dir}")
        self.original_dir = vault_dir
        self.root = tempfile.mkdtemp(prefix="arena_vault_")
        # Copy vault contents into temp dir
        shutil.copytree(vault_dir, self.root, dirs_exist_ok=True)
        self.answer_data: dict | None = None

    # --- Tool implementations (BitGN-compatible JSON output) ---

    def outline(self, path: str) -> str:
        """Return folder structure with file headers (markdown headings)."""
        resolved = self._resolve(path)
        if not os.path.isdir(resolved):
            return json.dumps({"error": f"Path not found: {path}"})

        folders = []
        files = []

        for entry in sorted(os.listdir(resolved)):
            full = os.path.join(resolved, entry)
            if os.path.isdir(full):
                folders.append(entry)
            elif os.path.isfile(full):
                headers = self._extract_headers(full)
                file_info = {"path": entry}
                if headers:
                    file_info["headers"] = headers
                files.append(file_info)

        result = {"path": path, "folders": folders, "files": files}
        return json.dumps(result, indent=2)

    def read(self, path: str) -> str:
        """Read file content."""
        resolved = self._resolve(path)
        if not os.path.isfile(resolved):
            return json.dumps({"error": f"File not found: {path}"})

        try:
            with open(resolved, encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            content = "[binary file — cannot display]"

        return json.dumps({"path": path, "content": content}, indent=2)

    def list(self, path: str) -> str:
        """List folder contents (names only, no headers)."""
        resolved = self._resolve(path)
        if not os.path.isdir(resolved):
            return json.dumps({"error": f"Path not found: {path}"})

        folders = []
        files = []

        for entry in sorted(os.listdir(resolved)):
            full = os.path.join(resolved, entry)
            if os.path.isdir(full):
                folders.append(entry)
            elif os.path.isfile(full):
                files.append(entry)

        result = {}
        if folders:
            result["folders"] = folders
        if files:
            result["files"] = files
        return json.dumps(result, indent=2)

    def search(self, pattern: str, count: int = 5, path: str = "/") -> str:
        """Regex search through vault files. Returns snippets."""
        resolved = self._resolve(path)
        if not os.path.isdir(resolved):
            return json.dumps({"snippets": []})

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return json.dumps({"error": f"Invalid regex: {pattern}"})

        snippets = []
        for dirpath, _, filenames in os.walk(resolved):
            for fname in sorted(filenames):
                if len(snippets) >= count:
                    break
                fpath = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(fpath, self.root).replace("\\", "/")

                try:
                    with open(fpath, encoding="utf-8") as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                snippets.append({
                                    "file": rel_path,
                                    "match": line.strip()[:200],
                                    "line": line_num,
                                })
                                if len(snippets) >= count:
                                    break
                except (UnicodeDecodeError, PermissionError):
                    continue

        return json.dumps({"snippets": snippets}, indent=2)

    def write(self, path: str, content: str) -> str:
        """Write file to vault (temp copy)."""
        resolved = self._resolve(path)
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return "{}"

    def delete(self, path: str) -> str:
        """Delete file from vault (temp copy)."""
        resolved = self._resolve(path)
        if os.path.isfile(resolved):
            os.remove(resolved)
        return "{}"

    def answer(self, answer: str, refs: list[str]) -> str:
        """Store the agent's answer for later scoring."""
        self.answer_data = {"answer": answer, "refs": refs}
        return "{}"

    # --- Helpers ---

    def _resolve(self, path: str) -> str:
        """Resolve a vault path to an absolute filesystem path."""
        # Strip leading slash — vault paths are relative to root
        clean = path.lstrip("/")
        if not clean:
            return self.root
        resolved = os.path.normpath(os.path.join(self.root, clean))
        # Prevent directory traversal
        if not resolved.startswith(self.root):
            raise ValueError(f"Path traversal blocked: {path}")
        return resolved

    def _extract_headers(self, filepath: str) -> list[str]:
        """Extract markdown headings from a file (for outline)."""
        headers = []
        try:
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#"):
                        # Remove # prefix and strip
                        heading = line.lstrip("#").strip()
                        if heading:
                            headers.append(heading)
        except (UnicodeDecodeError, PermissionError):
            pass
        return headers

    def get_modified_files(self) -> dict[str, str]:
        """Return files that were written (new or changed vs original)."""
        modified = {}
        for dirpath, _, filenames in os.walk(self.root):
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(fpath, self.root).replace("\\", "/")

                # Check if file exists in original
                orig_path = os.path.join(self.original_dir, rel_path)
                if not os.path.isfile(orig_path):
                    # New file
                    with open(fpath, encoding="utf-8") as f:
                        modified[rel_path] = f.read()
                else:
                    # Check if content changed
                    with open(fpath, encoding="utf-8") as f:
                        new_content = f.read()
                    with open(orig_path, encoding="utf-8") as f:
                        old_content = f.read()
                    if new_content != old_content:
                        modified[rel_path] = new_content

        return modified

    def get_deleted_files(self) -> list[str]:
        """Return files that existed in original but were deleted."""
        deleted = []
        for dirpath, _, filenames in os.walk(self.original_dir):
            for fname in filenames:
                orig_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(orig_path, self.original_dir).replace("\\", "/")
                temp_path = os.path.join(self.root, rel_path)
                if not os.path.isfile(temp_path):
                    deleted.append(rel_path)
        return deleted

    def cleanup(self) -> None:
        """Remove the temporary vault directory."""
        if os.path.isdir(self.root):
            shutil.rmtree(self.root, ignore_errors=True)

    def __del__(self):
        self.cleanup()
