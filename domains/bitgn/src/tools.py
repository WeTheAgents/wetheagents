"""Dispatch Pydantic tool models to backend runtimes.

Supports two backends:
- BitGN gRPC (remote API)
- LocalVaultRuntime (local files for arena training)

Both return JSON strings in the same format.
"""

import json
from collections.abc import Callable

from google.protobuf.json_format import MessageToDict

from bitgn.vm.mini_connect import MiniRuntimeClientSync
from bitgn.vm.mini_pb2 import (
    AnswerRequest,
    DeleteRequest,
    ListRequest,
    OutlineRequest,
    ReadRequest,
    SearchRequest,
    WriteRequest,
)
from connectrpc.errors import ConnectError

from src.models import (
    DeleteTool,
    ListTool,
    OutlineTool,
    ReadTool,
    ReportCompletion,
    SearchTool,
    ToolAction,
    WriteTool,
)

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"

# Type alias for the dispatcher callable
Dispatcher = Callable[[ToolAction], str]


# --- BitGN gRPC dispatcher ---


def bitgn_dispatcher(vm: MiniRuntimeClientSync) -> Dispatcher:
    """Create a dispatcher that routes tool calls to BitGN gRPC."""

    def _dispatch(tool: ToolAction) -> str:
        try:
            result = _call_grpc(vm, tool)
            mapped = MessageToDict(result)
            return json.dumps(mapped, indent=2)
        except ConnectError as e:
            error_msg = f"ERROR {e.code}: {e.message}"
            print(f"  {CLI_RED}{error_msg}{CLI_CLR}")
            return error_msg

    return _dispatch


def _call_grpc(vm: MiniRuntimeClientSync, tool: ToolAction):
    """Map tool model to gRPC call."""
    match tool:
        case OutlineTool(path=path):
            return vm.outline(OutlineRequest(path=path))
        case ReadTool(path=path):
            return vm.read(ReadRequest(path=path))
        case ListTool(path=path):
            return vm.list(ListRequest(path=path))
        case SearchTool(pattern=pattern, count=count, path=path):
            return vm.search(SearchRequest(path=path, pattern=pattern, count=count))
        case WriteTool(path=path, content=content):
            return vm.write(WriteRequest(path=path, content=content))
        case DeleteTool(path=path):
            return vm.delete(DeleteRequest(path=path))
        case ReportCompletion(answer=answer, refs=refs):
            return vm.answer(AnswerRequest(answer=answer, refs=refs))
        case _:
            raise ValueError(f"Unknown tool type: {type(tool)}")


# --- Local vault dispatcher ---


def local_dispatcher(vault_runtime) -> Dispatcher:
    """Create a dispatcher that routes tool calls to a LocalVaultRuntime."""
    from src.vault_runtime import LocalVaultRuntime

    vr: LocalVaultRuntime = vault_runtime

    def _dispatch(tool: ToolAction) -> str:
        match tool:
            case OutlineTool(path=path):
                return vr.outline(path)
            case ReadTool(path=path):
                return vr.read(path)
            case ListTool(path=path):
                return vr.list(path)
            case SearchTool(pattern=pattern, count=count, path=path):
                return vr.search(pattern, count, path)
            case WriteTool(path=path, content=content):
                return vr.write(path, content)
            case DeleteTool(path=path):
                return vr.delete(path)
            case ReportCompletion(answer=answer, refs=refs):
                return vr.answer(answer, list(refs))
            case _:
                raise ValueError(f"Unknown tool type: {type(tool)}")

    return _dispatch


# --- Legacy compatibility ---


def dispatch(vm: MiniRuntimeClientSync, tool: ToolAction) -> str:
    """Legacy dispatcher — wraps bitgn_dispatcher for backward compatibility."""
    return bitgn_dispatcher(vm)(tool)
