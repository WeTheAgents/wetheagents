from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_cloud_agent_setup_registers_codex_19_and_launch_token() -> None:
    script = (ROOT / "scripts" / "cloud_agent_setup.sh").read_text(encoding="utf-8")

    assert "CODEX19_GITHUB_TOKEN" in script
    assert '"codex-19|Codex-19@codex|cli|agent/Codex-19/work|Codex-19|codex-19@codex"' in script
    assert 'GITHUB_TOKEN=\\$CODEX19_GITHUB_TOKEN WEA_AGENT=Codex-19@codex' in script
