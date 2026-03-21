"""Pydantic models for BitGN sandbox agent tools and structured output."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from annotated_types import Ge, Le, MaxLen, MinLen
from pydantic import BaseModel, Field

# --- Tool models ---


class OutlineTool(BaseModel):
    tool: Literal["outline"]
    path: str = Field(default="/", description="folder path to outline")


class ReadTool(BaseModel):
    tool: Literal["read"]
    path: str


class ListTool(BaseModel):
    tool: Literal["list"]
    path: str


class SearchTool(BaseModel):
    tool: Literal["search"]
    pattern: str
    count: Annotated[int, Ge(1), Le(10)] = 5
    path: str = "/"


class WriteTool(BaseModel):
    tool: Literal["write"]
    path: str
    content: str


class DeleteTool(BaseModel):
    tool: Literal["delete"]
    path: str


class ReportCompletion(BaseModel):
    tool: Literal["report_completion"]
    completed_steps_laconic: list[str]
    answer: str
    refs: list[str] = Field(default_factory=list)
    code: Literal["completed", "failed"]


ToolAction = Union[
    OutlineTool,
    ReadTool,
    ListTool,
    SearchTool,
    WriteTool,
    DeleteTool,
    ReportCompletion,
]


# --- Agent step model ---


class NextStep(BaseModel):
    current_state: str
    plan_remaining_steps_brief: Annotated[list[str], MinLen(1), MaxLen(5)] = Field(
        ...,
        description="brief plan: what steps remain to accomplish the task",
    )
    task_completed: bool
    function: ToolAction = Field(..., description="execute the first remaining step")
