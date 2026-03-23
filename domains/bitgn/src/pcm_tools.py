"""Dispatch Pydantic tool models to BitGN PCM gRPC runtime."""

import json

from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import (
    AnswerRequest,
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

from src.pcm_models import (
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


def pcm_dispatcher(vm: PcmRuntimeClientSync) -> Dispatcher:
    """Create a dispatcher that routes tool calls to BitGN PCM gRPC."""

    def _dispatch(tool: PcmToolAction) -> str:
        try:
            result = _call_grpc(vm, tool)
            mapped = MessageToDict(result)
            return json.dumps(mapped, indent=2)
        except ConnectError as e:
            error_msg = f"ERROR {e.code}: {e.message}"
            print(f"  {CLI_RED}{error_msg}{CLI_CLR}")
            return error_msg

    return _dispatch


def _call_grpc(vm: PcmRuntimeClientSync, tool: PcmToolAction):
    """Map PCM tool model to gRPC call."""
    match tool:
        case TreeTool(root=root):
            return vm.tree(TreeRequest(root=root))
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
        case ReadTool(path=path):
            return vm.read(ReadRequest(path=path))
        case WriteTool(path=path, content=content):
            return vm.write(WriteRequest(path=path, content=content.rstrip("\n")))
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
