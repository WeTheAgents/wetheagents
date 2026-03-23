"""Pydantic models for BitGN PCM runtime tools and structured output."""

from typing import Annotated, Literal, Union

from annotated_types import Ge, Le, MaxLen, MinLen
from pydantic import BaseModel, Field

# --- PCM tool models ---


class TreeTool(BaseModel):
    tool: Literal["tree"]
    root: str = Field(default="", description="tree root, empty means repository root")


class FindTool(BaseModel):
    tool: Literal["find"]
    name: str
    root: str = "/"
    kind: Literal["all", "files", "dirs"] = "all"
    limit: Annotated[int, Ge(1), Le(20)] = 10


class SearchTool(BaseModel):
    tool: Literal["search"]
    pattern: str
    limit: Annotated[int, Ge(1), Le(20)] = 10
    root: str = "/"


class ListTool(BaseModel):
    tool: Literal["list"]
    path: str = "/"


class ReadTool(BaseModel):
    tool: Literal["read"]
    path: str


class WriteTool(BaseModel):
    tool: Literal["write"]
    path: str
    content: str


class DeleteTool(BaseModel):
    tool: Literal["delete"]
    path: str


class MkDirTool(BaseModel):
    tool: Literal["mkdir"]
    path: str


class MoveTool(BaseModel):
    tool: Literal["move"]
    from_name: str
    to_name: str


class PcmReportCompletion(BaseModel):
    tool: Literal["report_completion"]
    completed_steps_laconic: list[str]
    message: str
    grounding_refs: list[str] = Field(default_factory=list)
    outcome: Literal[
        "OUTCOME_OK",
        "OUTCOME_DENIED_SECURITY",
        "OUTCOME_NONE_CLARIFICATION",
        "OUTCOME_NONE_UNSUPPORTED",
        "OUTCOME_ERR_INTERNAL",
    ]


PcmToolAction = Union[
    TreeTool,
    FindTool,
    SearchTool,
    ListTool,
    ReadTool,
    WriteTool,
    DeleteTool,
    MkDirTool,
    MoveTool,
    PcmReportCompletion,
]


# --- Agent step model ---


class PcmNextStep(BaseModel):
    current_state: str
    plan_remaining_steps_brief: Annotated[list[str], MinLen(1), MaxLen(5)] = Field(
        ...,
        description="brief plan: what steps remain to accomplish the task",
    )
    task_completed: bool
    function: PcmToolAction = Field(..., description="execute the first remaining step")
