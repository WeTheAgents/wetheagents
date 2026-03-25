"""Dispatch Pydantic tool models to BitGN PCM gRPC runtime.

Formats results as shell-like plaintext (tree, ls, cat, rg) for token efficiency.
"""

import json
import shlex

from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import (
    AnswerRequest,
    ContextRequest,
    DeleteRequest,
    FindRequest,
    ListRequest,
    MkDirRequest,
    MoveRequest,
    Outcome,
    ReadRequest,
    SearchRequest,
    TreeRequest,
    WriteRequest,
)
from connectrpc.errors import ConnectError
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel

from src.pcm_models import (
    ContextTool,
    DeleteTool,
    FindTool,
    ListTool,
    MkDirTool,
    MoveTool,
    PcmReportCompletion,
    PcmToolAction,
    ReadTool,
    SearchTool,
    TreeTool,
    WriteTool,
)
from src.tools import Dispatcher

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"

OUTCOME_BY_NAME = {
    "OUTCOME_OK": Outcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": Outcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": Outcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": Outcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": Outcome.OUTCOME_ERR_INTERNAL,
}

FIND_KIND_MAP = {"all": 0, "files": 1, "dirs": 2}


# --- Shell-like output formatting ---


def _render_command(command: str, body: str) -> str:
    return f"{command}\n{body}"


def _format_tree_entry(entry, prefix: str = "", is_last: bool = True) -> list[str]:
    branch = "└── " if is_last else "├── "
    lines = [f"{prefix}{branch}{entry.name}"]
    child_prefix = f"{prefix}{'    ' if is_last else '│   '}"
    children = list(entry.children)
    for idx, child in enumerate(children):
        lines.extend(
            _format_tree_entry(child, prefix=child_prefix, is_last=idx == len(children) - 1)
        )
    return lines


def _format_tree_response(cmd: TreeTool, result) -> str:
    root = result.root
    if not root.name:
        body = "."
    else:
        lines = [root.name]
        children = list(root.children)
        for idx, child in enumerate(children):
            lines.extend(_format_tree_entry(child, is_last=idx == len(children) - 1))
        body = "\n".join(lines)

    root_arg = cmd.root or "/"
    level_arg = f" -L {cmd.level}" if cmd.level > 0 else ""
    return _render_command(f"tree{level_arg} {root_arg}", body)


def _format_list_response(cmd: ListTool, result) -> str:
    if not result.entries:
        body = "."
    else:
        body = "\n".join(
            f"{entry.name}/" if entry.is_dir else entry.name for entry in result.entries
        )
    return _render_command(f"ls {cmd.path}", body)


def _format_read_response(cmd: ReadTool, result) -> str:
    if cmd.start_line > 0 or cmd.end_line > 0:
        start = cmd.start_line if cmd.start_line > 0 else 1
        end = cmd.end_line if cmd.end_line > 0 else "$"
        command = f"sed -n '{start},{end}p' {cmd.path}"
    elif cmd.number:
        command = f"cat -n {cmd.path}"
    else:
        command = f"cat {cmd.path}"
    return _render_command(command, result.content)


def _format_search_response(cmd: SearchTool, result) -> str:
    root = shlex.quote(cmd.root or "/")
    pattern = shlex.quote(cmd.pattern)
    body = "\n".join(
        f"{match.path}:{match.line}:{match.line_text}" for match in result.matches
    )
    return _render_command(f"rg -n --no-heading -e {pattern} {root}", body)


def _format_result(cmd: BaseModel, result) -> str:
    """Format a gRPC result as shell-like plaintext, with JSON fallback."""
    if result is None:
        return "{}"
    if isinstance(cmd, TreeTool):
        return _format_tree_response(cmd, result)
    if isinstance(cmd, ListTool):
        return _format_list_response(cmd, result)
    if isinstance(cmd, ReadTool):
        return _format_read_response(cmd, result)
    if isinstance(cmd, SearchTool):
        return _format_search_response(cmd, result)
    return json.dumps(MessageToDict(result), indent=2)


# --- gRPC dispatch ---


def pcm_dispatcher(vm: PcmRuntimeClientSync) -> Dispatcher:
    """Create a dispatcher that routes tool calls to BitGN PCM gRPC."""

    def _dispatch(tool: PcmToolAction) -> str:
        try:
            result = _call_grpc(vm, tool)
            return _format_result(tool, result)
        except ConnectError as e:
            error_msg = f"ERROR {e.code}: {e.message}"
            print(f"  {CLI_RED}{error_msg}{CLI_CLR}")
            return error_msg

    return _dispatch


def _call_grpc(vm: PcmRuntimeClientSync, tool: PcmToolAction):
    """Map PCM tool model to gRPC call."""
    match tool:
        case TreeTool(root=root, level=level):
            return vm.tree(TreeRequest(root=root, level=level))
        case FindTool(name=name, root=root, kind=kind, limit=limit):
            return vm.find(
                FindRequest(
                    root=root,
                    name=name,
                    type=FIND_KIND_MAP[kind],
                    limit=limit,
                )
            )
        case SearchTool(pattern=pattern, limit=limit, root=root):
            return vm.search(SearchRequest(root=root, pattern=pattern, limit=limit))
        case ListTool(path=path):
            return vm.list(ListRequest(name=path))
        case ReadTool(path=path, number=number, start_line=start_line, end_line=end_line):
            return vm.read(
                ReadRequest(
                    path=path,
                    number=number,
                    start_line=start_line,
                    end_line=end_line,
                )
            )
        case ContextTool():
            return vm.context(ContextRequest())
        case WriteTool(path=path, content=content, start_line=start_line, end_line=end_line):
            return vm.write(
                WriteRequest(
                    path=path,
                    content=content,
                    start_line=start_line,
                    end_line=end_line,
                )
            )
        case DeleteTool(path=path):
            return vm.delete(DeleteRequest(path=path))
        case MkDirTool(path=path):
            return vm.mk_dir(MkDirRequest(path=path))
        case MoveTool(from_name=from_name, to_name=to_name):
            return vm.move(MoveRequest(from_name=from_name, to_name=to_name))
        case PcmReportCompletion(message=message, grounding_refs=refs, outcome=outcome):
            return vm.answer(
                AnswerRequest(
                    message=message,
                    outcome=OUTCOME_BY_NAME[outcome],
                    refs=refs,
                )
            )
        case _:
            raise ValueError(f"Unknown PCM tool type: {type(tool)}")
