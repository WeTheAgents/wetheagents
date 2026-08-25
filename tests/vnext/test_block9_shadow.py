from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from wea_vnext.block9.common import Block9Error, canonical_bytes, sha256_hex
from wea_vnext.block9.shadow import (
    ShadowPolicy,
    ShadowWriteAdapter,
    WindowsShadowBoundary,
    run_shadow_twice,
)


def _policy(tmp_path: Path) -> ShadowPolicy:
    return ShadowPolicy(
        account="wea-vnext-shadow",
        is_administrator=False,
        network_adapters=("Ethernet:Down", "Wi-Fi:Down"),
        credential_sources=(),
        readable_roots=(str(tmp_path / "input"), str(tmp_path / "runtime")),
        writable_roots=(str(tmp_path / "output"),),
        denied_live_roots=(str(tmp_path / "live-repo"), str(tmp_path / "agent0")),
        allowed_children=("python.exe",),
        job_object_active=True,
    )


def _boundary(tmp_path: Path) -> WindowsShadowBoundary:
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    python_path = runtime / "python.exe"
    runner_path = runtime / "shadow_runner.py"
    python_path.write_bytes(b"pinned-python")
    runner_path.write_bytes(b"pinned-runner")
    return WindowsShadowBoundary(
        task_name="\\WeTheAgents\\vNextShadow",
        request_path=tmp_path / "input" / "shadow-request.json",
        result_path=tmp_path / "output" / "shadow-result.json",
        python_path=python_path,
        python_hash=sha256_hex(python_path.read_bytes()),
        runner_path=runner_path,
        runner_hash=sha256_hex(runner_path.read_bytes()),
    )


def test_shadow_policy_rejects_network_admin_credentials_or_live_write(
    tmp_path: Path,
) -> None:
    with pytest.raises(Block9Error, match="administrator"):
        _policy(tmp_path).__class__(
            **{**_policy(tmp_path).to_mapping(), "is_administrator": True}
        )
    with pytest.raises(Block9Error, match="network adapter"):
        _policy(tmp_path).__class__(
            **{**_policy(tmp_path).to_mapping(), "network_adapters": ("Wi-Fi:Up",)}
        )
    with pytest.raises(Block9Error, match="credential"):
        _policy(tmp_path).__class__(
            **{
                **_policy(tmp_path).to_mapping(),
                "credential_sources": ("GITHUB_TOKEN",),
            }
        )

    base = _policy(tmp_path).to_mapping()
    readable_roots = base["readable_roots"]
    assert type(readable_roots) is tuple
    base["writable_roots"] = (str(Path(readable_roots[0]) / "nested"),)
    with pytest.raises(Block9Error, match="overlap"):
        ShadowPolicy(**base)


def test_complete_shadow_runs_twice_with_identical_output_and_no_host_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_hashes = iter(("a" * 64, "a" * 64, "a" * 64, "a" * 64))

    def runner(
        _: WindowsShadowBoundary,
        input_bytes: bytes,
        runtime_bytes: bytes,
        policy: ShadowPolicy,
    ) -> tuple[bytes, bytes]:
        assert policy.account == "wea-vnext-shadow"
        state = canonical_bytes({"accepted": 2, "rejected": 1})
        report = canonical_bytes(
            {
                "input_hash": __import__("hashlib").sha256(input_bytes).hexdigest(),
                "state": state.hex(),
            }
        )
        return state, report

    monkeypatch.setattr(WindowsShadowBoundary, "run", runner)
    boundary = _boundary(tmp_path)

    proof = run_shadow_twice(
        input_bundle=b"frozen-input",
        runtime_bundle=b"candidate-runtime",
        policy=_policy(tmp_path),
        boundary=boundary,
        host_state_hash=lambda: next(host_hashes),
        rule_hash="b" * 64,
        boundary_hash="c" * 64,
    )
    assert proof["runs"] == 2
    assert proof["state_hash"]
    assert proof["report_hash"]


def test_unstable_shadow_output_or_host_change_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 0

    def unstable(*_: object) -> tuple[bytes, bytes]:
        nonlocal count
        count += 1
        return canonical_bytes({"run": count}), canonical_bytes({"run": count})

    monkeypatch.setattr(WindowsShadowBoundary, "run", unstable)
    boundary = _boundary(tmp_path)

    with pytest.raises(Block9Error, match="not repeatable"):
        run_shadow_twice(
            input_bundle=b"input",
            runtime_bundle=b"runtime",
            policy=_policy(tmp_path),
            boundary=boundary,
            host_state_hash=lambda: "d" * 64,
            rule_hash="b" * 64,
            boundary_hash="c" * 64,
        )


def test_host_change_between_repeatable_shadow_runs_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        WindowsShadowBoundary,
        "run",
        lambda *_: (canonical_bytes({}), canonical_bytes({})),
    )
    host_hashes = iter(("a" * 64, "a" * 64, "b" * 64, "b" * 64))

    with pytest.raises(Block9Error, match="between runs"):
        run_shadow_twice(
            input_bundle=b"input",
            runtime_bundle=b"runtime",
            policy=_policy(tmp_path),
            boundary=_boundary(tmp_path),
            host_state_hash=lambda: next(host_hashes),
            rule_hash="b" * 64,
            boundary_hash="c" * 64,
        )


def test_plain_in_process_callback_cannot_stand_in_for_os_isolation(
    tmp_path: Path,
) -> None:
    with pytest.raises(Block9Error, match="enforced Windows boundary"):
        run_shadow_twice(
            input_bundle=b"input",
            runtime_bundle=b"runtime",
            policy=_policy(tmp_path),
            boundary=lambda *_: (b"{}", b"{}"),  # type: ignore[arg-type]
            host_state_hash=lambda: "d" * 64,
            rule_hash="b" * 64,
            boundary_hash="c" * 64,
        )


def test_shadow_task_pins_exact_command_arguments_and_runner_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boundary = _boundary(tmp_path)
    task = ET.Element("Task")
    principal = ET.SubElement(ET.SubElement(task, "Principals"), "Principal")
    ET.SubElement(principal, "UserId").text = "MACHINE\\wea-vnext-shadow"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    action = ET.SubElement(ET.SubElement(task, "Actions"), "Exec")
    ET.SubElement(action, "Command").text = str(boundary.python_path.resolve())
    ET.SubElement(action, "Arguments").text = (
        f'"{boundary.runner_path.resolve()}" '
        f'--request "{boundary.request_path.resolve()}" '
        f'--result "{boundary.result_path.resolve()}"'
    )
    xml = ET.tostring(task, encoding="utf-8")
    monkeypatch.setattr(
        WindowsShadowBoundary,
        "_command",
        staticmethod(lambda *_: xml),
    )
    monkeypatch.setattr(
        WindowsShadowBoundary,
        "_resolve_account_sid",
        staticmethod(lambda _: "S-1-5-21-1000"),
    )
    boundary._validate_task(_policy(tmp_path))
    boundary.runner_path.write_bytes(b"tampered")
    with pytest.raises(Block9Error, match="runner hash changed"):
        boundary._validate_task(_policy(tmp_path))


def test_shadow_task_rejects_same_name_from_another_account_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boundary = _boundary(tmp_path)
    task = ET.Element("Task")
    principal = ET.SubElement(ET.SubElement(task, "Principals"), "Principal")
    ET.SubElement(principal, "UserId").text = "DOMAIN\\wea-vnext-shadow"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    action = ET.SubElement(ET.SubElement(task, "Actions"), "Exec")
    ET.SubElement(action, "Command").text = str(boundary.python_path.resolve())
    ET.SubElement(action, "Arguments").text = (
        f'"{boundary.runner_path.resolve()}" '
        f'--request "{boundary.request_path.resolve()}" '
        f'--result "{boundary.result_path.resolve()}"'
    )
    xml = ET.tostring(task, encoding="utf-8")
    monkeypatch.setattr(
        WindowsShadowBoundary,
        "_command",
        staticmethod(lambda *_: xml),
    )
    monkeypatch.setattr(
        WindowsShadowBoundary,
        "_resolve_account_sid",
        staticmethod(
            lambda account: (
                "S-1-5-21-2000"
                if account.lower().startswith("domain\\")
                else "S-1-5-21-1000"
            )
        ),
    )

    with pytest.raises(Block9Error, match="principal changed"):
        boundary._validate_task(_policy(tmp_path))


def test_shadow_task_rejects_any_additional_exec_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boundary = _boundary(tmp_path)
    task = ET.Element("Task")
    principal = ET.SubElement(ET.SubElement(task, "Principals"), "Principal")
    ET.SubElement(principal, "UserId").text = ".\\wea-vnext-shadow"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    actions = ET.SubElement(task, "Actions")
    malicious = ET.SubElement(actions, "Exec")
    ET.SubElement(malicious, "Command").text = "powershell.exe"
    expected = ET.SubElement(actions, "Exec")
    ET.SubElement(expected, "Command").text = str(boundary.python_path.resolve())
    ET.SubElement(expected, "Arguments").text = "ignored"
    xml = ET.tostring(task, encoding="utf-8")
    monkeypatch.setattr(
        WindowsShadowBoundary,
        "_command",
        staticmethod(lambda *_: xml),
    )
    with pytest.raises(Block9Error, match="exactly one Exec"):
        boundary._validate_task(_policy(tmp_path))


def test_shadow_result_must_belong_to_the_exact_fresh_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boundary = _boundary(tmp_path)
    policy = _policy(tmp_path)
    for root in (*policy.readable_roots, *policy.writable_roots):
        Path(root).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(WindowsShadowBoundary, "_validate_task", lambda *_: None)
    monkeypatch.setattr(
        WindowsShadowBoundary, "_validate_host_network", lambda *_: None
    )

    stale_result = {
        **{
            key: value
            for key, value in policy.to_mapping().items()
            if key != "denied_live_roots"
        },
        "credential_probe_denied": True,
        "denied_live_root_results": {
            path: "denied" for path in policy.denied_live_roots
        },
        "input_hash": sha256_hex(b"input"),
        "network_probe_denied": True,
        "report": {},
        "run_id": "shadow-from-an-earlier-run",
        "runtime_hash": sha256_hex(b"runtime"),
        "state": {},
    }

    def command(*_: str) -> bytes:
        boundary.result_path.write_bytes(canonical_bytes(stale_result))
        return b""

    monkeypatch.setattr(WindowsShadowBoundary, "_command", staticmethod(command))
    with pytest.raises(Block9Error, match="belongs to another run"):
        boundary.run(b"input", b"runtime", policy)


def test_shadow_network_probe_includes_virtual_non_loopback_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boundary = _boundary(tmp_path)
    observed_script = ""

    def command(*arguments: str) -> bytes:
        nonlocal observed_script
        observed_script = arguments[-1]
        return b"Ethernet:Down\nWi-Fi:Down\n"

    monkeypatch.setattr(WindowsShadowBoundary, "_command", staticmethod(command))
    boundary._validate_host_network(_policy(tmp_path))
    assert "Get-NetAdapter -IncludeHidden" in observed_script
    assert "-Physical" not in observed_script


@pytest.mark.parametrize(
    "method",
    ["write_ledger", "mutate_github", "read_credential", "run_git", "open_socket"],
)
def test_shadow_adapter_rejects_every_external_write_surface(method: str) -> None:
    adapter = ShadowWriteAdapter()
    with pytest.raises(Block9Error, match="shadow write denied"):
        getattr(adapter, method)()
