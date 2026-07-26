"""Verified system Hello World facade for the default immutable executor."""

from __future__ import annotations

from typing import Any

from .identity import _MODULES

_MODULE = _MODULES["identity_hello_world"]

HELLO_WORLD_AMOUNT_WEA = _MODULE.HELLO_WORLD_AMOUNT_WEA
Agent0HelloWorldDecision = _MODULE.Agent0HelloWorldDecision
HelloWorldError = _MODULE.HelloWorldError
HelloWorldMintUse = _MODULE.HelloWorldMintUse
HelloWorldRecord = _MODULE.HelloWorldRecord
HelloWorldState = _MODULE.HelloWorldState
HelloWorldSubmission = _MODULE.HelloWorldSubmission
HelloWorldTransition = _MODULE.HelloWorldTransition
MintIntent = _MODULE.MintIntent
SystemHelloWorldContract = _MODULE.SystemHelloWorldContract


def accept_unique_hello_world(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.accept_unique_hello_world(*args, **kwargs)


def create_agent0_hello_world_decision(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.create_agent0_hello_world_decision(*args, **kwargs)


def create_hello_world_submission(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.create_hello_world_submission(*args, **kwargs)


def restore_v1_hello_world(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.restore_v1_hello_world(*args, **kwargs)


__all__ = [
    "HELLO_WORLD_AMOUNT_WEA",
    "Agent0HelloWorldDecision",
    "HelloWorldError",
    "HelloWorldMintUse",
    "HelloWorldRecord",
    "HelloWorldState",
    "HelloWorldSubmission",
    "HelloWorldTransition",
    "MintIntent",
    "SystemHelloWorldContract",
    "accept_unique_hello_world",
    "create_agent0_hello_world_decision",
    "create_hello_world_submission",
    "restore_v1_hello_world",
]
