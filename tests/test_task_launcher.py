"""Windows native transport and guarded-launch integration; no model calls."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.name != "nt" or not shutil.which("powershell.exe"),
    reason="Windows PowerShell launcher integration",
)


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def test_launcher_domain_transport_resume_and_evidence_preservation(tmp_path):
    tree = tmp_path / "task tree"
    tree.mkdir()
    for command in (
        ["init", "-b", "codex/fixture"],
        ["remote", "add", "origin", "https://github.com/WeTheAgents/wetheagents.git"],
    ):
        subprocess.run(
            ["git", "-C", str(tree), *command], check=True, capture_output=True
        )
    genome = tmp_path / "genome" / "genomes" / "Codex-2@codex"
    genome.mkdir(parents=True)
    (genome / "AGENTS.local.md").write_text("Fixture identity only")
    domain = tmp_path / "domain tree"
    domain.mkdir()
    prompt = tmp_path / "prompt $(literal).txt"
    prompt.write_text("literal prompt $(must-not-execute)")
    executable = tmp_path / "fake codex.exe"
    source = (
        "using System; public class Client { public static int Main(string[] args) { "
        "Console.WriteLine(string.Join(\"|\",args)); "
        "Console.WriteLine(Console.In.ReadToEnd()); return 0; } }"
    )
    registry = tmp_path / "registry"
    evidence = tmp_path / "evidence"
    script = tmp_path / "fixture.ps1"
    script.write_text(
        "$ErrorActionPreference='Stop'\n"
        f"Add-Type -TypeDefinition {literal(source)} -OutputAssembly "
        f"{literal(executable)} -OutputType ConsoleApplication\n"
        "$env:WEA_AGENT='Codex-2@codex'\n"
        "foreach ($attempt in 1,2) {\n"
        f"& {literal(REPO / 'gunnery/agent0/dispatch_codex_worker.ps1')} "
        "-Identity 'Codex-2@codex' -TaskId 'fixture' "
        f"-RegistryRoot {literal(registry)} -Worktree {literal(tree)} "
        "-Branch 'codex/fixture' "
        f"-PythonExecutable {literal(sys.executable)} "
        f"-CodexExecutable {literal(executable)} "
        f"-GenomeRoot {literal(tmp_path / 'genome')} "
        f"-PromptFile {literal(prompt)} -TaskEvidenceDir {literal(evidence)} "
        f"-RunDir (Join-Path {literal(evidence)} $attempt) -Name 'fixture' "
        f"-Resource {literal(json.dumps(['weather', 'codex/domain', str(domain)]))}\n"
        f"$exitFile=Join-Path (Join-Path {literal(evidence)} $attempt) 'exit.json'\n"
        "$deadline=[DateTime]::UtcNow.AddSeconds(15)\n"
        "while (-not (Test-Path -LiteralPath $exitFile)) {\n"
        "if ([DateTime]::UtcNow -gt $deadline) { throw 'Worker did not exit' }; "
        "Start-Sleep -Milliseconds 50\n}\n"
        "if ((Get-Content -LiteralPath $exitFile -Raw | ConvertFrom-Json).exit_code "
        "-ne 0) { throw 'Worker failed' }\n}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        capture_output=True,
        text=True,
        timeout=45,
        env={**os.environ, "TEMP": str(tmp_path), "TMP": str(tmp_path)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads((registry / "tasks.json").read_text())
    task = data["tasks"]["fixture"]
    assert len(task["assignment"]["resources"]) == 2
    assert len(task["attempts"]) == 2
    assert all(a["state"] == "finished" for a in task["attempts"])
    for attempt in (1, 2):
        run = evidence / str(attempt)
        assert (
            json.loads((run / "exit.json").read_text(encoding="utf-8-sig"))["exit_code"]
            == 0
        )
        output = (run / "events.jsonl").read_text()
        assert "must-not-execute" in output
        assert f"--add-dir|{os.path.normcase(str(domain.resolve()))}" in output
        assert (run / "launch.json").exists()
