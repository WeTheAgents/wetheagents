"""Restricted Windows shadow boundary and repeatability proof construction."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .common import Block9Error, canonical_bytes, require_hash, require_text, sha256_hex


@dataclass(frozen=True, slots=True)
class ShadowPolicy:
    account: str
    is_administrator: bool
    network_adapters: tuple[str, ...]
    credential_sources: tuple[str, ...]
    readable_roots: tuple[str, ...]
    writable_roots: tuple[str, ...]
    denied_live_roots: tuple[str, ...]
    allowed_children: tuple[str, ...]
    job_object_active: bool

    def __post_init__(self) -> None:
        require_text(self.account, field="shadow account")
        if self.account != "wea-vnext-shadow":
            raise Block9Error("shadow account identity is not accepted")
        if type(self.is_administrator) is not bool or self.is_administrator:
            raise Block9Error("shadow account must not be an administrator")
        for name, values in (
            ("network_adapters", self.network_adapters),
            ("credential_sources", self.credential_sources),
            ("readable_roots", self.readable_roots),
            ("writable_roots", self.writable_roots),
            ("denied_live_roots", self.denied_live_roots),
            ("allowed_children", self.allowed_children),
        ):
            if type(values) is not tuple:
                raise Block9Error(f"{name} must be an immutable tuple")
            for value in values:
                require_text(value, field=name)
        if any(not value.endswith(":Down") for value in self.network_adapters):
            raise Block9Error("every non-loopback network adapter must be Down")
        if self.credential_sources:
            raise Block9Error("shadow credential sources must be absent")
        if len(self.writable_roots) != 1:
            raise Block9Error("shadow needs exactly one writable output root")
        if not self.readable_roots or not self.denied_live_roots:
            raise Block9Error("shadow read and deny boundaries are incomplete")
        readable = {str(Path(value).resolve()) for value in self.readable_roots}
        writable = {str(Path(value).resolve()) for value in self.writable_roots}
        denied = {str(Path(value).resolve()) for value in self.denied_live_roots}

        def overlaps(left: set[str], right: set[str]) -> bool:
            return any(
                Path(first) == Path(second)
                or Path(first) in Path(second).parents
                or Path(second) in Path(first).parents
                for first in left
                for second in right
            )

        if (
            overlaps(readable, writable)
            or overlaps(writable, denied)
            or overlaps(readable, denied)
        ):
            raise Block9Error("shadow path permissions overlap")
        if type(self.job_object_active) is not bool or not self.job_object_active:
            raise Block9Error("shadow Job Object must be active")
        if self.allowed_children != ("python.exe",):
            raise Block9Error("shadow child-process allowlist is not exact")

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


class ShadowWriteAdapter:
    """Fail-closed adapter used inside the isolated shadow process."""

    @staticmethod
    def _deny() -> None:
        raise Block9Error("shadow write denied")

    def write_ledger(self) -> None:
        self._deny()

    def mutate_github(self) -> None:
        self._deny()

    def read_credential(self) -> None:
        self._deny()

    def run_git(self) -> None:
        self._deny()

    def open_socket(self) -> None:
        self._deny()


@dataclass(frozen=True, slots=True)
class WindowsShadowBoundary:
    """Launch a pre-provisioned least-privilege Scheduled Task boundary."""

    task_name: str
    request_path: Path
    result_path: Path
    python_path: Path
    python_hash: str
    runner_path: Path
    runner_hash: str
    timeout_seconds: int = 3600

    def __post_init__(self) -> None:
        require_text(self.task_name, field="shadow task name")
        if any(
            not isinstance(path, Path)
            for path in (
                self.request_path,
                self.result_path,
                self.python_path,
                self.runner_path,
            )
        ):
            raise Block9Error("shadow exchange paths must use Path")
        require_hash(self.python_hash, field="shadow Python hash")
        require_hash(self.runner_hash, field="shadow runner hash")
        if (
            type(self.timeout_seconds) is not int
            or self.timeout_seconds < 1
            or self.timeout_seconds > 86400
        ):
            raise Block9Error("shadow timeout is invalid")

    @staticmethod
    def _command(*arguments: str) -> bytes:
        try:
            result = subprocess.run(
                list(arguments),
                check=False,
                capture_output=True,
            )
        except OSError as exc:
            raise Block9Error("Windows shadow boundary is unavailable") from exc
        if result.returncode != 0:
            raise Block9Error("Windows shadow boundary command failed")
        return result.stdout

    @staticmethod
    def _resolve_account_sid(account: str) -> str:
        account = require_text(account, field="shadow account principal")
        if re.fullmatch(r"S-[0-9]+(?:-[0-9]+)+", account, flags=re.IGNORECASE):
            return account.upper()
        script = (
            "$ErrorActionPreference = 'Stop'; "
            "$account = New-Object System.Security.Principal.NTAccount("
            "$env:WEA_SHADOW_PRINCIPAL); "
            "$account.Translate([System.Security.Principal.SecurityIdentifier]).Value"
        )
        environment = {**os.environ, "WEA_SHADOW_PRINCIPAL": account}
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                check=False,
                capture_output=True,
                env=environment,
            )
        except OSError as exc:
            raise Block9Error("Windows shadow account lookup is unavailable") from exc
        if result.returncode != 0:
            raise Block9Error("Windows shadow account lookup failed")
        raw = result.stdout
        for encoding in ("utf-8", "utf-16"):
            try:
                sid = raw.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
            if re.fullmatch(r"S-[0-9]+(?:-[0-9]+)+", sid, flags=re.IGNORECASE):
                return sid.upper()
        raise Block9Error("shadow Scheduled Task principal SID is unreadable")

    def _validate_task(self, policy: ShadowPolicy) -> None:
        raw = self._command("schtasks.exe", "/Query", "/TN", self.task_name, "/XML")
        try:
            root = ET.fromstring(raw.decode("utf-16"))
        except (UnicodeDecodeError, ET.ParseError):
            try:
                root = ET.fromstring(raw.decode("utf-8"))
            except (UnicodeDecodeError, ET.ParseError) as exc:
                raise Block9Error("shadow Scheduled Task XML is invalid") from exc

        def children(element: ET.Element, name: str) -> list[ET.Element]:
            return [
                child for child in list(element) if child.tag.rsplit("}", 1)[-1] == name
            ]

        def descendants(name: str) -> list[ET.Element]:
            return [
                element
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == name
            ]

        user_ids = descendants("UserId")
        run_levels = descendants("RunLevel")
        actions = descendants("Actions")
        if len(user_ids) != 1 or len(run_levels) != 1 or len(actions) != 1:
            raise Block9Error("shadow Scheduled Task structure changed")
        action_nodes = list(actions[0])
        if len(action_nodes) != 1 or action_nodes[0].tag.rsplit("}", 1)[-1] != "Exec":
            raise Block9Error("shadow Scheduled Task must have exactly one Exec action")
        commands = children(action_nodes[0], "Command")
        arguments = children(action_nodes[0], "Arguments")
        if len(commands) != 1 or len(arguments) != 1:
            raise Block9Error("shadow Scheduled Task Exec action changed")

        user_id = (user_ids[0].text or "").strip().lower()
        expected_sid = self._resolve_account_sid(f".\\{policy.account}")
        observed_sid = self._resolve_account_sid(user_id)
        if observed_sid != expected_sid:
            raise Block9Error("shadow Scheduled Task principal changed")
        if (run_levels[0].text or "").strip() != "LeastPrivilege":
            raise Block9Error("shadow Scheduled Task is not least privilege")
        command = (commands[0].text or "").strip()
        if Path(command).resolve() != self.python_path.resolve():
            raise Block9Error("shadow Scheduled Task child command changed")
        expected_arguments = (
            f'"{self.runner_path.resolve()}" '
            f'--request "{self.request_path.resolve()}" '
            f'--result "{self.result_path.resolve()}"'
        )
        if (arguments[0].text or "").strip() != expected_arguments:
            raise Block9Error("shadow Scheduled Task arguments changed")
        for name, path, expected_hash in (
            ("Python", self.python_path, self.python_hash),
            ("runner", self.runner_path, self.runner_hash),
        ):
            try:
                actual_hash = sha256_hex(path.resolve().read_bytes())
            except OSError as exc:
                raise Block9Error(f"shadow {name} is unavailable") from exc
            if actual_hash != expected_hash:
                raise Block9Error(f"shadow {name} hash changed")

    def _validate_host_network(self, policy: ShadowPolicy) -> None:
        script = (
            "Get-NetAdapter -IncludeHidden | "
            "Where-Object { $_.InterfaceDescription -notmatch 'Loopback' -and "
            "$_.Name -notmatch 'Loopback' } | Sort-Object Name | "
            "ForEach-Object { $state = if ($_.Status -eq 'Up') "
            "{ 'Up' } else { 'Down' }; \"$($_.Name):$state\" }"
        )
        raw = self._command(
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script
        )
        try:
            observed = tuple(
                line.strip()
                for line in raw.decode("utf-8-sig").splitlines()
                if line.strip()
            )
        except UnicodeDecodeError as exc:
            raise Block9Error("shadow network evidence is unreadable") from exc
        if observed != policy.network_adapters:
            raise Block9Error("shadow host network state changed")

    def run(
        self,
        input_bytes: bytes,
        runtime_bytes: bytes,
        policy: ShadowPolicy,
    ) -> tuple[bytes, bytes]:
        if os.name != "nt":
            raise Block9Error("the accepted shadow boundary requires Windows")
        self._validate_task(policy)
        self._validate_host_network(policy)
        request_parent = self.request_path.resolve().parent
        result_parent = self.result_path.resolve().parent
        readable = {Path(value).resolve() for value in policy.readable_roots}
        writable = {Path(value).resolve() for value in policy.writable_roots}
        if request_parent not in readable or result_parent not in writable:
            raise Block9Error("shadow exchange paths do not match the ACL policy")
        run_id = f"shadow-{uuid.uuid4().hex}"
        input_path = request_parent / f"{run_id}-input.bin"
        runtime_path = request_parent / f"{run_id}-runtime.bin"
        input_path.write_bytes(input_bytes)
        runtime_path.write_bytes(runtime_bytes)
        request = {
            "input_path": str(input_path),
            "output_path": str(self.result_path.resolve()),
            "policy": policy.to_mapping(),
            "run_id": run_id,
            "runtime_path": str(runtime_path),
        }
        self.request_path.write_bytes(canonical_bytes(request))
        if self.result_path.exists():
            self.result_path.unlink()
        self._command("schtasks.exe", "/Run", "/TN", self.task_name)
        deadline = time.monotonic() + self.timeout_seconds
        while not self.result_path.exists():
            if time.monotonic() >= deadline:
                raise Block9Error("shadow Scheduled Task did not finish")
            time.sleep(0.25)
        raw = _require_canonical_result(
            self.result_path.read_bytes(), field="shadow boundary result"
        )
        result = json.loads(raw)
        required = {
            "account",
            "allowed_children",
            "credential_probe_denied",
            "credential_sources",
            "denied_live_root_results",
            "input_hash",
            "is_administrator",
            "job_object_active",
            "network_adapters",
            "network_probe_denied",
            "readable_roots",
            "report",
            "run_id",
            "runtime_hash",
            "state",
            "writable_roots",
        }
        if type(result) is not dict or set(result) != required:
            raise Block9Error("shadow boundary result is incomplete")
        if result["run_id"] != run_id:
            raise Block9Error("shadow boundary result belongs to another run")
        expected_policy = policy.to_mapping()
        for field in (
            "account",
            "allowed_children",
            "credential_sources",
            "is_administrator",
            "job_object_active",
            "network_adapters",
            "readable_roots",
            "writable_roots",
        ):
            expected = expected_policy[field]
            observed = result[field]
            if isinstance(expected, tuple):
                observed = tuple(observed) if type(observed) is list else observed
            if observed != expected:
                raise Block9Error(f"shadow boundary {field} changed")
        denied = result["denied_live_root_results"]
        if type(denied) is not dict or denied != {
            path: "denied" for path in policy.denied_live_roots
        }:
            raise Block9Error("shadow live-root denial proof is incomplete")
        if (
            result["credential_probe_denied"] is not True
            or result["network_probe_denied"] is not True
        ):
            raise Block9Error("shadow external-access denial proof is incomplete")
        if result["input_hash"] != sha256_hex(input_bytes):
            raise Block9Error("shadow input hash changed at the OS boundary")
        if result["runtime_hash"] != sha256_hex(runtime_bytes):
            raise Block9Error("shadow runtime hash changed at the OS boundary")
        return (
            canonical_bytes(result["state"]),
            canonical_bytes(result["report"]),
        )


def _require_canonical_result(value: object, *, field: str) -> bytes:
    if type(value) is not bytes:
        raise Block9Error(f"{field} must be exact bytes")
    try:
        parsed = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Block9Error(f"{field} is not JSON") from exc
    if canonical_bytes(parsed) != value:
        raise Block9Error(f"{field} is not canonical")
    return value


def run_shadow_twice(
    *,
    input_bundle: bytes,
    runtime_bundle: bytes,
    policy: ShadowPolicy,
    boundary: WindowsShadowBoundary,
    host_state_hash: Callable[[], str],
    rule_hash: str,
    boundary_hash: str,
) -> dict[str, object]:
    if type(input_bundle) is not bytes or not input_bundle:
        raise Block9Error("shadow input bundle must be non-empty exact bytes")
    if type(runtime_bundle) is not bytes or not runtime_bundle:
        raise Block9Error("shadow runtime bundle must be non-empty exact bytes")
    if type(policy) is not ShadowPolicy:
        raise Block9Error("shadow policy must use the exact type")
    if type(boundary) is not WindowsShadowBoundary:
        raise Block9Error("shadow run requires the enforced Windows boundary")
    require_hash(rule_hash, field="shadow rule_hash")
    require_hash(boundary_hash, field="shadow boundary_hash")
    results: list[tuple[bytes, bytes]] = []
    host_pairs: list[tuple[str, str]] = []
    for _ in range(2):
        before = require_hash(host_state_hash(), field="pre-shadow host hash")
        state, report = boundary.run(input_bundle, runtime_bundle, policy)
        state = _require_canonical_result(state, field="shadow state")
        report = _require_canonical_result(report, field="shadow report")
        after = require_hash(host_state_hash(), field="post-shadow host hash")
        if before != after:
            raise Block9Error("shadow changed host state")
        host_pairs.append((before, after))
        results.append((state, report))
    if len({value for pair in host_pairs for value in pair}) != 1:
        raise Block9Error("shadow host state changed between runs")
    if results[0] != results[1]:
        raise Block9Error("shadow output is not repeatable")
    state, report = results[0]
    proof = {
        "schema": "wea-vnext-shadow-proof-1",
        "runs": 2,
        "input_hash": sha256_hex(input_bundle),
        "runtime_hash": sha256_hex(runtime_bundle),
        "rule_hash": rule_hash,
        "boundary_hash": boundary_hash,
        "policy_hash": sha256_hex(canonical_bytes(policy.to_mapping())),
        "state_hash": sha256_hex(state),
        "report_hash": sha256_hex(report),
        "host_hash": host_pairs[0][0],
    }
    canonical_bytes(proof)
    return proof


__all__ = [
    "ShadowPolicy",
    "ShadowWriteAdapter",
    "WindowsShadowBoundary",
    "run_shadow_twice",
]
