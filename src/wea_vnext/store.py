"""Deterministic replay and isolated shadow-report storage."""

from __future__ import annotations

import ctypes
import errno
import os
import re
import secrets
import stat
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import ExecutorRegistry, RuntimeReference, load_executor

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

def _open_pinned_windows_directory(path: Path) -> int:
    """Open a non-reparse directory without allowing concurrent replacement."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0x0080,  # FILE_READ_ATTRIBUTES
        0x0001,  # FILE_SHARE_READ; deliberately deny write/delete sharing
        None,
        3,  # OPEN_EXISTING
        0x02200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        None,
    )
    invalid_handle = wintypes.HANDLE(-1).value
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = (
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        )

    info = FileAttributeTagInfo()
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_info.restype = wintypes.BOOL
    if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        close_handle(handle)
        raise ctypes.WinError(error)
    if info.file_attributes & 0x0400:  # FILE_ATTRIBUTE_REPARSE_POINT
        close_handle(handle)
        raise ValueError("shadow namespace cannot contain links or junctions")
    return int(handle)


def _open_relative_windows_directory(directory_handle: int, name: str) -> int:
    """Create or open one non-reparse directory beneath a pinned parent."""
    import ctypes
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.USHORT),
            ("maximum_length", wintypes.USHORT),
            ("buffer", wintypes.LPWSTR),
        )

    class ObjectAttributes(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.ULONG),
            ("root_directory", wintypes.HANDLE),
            ("object_name", ctypes.POINTER(UnicodeString)),
            ("attributes", wintypes.ULONG),
            ("security_descriptor", wintypes.LPVOID),
            ("security_quality_of_service", wintypes.LPVOID),
        )

    class IoStatusBlock(ctypes.Structure):
        _fields_ = (
            ("status", ctypes.c_long),
            ("information", ctypes.c_size_t),
        )

    buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    unicode_name = UnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(buffer, wintypes.LPWSTR),
    )
    attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        wintypes.HANDLE(directory_handle),
        ctypes.pointer(unicode_name),
        0x0040,  # OBJ_CASE_INSENSITIVE
        None,
        None,
    )
    io_status = IoStatusBlock()
    file_handle = wintypes.HANDLE()
    ntdll = ctypes.WinDLL("ntdll")
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    nt_create_file.restype = ctypes.c_long
    status = nt_create_file(
        ctypes.byref(file_handle),
        0x00100081,  # SYNCHRONIZE | READ_ATTRIBUTES | LIST_DIRECTORY
        ctypes.byref(attributes),
        ctypes.byref(io_status),
        None,
        0x0010,  # FILE_ATTRIBUTE_DIRECTORY
        0x0003,  # FILE_SHARE_READ | FILE_SHARE_WRITE; deny delete sharing
        3,  # FILE_OPEN_IF
        0x00200021,  # OPEN_REPARSE_POINT | DIRECTORY | SYNCHRONOUS_IO
        None,
        0,
    )
    if status < 0:
        rtl_error = ntdll.RtlNtStatusToDosError
        rtl_error.argtypes = (ctypes.c_long,)
        rtl_error.restype = wintypes.ULONG
        error = int(rtl_error(status))
        raise OSError(error, os.strerror(error), name)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = (
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        )

    info = FileAttributeTagInfo()
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_info.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not get_info(file_handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        close_handle(file_handle)
        raise ctypes.WinError(error)
    if info.file_attributes & 0x0400:
        close_handle(file_handle)
        raise ValueError("shadow namespace cannot contain links or junctions")
    raw_handle = file_handle.value
    if raw_handle is None:
        raise OSError("NtCreateFile returned an empty directory handle")
    return int(raw_handle)


def _open_relative_windows(directory_handle: int, name: str, *, create: bool) -> int:
    """Open one non-reparse child relative to a previously verified directory."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.USHORT),
            ("maximum_length", wintypes.USHORT),
            ("buffer", wintypes.LPWSTR),
        )

    class ObjectAttributes(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.ULONG),
            ("root_directory", wintypes.HANDLE),
            ("object_name", ctypes.POINTER(UnicodeString)),
            ("attributes", wintypes.ULONG),
            ("security_descriptor", wintypes.LPVOID),
            ("security_quality_of_service", wintypes.LPVOID),
        )

    class IoStatusBlock(ctypes.Structure):
        _fields_ = (
            ("status", ctypes.c_long),
            ("information", ctypes.c_size_t),
        )

    buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    unicode_name = UnicodeString(
        encoded_length,
        encoded_length + 2,
        ctypes.cast(buffer, wintypes.LPWSTR),
    )
    attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        wintypes.HANDLE(directory_handle),
        ctypes.pointer(unicode_name),
        0x0040,  # OBJ_CASE_INSENSITIVE
        None,
        None,
    )
    io_status = IoStatusBlock()
    file_handle = wintypes.HANDLE()
    ntdll = ctypes.WinDLL("ntdll")
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    nt_create_file.restype = ctypes.c_long
    desired_access = (0x40000000 if create else 0x80000000) | 0x00100000 | 0x0080
    status = nt_create_file(
        ctypes.byref(file_handle),
        desired_access,
        ctypes.byref(attributes),
        ctypes.byref(io_status),
        None,
        0x0080,  # FILE_ATTRIBUTE_NORMAL
        0x0001,  # FILE_SHARE_READ
        2 if create else 1,  # FILE_CREATE / FILE_OPEN
        0x00200060,  # OPEN_REPARSE_POINT | NON_DIRECTORY | SYNCHRONOUS_IO
        None,
        0,
    )
    if status < 0:
        rtl_error = ntdll.RtlNtStatusToDosError
        rtl_error.argtypes = (ctypes.c_long,)
        rtl_error.restype = wintypes.ULONG
        error = int(rtl_error(status))
        if create and error in {80, 183}:
            raise FileExistsError(error, os.strerror(error), name)
        raise OSError(error, os.strerror(error), name)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = (
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        )

    info = FileAttributeTagInfo()
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_info.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not get_info(file_handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        close_handle(file_handle)
        raise ctypes.WinError(error)
    if info.file_attributes & 0x0400:
        close_handle(file_handle)
        raise ValueError("shadow report destination cannot be a link or junction")
    raw_handle = file_handle.value
    if raw_handle is None:
        raise OSError("NtCreateFile returned an empty handle")
    return msvcrt.open_osfhandle(
        int(raw_handle), os.O_WRONLY if create else os.O_RDONLY
    )


def _open_beneath_posix(
    root_descriptor: int,
    relative_path: str,
    *,
    create: bool,
    directory: bool = False,
    nonblocking: bool = False,
) -> int:
    """Open a child atomically beneath a pinned repository root on Linux."""
    if sys.platform != "linux":
        raise OSError(
            errno.ENOTSUP,
            "secure shadow creation requires Linux openat2 on POSIX",
            relative_path,
        )

    class OpenHow(ctypes.Structure):
        _fields_ = (
            ("flags", ctypes.c_uint64),
            ("mode", ctypes.c_uint64),
            ("resolve", ctypes.c_uint64),
        )

    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.syscall
    syscall.argtypes = (
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.POINTER(OpenHow),
        ctypes.c_size_t,
    )
    syscall.restype = ctypes.c_long
    if create:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    else:
        flags = os.O_RDONLY
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    if nonblocking:
        flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    how = OpenHow(
        flags=flags,
        mode=0o600 if create else 0,
        # RESOLVE_NO_MAGICLINKS | RESOLVE_NO_SYMLINKS | RESOLVE_BENEATH
        resolve=0x02 | 0x04 | 0x08,
    )
    # openat2 is syscall 437 on Linux architectures supported by CPython.
    descriptor = int(
        syscall(
            437,
            root_descriptor,
            os.fsencode(relative_path),
            ctypes.byref(how),
            ctypes.sizeof(how),
        )
    )
    if descriptor < 0:
        error = ctypes.get_errno()
        if create and error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), relative_path)
        raise OSError(error, os.strerror(error), relative_path)
    return descriptor


def _link_pinned_posix(
    source_descriptor: int,
    directory_descriptor: int,
    destination_name: str,
) -> None:
    """Publish one pinned inode relative to the pinned shadow directory."""
    if sys.platform != "linux":
        raise OSError(
            errno.ENOTSUP,
            "secure shadow publication requires Linux linkat on POSIX",
            destination_name,
        )
    libc = ctypes.CDLL(None, use_errno=True)
    linkat = libc.linkat
    linkat.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    )
    linkat.restype = ctypes.c_int
    result = int(
        linkat(
            -100,  # AT_FDCWD
            os.fsencode(f"/proc/self/fd/{source_descriptor}"),
            directory_descriptor,
            os.fsencode(destination_name),
            0x400,  # AT_SYMLINK_FOLLOW: follow only the kernel-owned proc fd link
        )
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(
                error,
                os.strerror(error),
                destination_name,
            )
        raise OSError(error, os.strerror(error), destination_name)


def _install_linux_write_sandbox(root_descriptor: int) -> None:
    """Restrict this worker thread's filesystem mutations to repo_root."""
    if sys.platform != "linux":
        raise OSError(
            errno.ENOTSUP,
            "secure shadow storage requires Linux Landlock on POSIX",
        )

    class RulesetAttr(ctypes.Structure):
        _fields_ = (("handled_access_fs", ctypes.c_uint64),)

    class PathBeneathAttr(ctypes.Structure):
        _fields_ = (
            ("allowed_access", ctypes.c_uint64),
            ("parent_fd", ctypes.c_int32),
        )

    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    # landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)
    abi = int(syscall(444, None, 0, 1))
    if abi < 1:
        error = ctypes.get_errno() or errno.ENOTSUP
        raise OSError(error, "Linux Landlock is unavailable")

    handled_access = (
        (1 << 1)  # WRITE_FILE
        | (1 << 4)  # REMOVE_DIR
        | (1 << 5)  # REMOVE_FILE
        | (1 << 6)  # MAKE_CHAR
        | (1 << 7)  # MAKE_DIR
        | (1 << 8)  # MAKE_REG
        | (1 << 9)  # MAKE_SOCK
        | (1 << 10)  # MAKE_FIFO
        | (1 << 11)  # MAKE_BLOCK
        | (1 << 12)  # MAKE_SYM
    )
    if abi >= 2:
        handled_access |= 1 << 13  # REFER
    if abi >= 3:
        handled_access |= 1 << 14  # TRUNCATE

    ruleset_attr = RulesetAttr(handled_access)
    ruleset_descriptor = int(
        syscall(444, ctypes.byref(ruleset_attr), ctypes.sizeof(ruleset_attr), 0)
    )
    if ruleset_descriptor < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), "landlock_create_ruleset")
    try:
        path_rule = PathBeneathAttr(handled_access, root_descriptor)
        # LANDLOCK_RULE_PATH_BENEATH
        if int(syscall(445, ruleset_descriptor, 1, ctypes.byref(path_rule), 0)) < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), "landlock_add_rule")

        prctl = libc.prctl
        prctl.argtypes = (
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        )
        prctl.restype = ctypes.c_int
        if int(prctl(38, 1, 0, 0, 0)) != 0:  # PR_SET_NO_NEW_PRIVS
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), "prctl")
        if int(syscall(446, ruleset_descriptor, 0)) < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), "landlock_restrict_self")
    finally:
        os.close(ruleset_descriptor)


def _run_linux_write_sandboxed(root: Path, operation: Callable[[], Path]) -> Path:
    """Run one write in a disposable Landlocked thread."""
    results: list[Path] = []
    errors: list[BaseException] = []

    def run() -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        root_descriptor: int | None = None
        try:
            root_descriptor = os.open(root, flags)
            opened = os.fstat(root_descriptor)
            current = os.stat(root, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("repo_root changed before sandboxing")
            _install_linux_write_sandbox(root_descriptor)
            results.append(operation())
        except BaseException as exc:
            errors.append(exc)
        finally:
            if root_descriptor is not None:
                os.close(root_descriptor)

    worker = threading.Thread(target=run, name="wea-vnext-shadow-writer")
    worker.start()
    worker.join()
    if errors:
        raise errors[0]
    if len(results) != 1:
        raise OSError("sandboxed shadow writer returned no result")
    return results[0]


def _open_or_create_directory_posix(
    parent_descriptor: int,
    name: str,
) -> int:
    """Create a directory relative to a pinned parent and reopen it safely."""
    try:
        return _open_beneath_posix(
            parent_descriptor,
            name,
            create=False,
            directory=True,
        )
    except OSError as exc:
        if exc.errno != errno.ENOENT:
            raise
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
    except FileExistsError:
        pass
    return _open_beneath_posix(
        parent_descriptor,
        name,
        create=False,
        directory=True,
    )


@contextmanager
def _pin_shadow_directory_posix(
    root: Path, shadow_root: Path
) -> Iterator[_PinnedShadowDirectory]:
    """Create and open the shadow namespace beneath one pinned root."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    root_descriptor = os.open(root, flags)
    runs_descriptor: int | None = None
    shadow_descriptor: int | None = None
    try:
        opened = os.fstat(root_descriptor)
        current = os.stat(root, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError("repo_root changed during verification")
        runs_descriptor = _open_or_create_directory_posix(
            root_descriptor,
            ".wea_runs",
        )
        shadow_descriptor = _open_or_create_directory_posix(
            runs_descriptor,
            "vnext-shadow",
        )
        _verify_pinned_shadow(shadow_descriptor, shadow_root)
        yield _PinnedShadowDirectory(
            root=root_descriptor,
            shadow=shadow_descriptor,
        )
    finally:
        if shadow_descriptor is not None:
            os.close(shadow_descriptor)
        if runs_descriptor is not None:
            os.close(runs_descriptor)
        os.close(root_descriptor)


@contextmanager
def _pin_shadow_directory(
    root: Path, runs_root: Path, shadow_root: Path
) -> Iterator[_PinnedShadowDirectory]:
    """Anchor creation to verified directories across the final write."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        handles: list[int] = []
        try:
            handles.append(_open_pinned_windows_directory(root))
            handles.append(
                _open_relative_windows_directory(handles[-1], runs_root.name)
            )
            handles.append(
                _open_relative_windows_directory(handles[-1], shadow_root.name)
            )
            yield _PinnedShadowDirectory(root=handles[0], shadow=handles[-1])
        finally:
            for handle in reversed(handles):
                close_handle(handle)
        return

    with _pin_shadow_directory_posix(root, shadow_root) as pinned:
        yield pinned


@dataclass(frozen=True)
class _PinnedShadowDirectory:
    root: int
    shadow: int


def _verify_pinned_shadow(descriptor: int, shadow_root: Path) -> None:
    opened = os.fstat(descriptor)
    current = os.stat(shadow_root, follow_symlinks=False)
    if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise ValueError("shadow namespace changed during publication")


def _open_existing_shadow_report_posix(
    directory_descriptor: int, destination_name: str
) -> int:
    descriptor = _open_beneath_posix(
        directory_descriptor,
        destination_name,
        create=False,
        nonblocking=True,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("existing shadow report must be a regular file")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


@dataclass(frozen=True)
class ReplayReport:
    state: Any
    effects: tuple[Any, ...]
    batch_hashes: tuple[str, ...]
    read_attempts: tuple[tuple[str, Any], ...]
    _state_bytes: bytes
    _report_bytes: bytes

    @property
    def state_bytes(self) -> bytes:
        return self._state_bytes

    @property
    def report_bytes(self) -> bytes:
        return self._report_bytes


def replay(
    batches: Iterable[Any],
    runtime: RuntimeReference,
    *,
    registry: ExecutorRegistry | None = None,
) -> ReplayReport:
    """Replay complete GitHub batches without mutating inputs or live state."""
    handle = load_executor(runtime, registry=registry)
    executor = handle.module
    return ReplayReport(*executor.replay(batches, handle.reference))


def _write_shadow_report(root: Path, run_id: str, report: ReplayReport) -> Path:
    """Perform one write after the platform containment boundary is active."""
    runs_root = root / ".wea_runs"
    shadow_root = runs_root / "vnext-shadow"
    destination = shadow_root / f"{run_id}.json"
    with _pin_shadow_directory(root, runs_root, shadow_root) as pinned:
        temporary_name = f".{run_id}.{secrets.token_hex(16)}.tmp"
        temporary = shadow_root / temporary_name
        if os.name == "nt":
            descriptor = _open_relative_windows(
                pinned.shadow, temporary_name, create=True
            )
        else:
            descriptor = _open_beneath_posix(
                pinned.shadow, temporary_name, create=True
            )
        published = False
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(report.report_bytes)
                output.flush()
                os.fsync(output.fileno())
                if os.name == "nt":
                    # The still-open handle denies write/delete sharing, so the
                    # pathname cannot be replaced before CreateHardLink resolves it.
                    os.link(temporary, destination)
                else:
                    _verify_pinned_shadow(pinned.shadow, shadow_root)
                    _link_pinned_posix(
                        output.fileno(),
                        pinned.shadow,
                        destination.name,
                    )
            published = True
        except FileExistsError:
            if os.name == "nt":
                existing_descriptor = _open_relative_windows(
                    pinned.shadow, destination.name, create=False
                )
            else:
                existing_descriptor = _open_existing_shadow_report_posix(
                    pinned.shadow,
                    destination.name,
                )
            with os.fdopen(existing_descriptor, "rb") as existing:
                existing_bytes = existing.read()
            if existing_bytes != report.report_bytes:
                raise FileExistsError(
                    f"shadow report already exists with different bytes: {run_id}"
                ) from None
            published = True
        finally:
            try:
                if os.name == "nt":
                    temporary.unlink(missing_ok=True)
                else:
                    os.unlink(temporary_name, dir_fd=pinned.shadow)
            except FileNotFoundError:
                pass
        if not published:
            raise OSError("shadow report was not published")
    return destination


def write_shadow_report(repo_root: Path, run_id: str, report: ReplayReport) -> Path:
    """Write a replay report only under the ignored vNext shadow namespace."""
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must be a single safe path component")
    if run_id.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError("run_id must not use a reserved Windows device name")
    root = repo_root.resolve()
    if os.name == "nt":
        return _write_shadow_report(root, run_id, report)
    if sys.platform != "linux":
        raise OSError(
            errno.ENOTSUP,
            "secure shadow storage requires Linux on POSIX",
        )
    return _run_linux_write_sandboxed(
        root,
        lambda: _write_shadow_report(root, run_id, report),
    )
