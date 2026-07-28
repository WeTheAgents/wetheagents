from __future__ import annotations

import base64
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _installed_python(
    target: Path, code: str, **extra_env: str
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(target)
    environment.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=target.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _install_future_executor(target: Path) -> None:
    package = target / "wea_vnext"
    rules_path = package / "rulesets" / "0.7.json"
    executor_path = package / "executors" / "v0_7_0"
    executor_path.mkdir()
    rules_raw = _canonical({"tide_interface_version": "0.7", "version": "0.7"})
    init_raw = b'FUTURE_BEHAVIOR = "intentionally-distinct"\n'
    parent_init_raw = (package / "executors" / "__init__.py").read_bytes()
    rules_path.write_bytes(rules_raw)
    (executor_path / "__init__.py").write_bytes(init_raw)
    manifest = {
        "executor_version": "0.7.0",
        "files": {
            "executors/__init__.py": _sha256(parent_init_raw),
            "executors/v0_7_0/__init__.py": _sha256(init_raw),
            "rulesets/0.7.json": _sha256(rules_raw),
        },
        "module": "wea_vnext.executors.v0_7_0",
        "python_abi": "py3-none-any",
        "ruleset_path": "rulesets/0.7.json",
        "ruleset_sha256": _sha256(rules_raw),
        "semantic_dependencies": {},
        "tide_interface_version": "0.7",
    }
    (executor_path / "manifest.json").write_bytes(_canonical(manifest))


def test_wheel_resources_upgrade_isolation_and_preimport_verification(
    tmp_path: Path,
) -> None:
    build_root = tmp_path / "build-root"
    (build_root / "src").mkdir(parents=True)
    shutil.copy2(ROOT / "pyproject.toml", build_root / "pyproject.toml")
    shutil.copy2(ROOT / "README.md", build_root / "README.md")
    shutil.copytree(ROOT / "src" / "wea_cli", build_root / "src" / "wea_cli")
    shutil.copytree(ROOT / "src" / "wea_vnext", build_root / "src" / "wea_vnext")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheelhouse),
            str(build_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheel = next(wheelhouse.glob("*.whl"))
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)
        names = set(archive.namelist())
    assert "wea_vnext/rulesets/0.6.json" in names
    assert "wea_vnext/executors/v0_6_0/manifest.json" in names
    assert "wea_vnext/executors/v0_6_1/manifest.json" in names
    assert "wea_vnext/executors/v0_6_1/identity_hello_world.py" in names
    assert "wea_vnext/executors/v0_6_1/identity_migration.py" in names
    assert "wea_vnext/executors/v0_6_2/manifest.json" in names
    assert "wea_vnext/executors/v0_6_2/identity_hello_world.py" in names
    assert "wea_vnext/executors/v0_6_2/identity_migration.py" in names
    assert "wea_vnext/executors/v0_6_3/manifest.json" in names
    assert "wea_vnext/executors/v0_6_3/intake.py" in names
    assert "wea_vnext/hello_world.py" in names
    assert "wea_vnext/intake.py" in names
    assert "wea_vnext/migration.py" in names

    block_2_import_code = """
import hashlib
import importlib
from wea_vnext.engine import installed_executor
ordinary_hello_world = importlib.import_module(
    'wea_vnext.executors.v0_6_2.identity_hello_world'
)
assert ordinary_hello_world._WEA_VERIFIER_CAPABILITY is None
from wea_vnext.hello_world import SystemHelloWorldContract
import wea_vnext.hello_world as hello_world_facade
import wea_vnext.identity as identity_facade
from wea_vnext.identity import IdentityRegistry
from wea_vnext.migration import V1IdentityEvidence
assert not hasattr(identity_facade._MODULE, '_WEA_VERIFIER_CAPABILITY')
assert not hasattr(hello_world_facade._MODULE, '_WEA_VERIFIER_CAPABILITY')
runtime = installed_executor('0.6.3').reference
body = 'attacker-selected-body'
body_hash = hashlib.sha256(body.encode()).hexdigest()
method_globals = SystemHelloWorldContract.__post_init__.__globals__
method_globals['_CANONICAL_HELLO_WORLD'] = ('attacker-selected-issue', body_hash)
try:
    SystemHelloWorldContract(
        contract_id='attacker-selected-contract',
        issue_id='attacker-selected-issue',
        issue_number=1,
        body=body,
        body_hash=body_hash,
        ruleset_hash=runtime.ruleset_hash,
        tide_interface_version=runtime.tide_interface_version,
        executor_manifest_hash=runtime.executor_manifest_hash,
    )
except hello_world_facade.HelloWorldError:
    pass
else:
    raise AssertionError('exported class globals activated Hello World')
raw_contract = object.__new__(SystemHelloWorldContract)
try:
    hello_world_facade.accept_unique_hello_world(
        state=None,
        contract=raw_contract,
        submission=None,
        participant=None,
        decision=None,
        registry=None,
    )
except hello_world_facade.HelloWorldError:
    pass
else:
    raise AssertionError('raw allocated contract reached a mint transition')
try:
    ordinary_hello_world.SystemHelloWorldContract(
        contract_id='forged',
        issue_id='forged',
        issue_number=1,
        body='x',
        body_hash=hashlib.sha256(b'x').hexdigest(),
        ruleset_hash='0' * 64,
        tide_interface_version='forged',
        executor_manifest_hash='1' * 64,
    )
except ordinary_hello_world.HelloWorldError:
    pass
else:
    raise AssertionError('ordinary executor import accepted a forged runtime')
print(
    SystemHelloWorldContract.__name__,
    IdentityRegistry.__name__,
    V1IdentityEvidence.__name__,
)
"""
    block_2_import = _installed_python(installed, block_2_import_code)
    assert block_2_import.returncode == 0, (
        block_2_import.stdout + block_2_import.stderr
    )
    assert block_2_import.stdout.strip() == (
        "SystemHelloWorldContract IdentityRegistry V1IdentityEvidence"
    )

    replay_code = """
import base64
from wea_vnext.engine import default_registry, installed_executor
from wea_vnext.store import replay
descriptor = installed_executor('0.6.0')
report = replay([], descriptor.reference, registry=default_registry())
print(base64.b64encode(report.state_bytes + b'\\0' + report.report_bytes).decode())
"""
    before = _installed_python(installed, replay_code)
    assert before.returncode == 0, before.stdout + before.stderr

    _install_future_executor(installed)
    after = _installed_python(installed, replay_code)
    assert after.returncode == 0, after.stdout + after.stderr
    assert base64.b64decode(after.stdout.strip()) == base64.b64decode(
        before.stdout.strip()
    )

    future_init = installed / "wea_vnext" / "executors" / "v0_7_0" / "__init__.py"
    future_init.write_bytes(future_init.read_bytes() + b"# changed after install\n")
    with_unrelated_damage = _installed_python(installed, replay_code)
    assert with_unrelated_damage.returncode == 0, (
        with_unrelated_damage.stdout + with_unrelated_damage.stderr
    )
    assert base64.b64decode(with_unrelated_damage.stdout.strip()) == base64.b64decode(
        before.stdout.strip()
    )

    future_manifest = installed / "wea_vnext" / "executors" / "v0_7_0" / "manifest.json"
    malformed_manifests = (
        b'{"invalid-surrogate":"\\ud800"}',
        b'{"oversized-integer":' + (b"9" * 5000) + b"}",
    )
    for malformed_manifest in malformed_manifests:
        future_manifest.write_bytes(malformed_manifest)
        with_malformed_future = _installed_python(installed, replay_code)
        assert with_malformed_future.returncode == 0, (
            with_malformed_future.stdout + with_malformed_future.stderr
        )
        assert base64.b64decode(
            with_malformed_future.stdout.strip()
        ) == base64.b64decode(before.stdout.strip())

    current_manifest = (
        installed / "wea_vnext" / "executors" / "v0_6_0" / "manifest.json"
    )
    future_manifest.write_bytes(current_manifest.read_bytes())
    with_copied_future_manifest = _installed_python(installed, replay_code)
    assert with_copied_future_manifest.returncode == 0, (
        with_copied_future_manifest.stdout + with_copied_future_manifest.stderr
    )
    assert base64.b64decode(
        with_copied_future_manifest.stdout.strip()
    ) == base64.b64decode(before.stdout.strip())

    parent_marker = tmp_path / "corrupt-parent-imported"
    parent_init = installed / "wea_vnext" / "executors" / "__init__.py"
    parent_original = parent_init.read_bytes()
    parent_init.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "Path(os.environ['MARKER']).write_text('executed')\n"
        + parent_original.decode("utf-8"),
        encoding="utf-8",
    )
    parent_rejected = _installed_python(
        installed,
        """
from wea_vnext.engine import ManifestError, installed_executor
try:
    installed_executor('0.6.0')
except ManifestError:
    print('rejected-before-parent-import')
else:
    raise SystemExit('corrupt parent unexpectedly verified')
""",
        MARKER=str(parent_marker),
    )
    assert parent_rejected.returncode == 0, (
        parent_rejected.stdout + parent_rejected.stderr
    )
    assert parent_rejected.stdout.strip() == "rejected-before-parent-import"
    assert not parent_marker.exists()
    parent_init.write_bytes(parent_original)

    old_init = installed / "wea_vnext" / "executors" / "v0_6_0" / "__init__.py"
    old_init_original = old_init.read_bytes()
    old_init.write_text(
        "raise RuntimeError('stale unchecked bytecode was executed')\n",
        encoding="utf-8",
    )
    py_compile.compile(
        str(old_init),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    old_init.write_bytes(old_init_original)
    with_unchecked_bytecode = _installed_python(installed, replay_code)
    assert with_unchecked_bytecode.returncode == 0, (
        with_unchecked_bytecode.stdout + with_unchecked_bytecode.stderr
    )
    assert base64.b64decode(
        with_unchecked_bytecode.stdout.strip()
    ) == base64.b64decode(before.stdout.strip())

    declarations = (
        installed / "wea_vnext" / "executors" / "v0_6_0" / "declarations.py"
    )
    declarations_original = declarations.read_bytes()
    declarations.write_text(
        "raise RuntimeError('stale facade bytecode was executed')\n",
        encoding="utf-8",
    )
    py_compile.compile(
        str(declarations),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    declarations.write_bytes(declarations_original)
    facade_code = """
from wea_vnext.declarations import parse_declaration
declaration = parse_declaration('### Декларация WEA\\n- action: test')
print(declaration.get('action'))
"""
    facade_ignores_unchecked_bytecode = _installed_python(installed, facade_code)
    assert facade_ignores_unchecked_bytecode.returncode == 0, (
        facade_ignores_unchecked_bytecode.stdout
        + facade_ignores_unchecked_bytecode.stderr
    )
    assert facade_ignores_unchecked_bytecode.stdout.strip() == "test"

    marker = tmp_path / "corrupt-executor-imported"
    old_init.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "Path(os.environ['MARKER']).write_text('executed')\n"
        + old_init.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rejected = _installed_python(
        installed,
        """
from wea_vnext.engine import ManifestError, installed_executor
try:
    installed_executor('0.6.0')
except ManifestError:
    print('rejected-before-import')
else:
    raise SystemExit('corrupt executor unexpectedly verified')
""",
        MARKER=str(marker),
    )
    assert rejected.returncode == 0, rejected.stdout + rejected.stderr
    assert rejected.stdout.strip() == "rejected-before-import"
    assert not marker.exists()
