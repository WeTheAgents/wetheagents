"""Select and verify immutable WEA vNext executors."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import re
import sys
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import abc as importlib_abc
from importlib import resources
from importlib import util as importlib_util
from types import MappingProxyType, ModuleType
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from importlib.abc import Traversable


class RuntimeReference(NamedTuple):
    """The immutable runtime triple stored by a Contract."""

    ruleset_hash: str
    tide_interface_version: str
    executor_manifest_hash: str


def _normalize_runtime_reference(reference: RuntimeReference) -> RuntimeReference:
    """Detach a caller-owned tuple subclass from the verified runtime identity."""
    if not isinstance(reference, tuple) or tuple.__len__(reference) != 3:
        raise RuntimeMismatchError("Contract runtime triple is malformed")
    values = tuple(tuple.__getitem__(reference, index) for index in range(3))
    if any(type(value) is not str for value in values):
        raise RuntimeMismatchError("Contract runtime triple is malformed")
    return RuntimeReference(*values)


class RuntimeMismatchError(ValueError):
    """Raised when no verified executor matches a Contract runtime triple."""


class ManifestError(ValueError):
    """Raised when an installed executor is not semantically closed."""


@dataclass(frozen=True)
class ExecutorDescriptor:
    reference: RuntimeReference
    module_name: str


@dataclass(frozen=True)
class VerifiedManifest:
    executor_version: str
    manifest_hash: str
    reference: RuntimeReference
    files: tuple[str, ...]


@dataclass(frozen=True)
class _LoadedExecutor:
    root: ModuleType
    modules: Mapping[str, ModuleType]


class _ReadOnlyModule:
    """Expose verified attributes without exposing a mutable module namespace."""

    __slots__ = ("__module",)

    def __init__(self, module: ModuleType) -> None:
        object.__setattr__(self, "_ReadOnlyModule__module", module)

    def __getattribute__(self, name: str) -> Any:
        if name in {"__dict__", "_ReadOnlyModule__module"}:
            raise AttributeError("verified executor namespace is private")
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            module = object.__getattribute__(self, "_ReadOnlyModule__module")
            return getattr(module, name)

    def __setattr__(self, name: str, value: Any) -> None:
        del name, value
        raise AttributeError("verified executor modules are read-only")

    def __dir__(self) -> list[str]:
        module = object.__getattribute__(self, "_ReadOnlyModule__module")
        return dir(module)


@dataclass(frozen=True)
class ExecutorHandle:
    descriptor: ExecutorDescriptor

    @property
    def reference(self) -> RuntimeReference:
        return self.descriptor.reference

    @property
    def module(self) -> Any:
        verified = self.verify()
        if verified.reference != self.reference:
            raise RuntimeMismatchError(
                "installed executor changed after its handle was resolved"
            )
        return _load_verified_module(self.descriptor.module_name, verified)

    def import_module(self, relative_name: str) -> Any:
        """Return one submodule from the already verified source closure."""
        verified = self.verify()
        if verified.reference != self.reference:
            raise RuntimeMismatchError(
                "installed executor changed after its handle was resolved"
            )
        return _load_verified_submodule(
            self.descriptor.module_name,
            relative_name,
            verified,
        )

    def import_modules(self, relative_names: Iterable[str]) -> Mapping[str, Any]:
        """Return several submodules from one manifest-verified source closure."""
        verified = self.verify()
        if verified.reference != self.reference:
            raise RuntimeMismatchError(
                "installed executor changed after its handle was resolved"
            )
        return _load_verified_submodules(
            self.descriptor.module_name,
            tuple(relative_names),
            verified,
        )

    def verify(self) -> VerifiedManifest:
        return _verify_installed_manifest(self.descriptor.module_name)


@dataclass(frozen=True)
class ExecutorRegistry:
    entries: tuple[ExecutorDescriptor, ...]

    def __post_init__(self) -> None:
        references = [entry.reference for entry in self.entries]
        if len(references) != len(set(references)):
            raise ValueError("executor registry contains a duplicate runtime triple")

    def resolve(self, reference: RuntimeReference) -> ExecutorDescriptor:
        normalized = _normalize_runtime_reference(reference)
        matches = [
            entry
            for entry in self.entries
            if _normalize_runtime_reference(entry.reference) == normalized
        ]
        if len(matches) != 1:
            raise RuntimeMismatchError(
                "no executor matches the Contract runtime triple"
            )
        return matches[0]


_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXECUTOR_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
_EXECUTOR_PACKAGE = re.compile(r"v[0-9]+(?:_[0-9]+)+")
_RULESET_PATH = re.compile(r"rulesets/[0-9]+(?:\.[0-9]+)*\.json")
_MAX_JSON_INTEGER_DIGITS = 640
_EXECUTOR_LOAD_LOCK = threading.RLock()
_MISSING_BINDING = object()
_PUBLIC_EXECUTOR_SUBMODULES = frozenset(
    {
        "declarations",
        "identity",
        "identity_hello_world",
        "identity_migration",
        "projection",
    }
)
_MANIFEST_KEYS = {
    "executor_version",
    "files",
    "module",
    "python_abi",
    "ruleset_path",
    "ruleset_sha256",
    "semantic_dependencies",
    "tide_interface_version",
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resource_root() -> Traversable:
    return resources.files("wea_vnext")


def _join_resource(root: Traversable, *parts: str) -> Traversable:
    """Join one component at a time for Python 3.10 Traversable support."""
    result = root
    for part in parts:
        result = result.joinpath(part)
    return result


def _manifest_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def _reject_manifest_number(value: str) -> None:
    raise ManifestError(f"manifest contains a non-integer number: {value}")


def _parse_bounded_integer(value: str) -> int:
    if len(value.removeprefix("-")) > _MAX_JSON_INTEGER_DIGITS:
        raise ManifestError(
            f"JSON integer exceeds {_MAX_JSON_INTEGER_DIGITS} decimal digits"
        )
    return int(value)


def _load_strict_json(raw: bytes, *, source: str) -> tuple[dict[str, object], bytes]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ManifestError(f"{source} contains a UTF-8 BOM")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_manifest_object,
            parse_int=_parse_bounded_integer,
            parse_float=_reject_manifest_number,
            parse_constant=_reject_manifest_number,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise ManifestError(f"{source} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{source} must contain a JSON object")
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ManifestError(f"{source} is not canonicalizable JSON") from exc
    return value, canonical


def _load_canonical_json(raw: bytes, *, source: str) -> tuple[dict[str, object], bytes]:
    value, canonical = _load_strict_json(raw, source=source)
    if canonical != raw:
        raise ManifestError(f"{source} must use exact canonical JSON bytes")
    return value, canonical


def _installed_modules() -> tuple[str, ...]:
    executor_root = _resource_root().joinpath("executors")
    package_names = sorted(
        entry.name
        for entry in executor_root.iterdir()
        if entry.is_dir() and _EXECUTOR_PACKAGE.fullmatch(entry.name)
    )
    return tuple(f"wea_vnext.executors.{name}" for name in package_names)


def _expected_executor_files(module_name: str, ruleset_path: str) -> set[str]:
    package_name = module_name.rsplit(".", 1)[-1]
    executor_dir = _join_resource(_resource_root(), "executors", package_name)
    files: set[str] = set()
    pending: list[tuple[Traversable, str, int]] = [
        (executor_dir, f"executors/{package_name}", 0)
    ]
    while pending:
        directory, prefix, depth = pending.pop()
        if depth > 64:
            raise ManifestError("executor source tree exceeds the depth limit")
        try:
            entries = tuple(directory.iterdir())
        except (OSError, RecursionError, RuntimeError) as exc:
            raise ManifestError(
                "executor source tree cannot be traversed safely"
            ) from exc
        for entry in entries:
            relative_path = f"{prefix}/{entry.name}"
            is_link = getattr(entry, "is_symlink", lambda: False)()
            is_junction = getattr(entry, "is_junction", lambda: False)()
            if is_link or is_junction:
                raise ManifestError("executor source tree cannot contain links")
            if entry.is_dir():
                if entry.name != "__pycache__":
                    pending.append((entry, relative_path, depth + 1))
            elif entry.name != "manifest.json" and not entry.name.endswith(
                (".pyc", ".pyo")
            ):
                files.add(relative_path)

    files.add("executors/__init__.py")
    files.add(ruleset_path)
    return files


def _verify_installed_manifest(module_name: str) -> VerifiedManifest:
    package_name = module_name.rsplit(".", 1)[-1]
    manifest_path = _join_resource(
        _resource_root(), "executors", package_name, "manifest.json"
    )
    raw = manifest_path.read_bytes()
    manifest, canonical_manifest = _load_canonical_json(raw, source=str(manifest_path))

    if set(manifest) != _MANIFEST_KEYS:
        raise ManifestError("manifest top-level keys do not match its schema")
    if manifest.get("module") != module_name:
        raise ManifestError("manifest module does not match its package")
    if manifest.get("python_abi") != "py3-none-any":
        raise ManifestError("executor must declare the exact pure-Python ABI tag")
    expected_version = package_name.removeprefix("v").replace("_", ".")
    if manifest.get("semantic_dependencies") != {}:
        raise ManifestError("semantic dependencies are not supported")

    files = manifest.get("files")
    if not isinstance(files, dict) or not all(
        isinstance(path, str) and isinstance(digest, str) and _SHA256.fullmatch(digest)
        for path, digest in files.items()
    ):
        raise ManifestError("manifest files must map paths to SHA-256 digests")
    ruleset_path = manifest.get("ruleset_path")
    if not isinstance(ruleset_path, str) or not _RULESET_PATH.fullmatch(ruleset_path):
        raise ManifestError("manifest ruleset_path is not a safe versioned JSON path")
    if set(files) != _expected_executor_files(module_name, ruleset_path):
        raise ManifestError(
            "manifest does not cover the complete executor source closure"
        )

    root = _resource_root()
    for relative_path, expected_digest in files.items():
        actual_digest = _sha256(
            _join_resource(root, *relative_path.split("/")).read_bytes()
        )
        if actual_digest != expected_digest:
            raise ManifestError(f"manifest hash mismatch for {relative_path}")

    ruleset_hash = manifest.get("ruleset_sha256")
    interface_version = manifest.get("tide_interface_version")
    executor_version = manifest.get("executor_version")
    if (
        not isinstance(ruleset_hash, str)
        or not isinstance(interface_version, str)
        or not isinstance(executor_version, str)
    ):
        raise ManifestError("manifest runtime versions are incomplete")
    if not _SHA256.fullmatch(ruleset_hash):
        raise ManifestError("ruleset content hash is not a SHA-256 digest")
    if executor_version != expected_version:
        raise ManifestError("executor version does not match its package name")
    ruleset_resource = _join_resource(root, *ruleset_path.split("/"))
    ruleset_raw = ruleset_resource.read_bytes()
    rules, canonical_rules = _load_canonical_json(
        ruleset_raw, source=str(ruleset_resource)
    )
    if _sha256(canonical_rules) != ruleset_hash:
        raise ManifestError("ruleset content hash does not match canonical rules")
    ruleset_version = ruleset_path.removeprefix("rulesets/").removesuffix(".json")
    if rules.get("version") != ruleset_version:
        raise ManifestError("ruleset version does not match its versioned path")
    if rules.get("tide_interface_version") != interface_version:
        raise ManifestError("manifest Tide interface does not match packaged rules")

    manifest_hash = _sha256(canonical_manifest)
    reference = RuntimeReference(ruleset_hash, interface_version, manifest_hash)
    return VerifiedManifest(
        executor_version, manifest_hash, reference, tuple(sorted(files))
    )


@dataclass(frozen=True)
class _VerifiedSource:
    resource: Any
    digest: str
    is_package: bool


class _VerifiedSourceLoader(importlib_abc.Loader):
    """Execute exactly the source bytes covered by the verified manifest."""

    def __init__(
        self,
        fullname: str,
        source: _VerifiedSource,
        loaded: dict[str, ModuleType],
        verifier_capability: object,
    ) -> None:
        self.fullname = fullname
        self.source = source
        self.loaded = loaded
        self.verifier_capability = verifier_capability

    def create_module(self, spec: Any) -> None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        raw = self.source.resource.read_bytes()
        if _sha256(raw) != self.source.digest:
            raise ManifestError(f"manifest hash changed while loading {self.fullname}")
        filename = str(self.source.resource)
        code = compile(raw, filename, "exec", dont_inherit=True)
        module.__dict__["_WEA_VERIFIER_CAPABILITY"] = self.verifier_capability
        exec(code, module.__dict__)
        self.loaded[self.fullname] = module


class _VerifiedSourceFinder(importlib_abc.MetaPathFinder):
    def __init__(
        self,
        sources: dict[str, _VerifiedSource],
        loaded: dict[str, ModuleType],
        verifier_capability: object,
    ) -> None:
        self.sources = sources
        self.loaded = loaded
        self.verifier_capability = verifier_capability

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: ModuleType | None = None,
    ) -> Any:
        del path, target
        source = self.sources.get(fullname)
        if source is None:
            return None
        loader = _VerifiedSourceLoader(
            fullname,
            source,
            self.loaded,
            self.verifier_capability,
        )
        return importlib_util.spec_from_loader(
            fullname,
            loader,
            is_package=source.is_package,
        )


def _verified_python_sources(
    module_name: str, verified: VerifiedManifest
) -> dict[str, _VerifiedSource]:
    """Map manifest-pinned Python paths to import names without touching bytecode."""
    root = _resource_root()
    package_name = module_name.rsplit(".", 1)[-1]
    manifest_raw = _join_resource(
        root, "executors", package_name, "manifest.json"
    ).read_bytes()
    manifest, canonical_manifest = _load_canonical_json(
        manifest_raw, source=f"{module_name} manifest"
    )
    if _sha256(canonical_manifest) != verified.manifest_hash:
        raise ManifestError("manifest changed after executor verification")
    files = manifest["files"]
    if not isinstance(files, dict):
        raise ManifestError("verified manifest files changed while loading")

    sources: dict[str, _VerifiedSource] = {}
    for relative_path in verified.files:
        if not relative_path.endswith(".py"):
            continue
        digest = files.get(relative_path)
        if not isinstance(digest, str):
            raise ManifestError("verified manifest source digest is missing")
        parts = relative_path.removesuffix(".py").split("/")
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        fullname = "wea_vnext." + ".".join(parts)
        sources[fullname] = _VerifiedSource(
            _join_resource(root, *relative_path.split("/")),
            digest,
            is_package,
        )
    if module_name not in sources or "wea_vnext.executors" not in sources:
        raise ManifestError("verified manifest omits an executor package source")
    return sources


def _load_verified_module(
    module_name: str, verified: VerifiedManifest
) -> _ReadOnlyModule:
    """Return a read-only view of one verifier-owned executor instance."""
    return _ReadOnlyModule(_load_verified_executor(module_name, verified).root)


def _load_verified_executor(
    module_name: str,
    verified: VerifiedManifest,
) -> _LoadedExecutor:
    """Load one fresh private closure outside the ordinary module cache."""
    with _EXECUTOR_LOAD_LOCK:
        sources = _verified_python_sources(module_name, verified)
        previous_modules = {
            name: sys.modules[name] for name in sources if name in sys.modules
        }
        previous_bindings: list[tuple[ModuleType, str, Any]] = []
        seen_bindings: set[tuple[int, str]] = set()
        for name in sources:
            parent_name, separator, child_name = name.rpartition(".")
            if not separator:
                continue
            parent = sys.modules.get(parent_name)
            if parent is None:
                continue
            binding_key = (id(parent), child_name)
            if binding_key in seen_bindings:
                continue
            seen_bindings.add(binding_key)
            previous_bindings.append(
                (
                    parent,
                    child_name,
                    vars(parent).get(child_name, _MISSING_BINDING),
                )
            )
        for name in sorted(sources, key=lambda item: item.count("."), reverse=True):
            sys.modules.pop(name, None)

        loaded: dict[str, ModuleType] = {}
        verifier_capability = object()
        finder = _VerifiedSourceFinder(sources, loaded, verifier_capability)
        sys.meta_path.insert(0, finder)
        try:
            imported = importlib.import_module(module_name)
            for source_module in sorted(
                sources, key=lambda item: (item.count("."), item)
            ):
                importlib.import_module(source_module)
            if set(loaded) != set(sources):
                raise ManifestError("verified loader did not execute the full closure")
            if loaded.get(module_name) is not imported:
                raise ManifestError(
                    "executor root did not come from the verified loader"
                )
            _bind_verified_runtime(
                imported,
                verified.reference,
                verifier_capability,
            )
            for module in loaded.values():
                module.__dict__.pop("_WEA_VERIFIER_CAPABILITY", None)
        finally:
            sys.meta_path.remove(finder)
            for name in sources:
                sys.modules.pop(name, None)
            sys.modules.update(previous_modules)
            for parent, child_name, previous in previous_bindings:
                if previous is _MISSING_BINDING:
                    vars(parent).pop(child_name, None)
                else:
                    setattr(parent, child_name, previous)

        return _LoadedExecutor(
            imported,
            MappingProxyType(dict(loaded)),
        )


def _load_verified_submodule(
    module_name: str,
    relative_name: str,
    verified: VerifiedManifest,
) -> _ReadOnlyModule:
    """Return the exact module object created by the manifest-pinned loader."""
    if not relative_name or any(
        not part.isidentifier() for part in relative_name.split(".")
    ):
        raise ManifestError("executor submodule name is invalid")
    if relative_name not in _PUBLIC_EXECUTOR_SUBMODULES:
        raise ManifestError("executor submodule is internal")
    loaded = _load_verified_executor(module_name, verified)
    fullname = f"{module_name}.{relative_name}"
    module = loaded.modules.get(fullname)
    if module is None:
        raise ManifestError("executor submodule is outside the verified closure")
    return _ReadOnlyModule(module)


def _load_verified_submodules(
    module_name: str,
    relative_names: tuple[str, ...],
    verified: VerifiedManifest,
) -> Mapping[str, Any]:
    """Return multiple read-only submodules backed by one verified closure."""
    if not relative_names or len(relative_names) != len(set(relative_names)):
        raise ManifestError("executor submodule names must be unique")
    for relative_name in relative_names:
        if not relative_name or any(
            not part.isidentifier() for part in relative_name.split(".")
        ):
            raise ManifestError("executor submodule name is invalid")
        if relative_name not in _PUBLIC_EXECUTOR_SUBMODULES:
            raise ManifestError("executor submodule is internal")
    loaded = _load_verified_executor(module_name, verified)
    result: dict[str, Any] = {}
    for relative_name in relative_names:
        fullname = f"{module_name}.{relative_name}"
        module = loaded.modules.get(fullname)
        if module is None:
            raise ManifestError("executor submodule is outside the verified closure")
        result[relative_name] = _ReadOnlyModule(module)
    return MappingProxyType(result)


def _bind_verified_runtime(
    module: ModuleType,
    reference: RuntimeReference,
    verifier_capability: object,
) -> None:
    binder = getattr(module, "_bind_verified_runtime", None)
    if not callable(binder):
        raise ManifestError("executor does not expose runtime provenance binding")
    try:
        parameter_count = len(inspect.signature(binder).parameters)
    except (TypeError, ValueError) as exc:
        raise ManifestError("executor runtime binder signature is invalid") from exc
    if parameter_count == 1:
        binder(reference)
    elif parameter_count == 2:
        binder(reference, verifier_capability)
    else:
        raise ManifestError("executor runtime binder signature is invalid")


def installed_executor(version: str) -> ExecutorDescriptor:
    """Return a freshly verified descriptor for an installed executor."""
    if type(version) is not str or not _EXECUTOR_VERSION.fullmatch(version):
        raise RuntimeMismatchError("executor version must be canonical dotted semver")
    module_name = f"wea_vnext.executors.v{version.replace('.', '_')}"
    if module_name not in _installed_modules():
        raise RuntimeMismatchError(f"executor {version} is not installed")
    verified = _verify_installed_manifest(module_name)
    if verified.executor_version != version:
        raise RuntimeMismatchError("installed executor version does not match request")
    return ExecutorDescriptor(reference=verified.reference, module_name=module_name)


def default_registry() -> ExecutorRegistry:
    entries: list[ExecutorDescriptor] = []
    for module in _installed_modules():
        version = module.rsplit(".v", 1)[1].replace("_", ".")
        try:
            entries.append(installed_executor(version))
        except (ManifestError, OSError):
            continue
    return ExecutorRegistry(tuple(entries))


def _resolve_installed_reference(reference: RuntimeReference) -> ExecutorDescriptor:
    matches: list[str] = []
    for module_name in _installed_modules():
        try:
            verified = _verify_installed_manifest(module_name)
        except (ManifestError, OSError):
            continue
        if verified.reference == reference:
            matches.append(module_name)
    if len(matches) != 1:
        raise RuntimeMismatchError("no executor matches the Contract runtime triple")
    return ExecutorDescriptor(reference=reference, module_name=matches[0])


def load_executor(
    reference: RuntimeReference,
    *,
    registry: ExecutorRegistry | None = None,
) -> ExecutorHandle:
    """Resolve the exact Contract triple and verify its package before use."""
    normalized = _normalize_runtime_reference(reference)
    selected = (
        registry.resolve(normalized)
        if registry is not None
        else _resolve_installed_reference(normalized)
    )
    verified = _verify_installed_manifest(selected.module_name)
    if verified.reference != normalized:
        raise RuntimeMismatchError(
            "installed executor no longer matches the Contract runtime triple"
        )
    return ExecutorHandle(
        ExecutorDescriptor(
            reference=verified.reference,
            module_name=selected.module_name,
        )
    )
