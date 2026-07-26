from __future__ import annotations

import hashlib

import pytest

from wea_vnext.engine import installed_executor
from wea_vnext.hello_world import HelloWorldError, SystemHelloWorldContract


def test_s_09c_fails_closed_until_canonical_issue_snapshot_is_installed() -> None:
    runtime = installed_executor("0.6.1").reference
    body = "Submit mechanically unique Work."

    with pytest.raises(HelloWorldError, match="canonical Issue #1 snapshot"):
        SystemHelloWorldContract(
            contract_id="contract-system-hello-world",
            issue_id="caller-supplied-issue-id",
            issue_number=1,
            body=body,
            body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            ruleset_hash=runtime.ruleset_hash,
            tide_interface_version=runtime.tide_interface_version,
            executor_manifest_hash=runtime.executor_manifest_hash,
        )
