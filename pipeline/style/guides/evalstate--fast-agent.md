# Style Guide: evalstate/fast-agent

Reverse-engineered from codebase analysis, commit history, and merged PR reviews. Intended for contributors writing PRs that will pass evalstate's review on the first try.

---

## 1. Imports

**Ordering** (enforced by ruff rule `I`):
1. Standard library (`import os`, `import asyncio`, `from contextlib import ...`)
2. Third-party (`from mcp import ...`, `from pydantic import ...`, `from anyio import ...`)
3. Local (`from fast_agent.config import ...`, `from fast_agent.core.logging.logger import ...`)

**Blank lines**: One blank line between each group. No blank lines within a group.

**TYPE_CHECKING block**: Always placed LAST in the import section, after all runtime imports. Used to break circular dependencies. Contents imported as string annotations:

```python
if TYPE_CHECKING:
    from fast_agent.context import Context
    from fast_agent.mcp_server_registry import ServerRegistry
```

**Multi-import style**: evalstate uses parenthesized multi-line imports for long import lists:
```python
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Mapping,
    TypeVar,
    Union,
    cast,
)
```

**Never import `logging` directly** for application logging. Always use:
```python
from fast_agent.core.logging.logger import get_logger
logger = get_logger(__name__)
```

The only place stdlib `logging` appears is inside logging filter classes where it is needed for the filter API itself (see `_suppress_mcp_sse_errors`).

---

## 2. Type Annotations

**Union syntax**: Always use `X | None`, never `Optional[X]`. This is Python 3.10+ syntax and the entire codebase is consistent.

```python
# DO
server_name: str | None = None
error_message: str | None = None

# DON'T
server_name: Optional[str] = None
```

**Return type annotations**: Always annotated on public methods. `-> None` is explicitly written:
```python
async def close(self) -> None:
async def load_servers(self, *, force_connect: bool = False) -> None:
def get_server_config(self, server_name: str) -> MCPServerSettings | None:
```

**Generic types**: Use `dict[str, X]`, `list[str]`, `tuple[str, ...]` (lowercase built-in generics), not `Dict`, `List`, `Tuple`.

**Callable signatures**: When a callable type appears in more than one signature, evalstate extracts a named `Protocol` rather than repeating inline `Callable[...]`:
```python
# DO — named protocol (evalstate's preferred style as of v0.6.6+)
@runtime_checkable
class ClientSessionFactory(Protocol):
    def __call__(
        self,
        read_stream: MemoryObjectReceiveStream,
        write_stream: MemoryObjectSendStream,
        read_timeout: timedelta | None,
        *,
        server_config: "MCPServerSettings | None" = None,
        transport_metrics: "TransportChannelMetrics | None" = None,
    ) -> ClientSession: ...

# Then use it:
client_session_factory: ClientSessionFactory | None = None

# DON'T — inline Callable repeated across multiple signatures
client_session_factory: Callable[
    [MemoryObjectReceiveStream, MemoryObjectSendStream, timedelta | None],
    ClientSession,
]
```
For one-off callables that appear in a single signature, inline `Callable[...]` is still acceptable.

**cast()**: Used sparingly and only when necessary. Imports from `typing`:
```python
server_registry = cast("ServerRegistry", self._require_server_registry())
```

---

## 3. Logging

**Logger initialization**: Module-level, right after imports:
```python
logger = get_logger(__name__)
```

Some modules override the logger per-instance (see MCPAggregator's `__init__`):
```python
logger_name = f"{__name__}.{name}" if name else __name__
logger = get_logger(logger_name)
```

**String format**: f-strings dominate (43 instances in mcp_aggregator.py). %-format is rare (1 instance). Use f-strings.

**Level conventions observed**:
- `logger.debug()` -- internal state, skipping optional steps, capability checks, fallback paths
- `logger.info()` -- connection events, initialization milestones, reconnection, structured progress payloads
- `logger.warning()` -- ping failures, Skybridge mismatches, degraded functionality
- `logger.error()` -- tool loading failures, cleanup errors, invalid configurations

**Structured data**: The custom logger supports a `data=` keyword argument for structured payloads:
```python
logger.info(
    f"Creating persistent connection to server: {server_name}",
    data={
        "progress_action": ProgressAction.CONNECTING,
        "server_name": server_name,
        "agent_name": self.agent_name,
    },
)
```

**exc_info=True**: Used with `logger.error()` and `logger.debug()` when you want the traceback:
```python
logger.error(f"Error in tool progress handler: {e}", exc_info=True)
logger.debug("transport metrics hook failed", server_name, exc_info=True)
```

**Error message format**: Server-related errors consistently include the server name:
- `f"Server '{server_name}' not found in registry."`
- `f"Error loading tools from server '{server_name}'"`
- `f"{server_name}: Lifecycle task encountered an error: {exc}"`

Two patterns: quoted name in parenthetical (`Server '{name}'`) and prefix style (`{name}: message`). The prefix style (no quotes) is used in the connection manager for lifecycle events. The quoted style is used in the aggregator for registry lookups.

---

## 4. Error Handling

**Specific exceptions first**: ConnectionError and ServerSessionTerminatedError are caught before generic Exception:
```python
except ConnectionError:
    raise
except ServerSessionTerminatedError:
    raise
except Exception as e:
    logger.error(error_msg)
    if error_factory:
        return error_factory(error_msg)
    raise e
```

**Broad except with noqa**: When catching all exceptions is intentional, always add `# noqa: BLE001` with a reason:
```python
except Exception as exc:  # noqa: BLE001 - logging and surfacing gracefully
```

**Custom exceptions**: Inherit from `FastAgentError(message, details)`. The two-part structure separates the user-facing message from technical details:
```python
raise ServerInitializationError(
    f"MCP Server: '{server_name}': Failed to start stdio server.",
    formatted_error,
)
```

**Error message format for ServerInitializationError**: Always `MCP Server: '{name}': <what failed>.`

**Defensive guards**: Use `# pragma: no cover` for defensive code paths that are unlikely to execute:
```python
except Exception:  # pragma: no cover - defensive guard
    logger.debug(...)
```

**Never raise bare Exception**. Always use a specific type (ValueError, RuntimeError, or a custom FastAgentError subclass).

---

## 5. Class Design

**BaseModel vs dataclass**:
- `BaseModel` (Pydantic): For classes that need validation, serialization, or JSON schema (ServerStatus, NamespacedTool, MCPAggregator itself)
- `@dataclass`: For simple containers. Use `frozen=True, slots=True` for immutable value objects:
```python
@dataclass(frozen=True, slots=True)
class MCPAttachOptions:
    startup_timeout_seconds: float = 10.0
    trigger_oauth: bool = True
```

**model_config**: When a Pydantic model needs special config:
```python
model_config = ConfigDict(arbitrary_types_allowed=True)
model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
```

**ContextDependent mixin**: Classes that need application context inherit from `ContextDependent`:
```python
class MCPAggregator(ContextDependent):
class MCPConnectionManager(ContextDependent):
```

**_require_ pattern**: Private methods that enforce prerequisites and raise RuntimeError:
```python
def _require_context(self) -> "Context":
    if self.context is None:
        raise RuntimeError("MCPAggregator requires a context")
    return self.context

def _require_server_registry(self) -> ServerRegistryProtocol:
def _require_connection_manager(self) -> MCPConnectionManager:
```

**Protocol classes**: Used in `interfaces.py` for dependency inversion. Decorated with `@runtime_checkable`:
```python
@runtime_checkable
class MCPConnectionManagerProtocol(Protocol):
    """Protocol for MCPConnectionManager functionality needed by ServerRegistry."""
```

---

## 6. Naming

**Private methods**: Single underscore `_foo`. Never double underscore. Examples:
- `_create_session_factory`
- `_fetch_server_tools`
- `_execute_on_server`
- `_reset_runtime_indexes`
- `_display_startup_state`

**Private attributes**: Single underscore:
- `self._namespaced_tool_map`
- `self._persistent_connection_manager`
- `self._owns_connection_manager`

**Constants**: Module-level UPPER_SNAKE:
```python
SESSION_NOT_FOUND_ERROR_CODE = -32043
LEGACY_SESSION_REQUIRED_ERROR_CODE = -32002
SEP = "."
```

**Test helper classes**: Prefixed with underscore to signal they are test-internal:
```python
class _DummyRegistry:
class _RecordingAggregator(MCPAggregator):
class _SessionStub:
class _ManagerStub:
class _FallbackAggregator(MCPAggregator):
```

**Helper functions in tests**: Also underscore-prefixed:
```python
def _build_context(configs: dict[str, MCPServerSettings]) -> Context:
def _make_server_connection() -> ServerConnection:
```

---

## 7. Docstrings

**Public methods**: Google-style docstrings with Args/Returns/Raises sections:
```python
def get_server_config(self, server_name: str) -> MCPServerSettings | None:
    """
    Get the configuration for a specific server.

    Args:
        server_name (str): The name of the server.

    Returns:
        MCPServerSettings: The server configuration.
    """
```

**Private methods**: Docstrings are optional. When present, they are terse one-liners:
```python
async def _reset_runtime_indexes(self) -> None:
    # (no docstring)

def _display_startup_state(self, total_tool_count: int, total_prompt_count: int) -> None:
    """Display startup summary and Skybridge status information."""
```

**Module-level docstrings**: Present on interface files and major modules:
```python
"""
Interface definitions to prevent circular imports.
This module defines protocols (interfaces) that can be used to break circular dependencies.
"""
```

**Class docstrings**: Present on all classes, typically one or two lines:
```python
class MCPAggregator(ContextDependent):
    """
    Aggregates multiple MCP servers. When a developer calls, e.g. call_tool(...),
    the aggregator searches all servers in its list for a server that provides that tool.
    """
```

---

## 8. Async Patterns

**Context managers**: Class-based with explicit `__aenter__`/`__aexit__`:
```python
async def __aenter__(self):
    ...
    return self

async def __aexit__(self, exc_type, exc_val, exc_tb):
    await self.close()
```

**Lock usage**: `anyio.Lock()` (not `asyncio.Lock`) used for thread-safe async operations:
```python
from anyio import Lock
self._lock = Lock()

async with self._lock:
    server_conn = self.running_servers.get(server_name)
```

Exception: `asyncio.Lock` is used in the aggregator's `__init__` (line 3), but `anyio.Lock` elsewhere.

**Task groups**: anyio `create_task_group()` for managing concurrent server lifecycles:
```python
from anyio import create_task_group
self._task_group = create_task_group()
self._tg.start_soon(_server_lifecycle_task, server_conn)
```

**Shutdown pattern**: Event-based signaling with `anyio.Event`:
```python
self._initialized_event = Event()
self._shutdown_event = Event()
```

---

## 9. Testing Patterns

**pytest marker**: `@pytest.mark.asyncio` required on every async test (strict mode):
```python
@pytest.mark.asyncio
async def test_server_lifecycle_sets_initialized_on_startup_failure():
```

**Sync tests**: No marker needed. Many tests are sync when they don't need async:
```python
def test_prepare_headers_respects_user_authorization(monkeypatch):
def test_list_configured_detached_servers_includes_registry_entries() -> None:
```

**Return type on tests**: Some tests have `-> None`, some don't. Both are accepted. Follow existing pattern in the file you're modifying.

**Fixtures**: Prefer `monkeypatch` for patching. The global `conftest.py` has an `autouse` fixture that isolates the environment directory.

**Inline helper classes**: Tests define small stub/mock classes inline rather than using complex mock setups:
```python
class DummyTransportContext:
    async def __aenter__(self):
        return object(), object(), None
    async def __aexit__(self, exc_type, exc, tb):
        return None

class DummySession:
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return None
    async def initialize(self):
        raise RuntimeError("boom")
```

**Assertion style**: Plain `assert` statements. No assertEqual, no assertIn:
```python
assert server_conn._error_occurred is True
assert "demo" not in manager.running_servers
assert headers == {"Authorization": "Bearer user-token"}
```

**Test naming**: `test_<what_it_tests>` -- descriptive, snake_case, sometimes long:
```python
test_startup_timeout_budget_excludes_oauth_wait_window
test_get_server_formats_stdio_missing_executable_without_traceback
test_fetch_server_tools_optimistic_fallback_when_capability_missing
```

**Parametrize**: Used for validation edge cases (see test_mcp_runtime_handlers.py for nan/inf/0/-1 testing).

**No unittest.mock.patch**: Tests use `monkeypatch.setattr()` instead.

---

## 10. PR Conventions

**PR body structure**: Based on analysis of merged external PRs (iqdoctor, phucly95, yarisoy):

```
## Summary
- bullet point 1
- bullet point 2

## Problem
Description of the bug or missing feature.

## Change
**`path/to/file.py`**
- what changed and why

## Verification
- `uv run pytest tests/unit/... -q`
- `uv run ruff check path/to/changed/files`
```

**What evalstate looks for in reviews**:
- He reads the code carefully and sometimes commits additional tests/fixes directly to the contributor's branch (see PR #729 where he cherry-picked a commit)
- He values concise, well-scoped changes. His comment on PR #679: "LOL, you were quick on that one" -- speed and precision are appreciated
- He rarely leaves style nits in reviews. If the code works and is well-tested, he merges
- He has never requested formatting changes on any analyzed PR -- the CI handles that

**Merge strategy**: Squash merge for external PRs (PR number appended to commit title). His own feature branches sometimes use merge commits.

**Commit message**: No strict conventional-commit requirement. External PRs use `fix:`, `feat:`, `chore:` prefixes with optional scope. evalstate's own commits are freeform ("version bump", "commit local", "modernize tests"). For our PRs, use conventional format with scope: `fix(mcp): ...`

---

## 11. Specific Patterns in mcp_aggregator.py

**_execute_on_server**: The central dispatch method. All tool/prompt/resource calls go through it. Takes `method_name` as string, `method_args` as dict, and optional `error_factory` and `progress_callback`. When adding new operations, follow this pattern.

**Reconnection pattern**: ConnectionError and ServerSessionTerminatedError are caught at the _execute_on_server level, then dispatched to `_handle_connection_error` / `_handle_session_terminated`. Do not add reconnection logic elsewhere.

**Feature capability check**: Always goes through `server_supports_feature()` which calls `get_capabilities()`. The capability check returns False for non-persistent connections.

**gen_client**: The lightweight alternative to persistent connections. Used via `async with gen_client(server_name, server_registry=server_registry) as client:`. Creates a temporary connection, yields a ClientSession, cleans up on exit.

---

## 12. Things to Absolutely Avoid

1. **Do not use `Optional[X]`** -- always `X | None`
2. **Do not use `logging.getLogger()`** -- always `get_logger(__name__)`
3. **Do not use `__double_underscore` private methods** -- always `_single_underscore`
4. **Do not use `unittest.mock.patch()`** -- use `monkeypatch.setattr()`
5. **Do not forget `@pytest.mark.asyncio`** on async tests -- strict mode will fail silently
6. **Do not add `# type: ignore`** -- fix the type issue or discuss with the type checker
7. **Do not exceed 100 chars per line** (though E501 is ignored by ruff, the codebase still generally stays under 100)
8. **Do not create documentation files** unless explicitly requested
9. **Do not use `Dict`, `List`, `Tuple`, `Set`** from typing -- use lowercase built-in generics
10. **Do not bundle unrelated changes** in a single PR

---

## 13. File Headers

No license headers in source files. No `#!/usr/bin/env python` shebangs. Files start directly with docstrings or imports.

---

*Part 1 produced by code-stylist for the W-E-A dominion pipeline. Source: codebase analysis of evalstate/fast-agent at commit 4866bdd, plus 10 merged PRs from external contributors.*

---

# Part 2: Architecture & Design Patterns

Part 1 documented how evalstate writes individual lines. Part 2 documents how he thinks -- class organization, control flow philosophy, resource lifecycle, and the design instincts behind architectural decisions across 3000+ lines of core MCP code.

---

## 1. Class Organization

### Method ordering within MCPAggregator (~2300 lines)

evalstate orders methods in a consistent four-band layout:

1. **Data model / field declarations** (lines 200-209) -- class-level fields with docstrings come first, before any methods.
2. **Lifecycle methods** -- `__aenter__`, `__aexit__`, `__init__`, `close()`, factory `create()`. The async context manager is defined BEFORE `__init__`. This is unusual but deliberate: the lifecycle contract is the first thing a reader encounters.
3. **Private infrastructure** -- `_require_*` guards, `_create_session_factory`, `_reset_runtime_indexes`, then feature-grouped private methods (`_fetch_server_tools`, `_fetch_server_prompts`, `_evaluate_skybridge_for_server`).
4. **Public API** -- `call_tool`, `get_prompt`, `list_resources`, `complete`, exposed in the order a user would discover them. Each public method follows the same pattern: check `self.initialized`, parse the resource name, then delegate to `_execute_on_server`.

**Within each band**, methods are grouped by feature, not alphabetically. Tool-related methods (`call_tool`, `list_tools`, `refresh_all_tools`, `_refresh_server_tools`, `_handle_tool_list_changed`) cluster together. Prompt-related methods cluster together. Resource-related methods cluster together.

**DO**: Group methods by feature/concern. Place lifecycle at the top, public API at the bottom.
**DON'T**: Alphabetize methods. Don't scatter related methods across the file.

**evalstate would...** expect our fix for issue #405 to place any new private helper next to the existing `_execute_on_server` method family, not at the end of the file.

### Method ordering within MCPConnectionManager (~600 lines)

Same four-band pattern, smaller scale:
1. `__init__`, `__aenter__`, `__aexit__` (lifecycle)
2. Private methods: `_suppress_mcp_sse_errors`, `_suppress_mcp_streamable_http_errors`, `_build_oauth_event_handler` (infrastructure)
3. `launch_server`, `_launch_and_wait_for_server` (private workhorse + public entry)
4. `get_server`, `get_server_capabilities`, `disconnect_server`, `reconnect_server`, `disconnect_all` (public API)

### Helper classes: top-of-file, before the main class

`NamespacedTool`, `ServerStats`, `ServerStatus`, `MCPAttachOptions`, `MCPAttachResult`, `MCPDetachResult` are ALL defined above `MCPAggregator`. Similarly, `StreamingContextAdapter`, `ServerConnection`, and free functions like `_prepare_headers_and_auth` are defined above `MCPConnectionManager`.

**DO**: Put helper/support classes and free functions ABOVE the main class. The reader encounters data structures before behavior.
**DON'T**: Define helper classes inside the main class or at the bottom of the file.

---

## 2. Initialization Patterns

### Two-phase init: construct, then async-initialize

evalstate uses a strict two-phase initialization pattern across all major classes:

**Phase 1 -- `__init__`**: Synchronous. Sets all fields to safe defaults. No I/O. No network. No filesystem. The object exists but is inert.

```python
# MCPAggregator.__init__ sets:
self.initialized = False
self._persistent_connection_manager = None
self._owns_connection_manager = False
self._namespaced_tool_map = {}
self._server_to_tool_map = {}
# ... all locks, all caches, all empty collections
```

**Phase 2 -- `__aenter__`**: Async. Acquires resources, connects to servers, loads tools. The object becomes alive.

```python
async def __aenter__(self):
    if self.initialized:
        return self          # idempotent re-entry guard
    if self.connection_persistence:
        context = self._require_context()
        # ... create/reuse connection manager
    await self.load_servers()
    return self
```

The `create()` classmethod provides a third option -- a factory that combines construction and initialization in one call but wraps cleanup on failure:

```python
@classmethod
async def create(cls, ...) -> "MCPAggregator":
    instance = cls(...)
    try:
        await instance.__aenter__()
        await instance.load_servers()
        return instance
    except Exception as e:
        await instance.__aexit__(None, None, None)
        raise
```

### State guards: the `_require_*` family

After two-phase init, some fields are None until phase 2 completes. evalstate handles this with `_require_*` methods that are BOTH a null-check AND a type-narrowing cast:

```python
def _require_context(self) -> "Context":
    if self.context is None:
        raise RuntimeError("MCPAggregator requires a context")
    return self.context

def _require_server_registry(self) -> ServerRegistryProtocol:
    context = self._require_context()          # chains: require context first
    server_registry = getattr(context, "server_registry", None)
    if server_registry is None:
        raise RuntimeError("Context is missing server registry for MCP connections")
    return server_registry

def _require_connection_manager(self) -> MCPConnectionManager:
    if self._persistent_connection_manager is None:
        raise RuntimeError("Persistent connection manager is not initialized")
    return self._persistent_connection_manager
```

Notice: `_require_server_registry` chains through `_require_context`. The `_require_*` methods compose. The caller never needs to null-check -- they call `_require_*` and either get a guaranteed non-None value or the method raises.

### Idempotent re-entry

`__aenter__` checks `self.initialized` and returns early if already initialized. `load_servers` does the same. This makes it safe to call these methods multiple times.

**DO**: Always provide `_require_*` methods for fields that are None before async init. Return the typed value so the caller never needs `assert` or `cast`.
**DON'T**: Use `assert self.context is not None` inline. Don't use `if self.context is None: return` (silent failure). Always raise RuntimeError with a descriptive message.

---

## 3. Control Flow Philosophy

### Guard clauses: aggressive early returns

evalstate uses early returns aggressively, especially at the tops of methods. Examples from the aggregator:

```python
async def load_servers(self, *, force_connect: bool = False) -> None:
    if self.initialized and not force_connect:
        logger.debug("MCPAggregator already initialized.")
        return
    # ... rest of method

async def get_capabilities(self, server_name: str):
    if not self.connection_persistence:
        return None                              # fast path for non-persistent
    # ... persistent path

async def get_server_instructions(self) -> dict:
    if not self.connection_persistence:
        return instructions                      # early exit: nothing to read
    manager = getattr(self, "_persistent_connection_manager", None)
    if manager is None:
        return instructions                      # early exit: not initialized
    # ... main logic
```

### Nesting depth: controlled but not minimal

evalstate does NOT obsessively flatten all nesting. The `_server_lifecycle_task` function reaches 5-6 levels of nesting, and that is accepted because the nesting mirrors the resource ownership hierarchy (transport context > session context > initialization > ping loop). The `collect_server_status` method has deep nesting for building status objects, and that too is accepted.

But evalstate avoids GRATUITOUS nesting. When a method has an early exit condition, it returns immediately rather than wrapping the entire body in an if-block.

**The rule**: Nesting is acceptable when it reflects resource scope or ownership. Nesting is unacceptable when it is just an inverted guard clause.

### The connection_persistence fork

Throughout the aggregator, `self.connection_persistence` creates a structural fork. The pattern is always if/else, never strategy pattern, never polymorphism:

```python
# _execute_on_server: the central dispatch
if self.connection_persistence:
    manager = self._require_connection_manager()
    server_connection = await manager.get_server(...)
    session = server_connection.session
    result = await try_execute(session)
else:
    server_registry = self._require_server_registry()
    async with gen_client(server_name, server_registry=server_registry) as client:
        result = await try_execute(client)
```

This pattern repeats in `_handle_connection_error`, `_handle_session_terminated`, `get_capabilities`, and `get_server_instructions`. Each time, the persistent path goes through the connection manager, and the non-persistent path goes through `gen_client`.

evalstate chose if/else over strategy pattern because:
- There are exactly two cases, ever. No third mode.
- The two paths are structurally different (context manager vs direct call).
- The fork appears in ~6 places -- enough to notice, not enough to warrant a class hierarchy.

**DO**: Use if/else for a two-way behavioral fork. Name the boolean clearly (`connection_persistence`).
**DON'T**: Create an abstract base class and two subclasses for a boolean toggle. Don't hide the fork in a method that returns different callable types.

**evalstate would...** reject a PR that introduces `PersistentExecutor` and `TemporaryExecutor` classes. He would accept a PR that extracts `_execute_persistent` and `_execute_temporary` private methods if the fork code grew too long, but the dispatch would remain in `_execute_on_server` as if/else.

---

## 4. Strategy Patterns (When evalstate DOES use abstraction)

### Handlers: interface + no-op default

For cross-cutting concerns (tool execution events, tool permissions), evalstate uses a handler interface with a no-op default implementation:

```python
# Constructor resolution chain:
resolved_tool_handler = tool_handler
if resolved_tool_handler is None and context is not None:
    acp_ctx = getattr(context, "acp", None)
    resolved_tool_handler = getattr(acp_ctx, "progress_manager", None) or None
self._tool_handler = resolved_tool_handler or NoOpToolExecutionHandler()
```

The pattern: try the explicit argument, then try context, then fall back to no-op. The no-op ensures callers never need to null-check before calling handler methods.

### Protocol classes: minimal and prescriptive

`interfaces.py` defines three protocols, each with the minimum surface area:

- `MCPConnectionManagerProtocol`: 3 methods (`get_server`, `disconnect_server`, `disconnect_all_servers`)
- `ServerRegistryProtocol`: 2 properties + 2 methods
- `ServerConnection`: 1 property (`session`)

Protocols are `@runtime_checkable` so they work with `isinstance()`. They describe what the consumer NEEDS, not what the provider HAS.

`ServerRegistry` (the concrete class) is 90 lines. It does NOT inherit from `ServerRegistryProtocol`. It satisfies the protocol structurally. evalstate prefers structural typing (duck typing with Protocol) over nominal inheritance.

**DO**: Define protocols for what the consumer needs. Keep them minimal. Use `@runtime_checkable`.
**DON'T**: Make concrete classes inherit from their own protocol. Don't put implementation logic in protocol files. Don't create protocols with 10+ methods.

---

## 5. Error Propagation Architecture

evalstate uses a layered catch/raise/propagate strategy. The layers, from innermost to outermost:

### Layer 1: `try_execute` (inside `_execute_on_server`)
```python
async def try_execute(client: ClientSession):
    try:
        method = getattr(client, method_name)
        result = await method(**kwargs)
        return result
    except ConnectionError:
        raise                                     # pass-through for reconnection
    except ServerSessionTerminatedError:
        raise                                     # pass-through for reconnection
    except Exception as e:
        if error_factory:
            return error_factory(error_msg)       # catch-and-return
        raise e                                   # catch-and-reraise
```

### Layer 2: `_execute_on_server` (the dispatch)
```python
try:
    if self.connection_persistence:
        result = await try_execute(session)
    else:
        async with gen_client(...) as client:
            result = await try_execute(client)
except ConnectionError:
    result, success_flag = await self._handle_connection_error(...)
except ServerSessionTerminatedError as exc:
    result, success_flag = await self._handle_session_terminated(...)
except Exception:
    success_flag = False
    raise
finally:
    if success_flag is not None:
        await self._record_server_call(server_name, operation_type, success_flag)
```

### Layer 3: `_handle_connection_error` / `_handle_session_terminated`
These try reconnection once. On failure, they either use `error_factory` (catch-and-return) or raise a new exception. They NEVER attempt a second reconnection -- explicit infinite-loop prevention.

### Layer 4: `_server_lifecycle_task` (connection manager)

The docstring says it all: "This function must NEVER raise an exception, as it runs in a shared task group." All exceptions are caught and recorded as state:

```python
except Exception as exc:
    server_conn._error_occurred = True
    server_conn._error_message = ...
    server_conn._initialized_event.set()       # unblock waiters
    # No raise - allow graceful exit
```

### The error_factory pattern

`error_factory` is an optional callable passed to `_execute_on_server`. When present, exceptions become return values instead of raised errors. This is critical for tool calls, where the MCP protocol expects a `CallToolResult(isError=True)` rather than an exception:

```python
error_factory=lambda msg: CallToolResult(
    isError=True, content=[TextContent(type="text", text=msg)]
)
```

When `error_factory` is None, exceptions propagate. This dual mode means `_execute_on_server` supports both "return errors as values" (for user-facing operations) and "raise exceptions" (for internal operations like `list_tools`).

**DO**: Use `error_factory` for operations where the caller expects an error-as-value. Let exceptions propagate for internal operations.
**DON'T**: Catch and swallow exceptions. Don't catch `Exception` without `# noqa: BLE001` and a reason. Don't attempt more than one reconnection in error handlers.

---

## 6. Resource Lifecycle

### Ownership rule: whoever creates it, closes it

`MCPAggregator.__aenter__` may create a `MCPConnectionManager`:
```python
if not hasattr(context, "_connection_manager") or context._connection_manager is None:
    manager = MCPConnectionManager(server_registry, context=context)
    await manager.__aenter__()
    context._connection_manager = manager
    self._owns_connection_manager = True          # ownership flag
```

And `close()` only shuts down the connection manager if it owns it:
```python
if self._owns_connection_manager and (
    hasattr(self.context, "_connection_manager")
    and self.context._connection_manager == self._persistent_connection_manager
):
    await self._persistent_connection_manager.disconnect_all()
    await self._persistent_connection_manager.__aexit__(None, None, None)
    delattr(self.context, "_connection_manager")
```

### TaskGroup lifecycle in MCPConnectionManager

The connection manager owns an `anyio.create_task_group()` that outlives any individual server connection:

```python
async def __aenter__(self):
    self._task_group = create_task_group()
    await self._task_group.__aenter__()
    self._task_group_active = True
    return self

async def __aexit__(self, exc_type, exc_val, exc_tb):
    try:
        await self.disconnect_all()
        with suppress(asyncio.CancelledError):
            await asyncio.sleep(0.5)             # brief delay for clean shutdown
        if self._task_group_active:
            await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
            self._task_group_active = False
    except Exception:
        logger.exception("Error during connection manager shutdown")
```

Server connections live inside this task group. When `launch_server` creates a `ServerConnection`, it spawns a task in the shared group:
```python
self._tg.start_soon(_server_lifecycle_task, server_conn)
```

When `disconnect_server` is called, it signals shutdown via `server_conn.request_shutdown()` (sets an `anyio.Event`), and the lifecycle task exits naturally. The connection manager does NOT cancel the task -- it waits for cooperative shutdown.

### Shutdown protocol

Shutdown is cooperative, event-based, never cancellation-based:
1. `request_shutdown()` sets `_shutdown_event` and `_oauth_abort_event`
2. `_server_lifecycle_task` is awaiting `wait_for_shutdown_request()`, which unblocks
3. The task exits its `async with session:` block, triggering `__aexit__` cleanup
4. Exceptions during cleanup are caught and logged as debug (expected during shutdown)

**DO**: Use `_shutdown_event.set()` for cooperative shutdown. Track ownership with boolean flags. Use `suppress(asyncio.CancelledError)` in cleanup.
**DON'T**: Cancel tasks directly. Don't assume `__aexit__` succeeds during shutdown. Don't forget to set the initialized event on error (prevents hanging waiters).

---

## 7. Protocol Design Philosophy

evalstate's protocols in `interfaces.py` follow three principles:

**Minimal**: `ServerConnection` protocol has exactly ONE property: `session`. The concrete `ServerConnection` class has 20+ attributes and methods. The protocol exposes only what `gen_client` needs.

**Consumer-oriented**: `ServerRegistryProtocol` has the methods `gen_client` calls. It does NOT include `load_registry_from_file()` which exists on the concrete class but no consumer needs through the protocol.

**Structurally satisfied**: No concrete class inherits from its protocol. `ServerRegistry` satisfies `ServerRegistryProtocol` by having the right methods/properties. `MCPConnectionManager` satisfies `MCPConnectionManagerProtocol` the same way. This keeps the dependency graph clean: `interfaces.py` imports nothing from the concrete implementations.

**The `__all__` export list** explicitly controls the public surface of `interfaces.py`. It re-exports protocols from `fast_agent.interfaces` (the parent-level interface file), creating a single import point for MCP-layer consumers.

---

## 8. Test Architecture

### File organization: one test file per feature slice

Test files mirror the source structure but slice by feature, not by class:
- `test_mcp_connection_manager.py` -- tests for lifecycle, headers, OAuth detection, timeout budgets
- `test_mcp_aggregator_runtime_attach.py` -- tests for attach/detach/load_servers
- `test_mcp_aggregator_session_status.py` -- tests for `collect_server_status`
- `test_mcp_aggregator_server_instructions.py` -- tests for `get_server_instructions`

No class-level grouping. All tests are top-level functions (or occasionally class-grouped when sharing setup logic).

### Fixture patterns: global conftest + inline stubs

The global `tests/unit/conftest.py` has a single `autouse` fixture that isolates the environment directory per test. This is the ONLY shared fixture.

Test-specific setup uses inline helper functions and stub classes:

```python
def _build_context(configs: dict[str, MCPServerSettings]) -> Context:
    registry = ServerRegistry()
    registry.registry = configs
    return Context(server_registry=registry)

def _make_server_connection() -> ServerConnection:
    # ... inline DummyTransportContext, DummySession, session_factory
    return ServerConnection(...)
```

These helpers are prefixed with `_` to signal they are test-internal.

### Stub pattern: inline classes, not mocks

evalstate strongly prefers hand-written stub classes over `unittest.mock`. Typical pattern:

```python
class _ServerConnStub:
    def __init__(self, config: MCPServerSettings) -> None:
        self.server_implementation = SimpleNamespace(name="demo-server", version="0.1.0")
        self.server_capabilities = None
        # ... set every field the method under test reads

    def is_healthy(self) -> bool:
        return True
```

`SimpleNamespace` is used for deeply nested objects that need attribute access. `AsyncMock` appears only for assertions that a method was NOT called (negative tests), never as the primary interaction mechanism.

### Test naming: descriptive verb phrases

```python
test_prepare_headers_respects_user_authorization
test_server_lifecycle_sets_initialized_on_startup_failure
test_startup_timeout_budget_excludes_oauth_wait_window
test_get_server_formats_stdio_missing_executable_without_traceback
test_fetch_server_tools_optimistic_fallback_when_capability_missing
test_attach_server_registers_runtime_server_before_prompt_discovery
test_get_server_instructions_does_not_implicitly_connect
```

Pattern: `test_<method/feature>_<scenario_or_condition>`. No `test_should_*`. No BDD-style `test_when_*_then_*`. Just a direct statement of what the test verifies.

### Subclass stubs for method overrides

When testing `MCPAggregator` methods that call other aggregator methods internally, evalstate creates subclass stubs that override the called methods:

```python
class _FallbackAggregator(MCPAggregator):
    async def server_supports_feature(self, server_name, feature):
        return False
    async def _execute_on_server(self, server_name, operation_type, ...):
        return ListToolsResult(tools=[Tool(name="echo", ...)])
```

This avoids mocking framework complexity and makes the test read like a spec.

### What he tests, what he does not

**Tested**: boundary conditions (timeout budgets with OAuth windows), error propagation paths (FileNotFoundError formatting), state transitions (initialized_event set on failure), negative cases (method should NOT be called), cache behavior.

**Not tested**: UI output (console.print calls), logging content, exact string formatting of log messages.

**DO**: Use inline stub classes. Use `SimpleNamespace` for nested objects. Name tests descriptively. Test state transitions and error paths.
**DON'T**: Use `unittest.mock.patch()` for method replacement -- use `monkeypatch.setattr()`. Don't test log messages. Don't use class-level `setUp`/`tearDown`.

---

## 9. What evalstate Cares About in Review

Evidence from 18+ analyzed external PRs (iqdoctor, phucly95, yarisoy, floriafz23):

### What he merges without comments
- Clean, well-scoped single-purpose PRs with tests (PR #679, #680, #709)
- PRs that follow the existing code structure and conventions
- PRs where CI passes and the change is obviously correct

### What triggers his engagement
- **Missing coverage**: On PR #729, he co-committed additional tests and fixed an edge case the contributor missed (the non-MCP agent fallback path). He did not request changes -- he just pushed a commit to the contributor's branch.
- **Root cause accuracy**: On PR #660, he "made a small adjustment to the tool name/tracking logic" after merging. He refined the fix himself rather than sending it back.
- **False positive bugs**: PR #717 was merged quickly because it fixed a misclassification (non-OAuth errors being reported as OAuth timeouts). He values diagnostic accuracy.

### His review style
- He does NOT leave style nits. Not once in analyzed PRs did he comment on formatting, naming, or import order. CI handles that.
- He does NOT request refactoring of working code. If it works and is tested, it ships.
- He DOES co-commit. When a PR is 90% right, he pushes the remaining 10% himself rather than requesting changes. This is his signature move.
- He is warm but terse. Comments are typically one sentence: "Thanks!", "LOL, you were quick on that one.", "Thanks very much for this -- I made a small adjustment."
- He tests the PR locally. On PR #650, he mentioned "I can't make it work locally with streaming / crashing." He does not merge on green CI alone for non-trivial changes.

### What gets a PR delayed or stalled
- Cross-version fragility (PR #650 sat for a week because OTEL plugins were version-sensitive)
- Changes that touch core behavior without obvious need (no examples found of outright rejection, but careful scrutiny is implied)

**evalstate would...** merge our #405 fix quickly if: (1) it has a regression test, (2) it follows the existing `_execute_on_server` fork pattern, (3) it does not change the public API. He would push a co-commit if we miss an edge case.

---

## 10. Design Instincts

### When does he create a new class?

A new class is created when there is a distinct **lifecycle** to manage (construct, init, use, close). `MCPAggregator`, `MCPConnectionManager`, `ServerConnection` -- each has an independent lifecycle.

Data containers become classes when they carry behavior (methods like `record()`, `is_healthy()`, `request_shutdown()`). Pure data uses `@dataclass(frozen=True, slots=True)` or `BaseModel`.

`ServerRegistry` is 90 lines with 3 methods. It became a class because it owns state (`registry` dict) and has a lifecycle (load from file). But it has no Protocol base, no inheritance, no ABC. evalstate does not create classes for ceremony.

### When does he create a new file?

When the responsibility is distinct enough to name independently. `interfaces.py` exists to break circular imports -- that is its entire purpose, stated in its module docstring. `gen_client.py` provides the non-persistent connection shortcut -- a single `@asynccontextmanager` function.

He does NOT create a file for every class. `ServerConnection` lives in `mcp_connection_manager.py` alongside the manager that creates and owns it. `NamespacedTool`, `ServerStats`, `ServerStatus` all live in `mcp_aggregator.py` alongside their sole consumer.

### When does he create a helper function?

Free functions exist at module level when they are pure (no `self`) and used by the main class. Examples:
- `_prepare_headers_and_auth()` -- extracted because it is testable in isolation
- `_format_stdio_startup_error()` -- extracted because it is a complex string builder
- `_is_oauth_timeout_message()` -- extracted because it is a predicate tested independently
- `_server_lifecycle_task()` -- extracted because it runs in a separate task and must NEVER raise

The pattern: extract to a module-level function when (a) the logic is testable independently, or (b) the function runs in a different execution context (separate task).

### When does he use inline lambda?

Sparingly. Lambdas appear only as `error_factory` arguments:
```python
error_factory=lambda msg: CallToolResult(
    isError=True, content=[TextContent(type="text", text=msg)]
)
```
And as quick throwaway predicates in tests. Never in class definitions. Never as stored attributes.

### The "one more level of indirection" threshold

evalstate adds abstraction when he hits three triggers:
1. **Multiple callers** need the same error-handling logic (hence `_execute_on_server` centralizing all server dispatch)
2. **Testability** demands isolation (hence `_prepare_headers_and_auth` as a free function)
3. **Lifecycle boundaries** exist (hence `ServerConnection` as its own class, not a dict)

He does NOT add abstraction for:
- Two-case behavioral forks (uses if/else on `connection_persistence`)
- Future extensibility ("what if we need a third transport type?")
- Design pattern compliance (no abstract factories, no visitors, no observers)

**evalstate would...** reject a PR that introduces a `ConnectionStrategy` ABC with `PersistentStrategy` and `TemporaryStrategy` subclasses. He would accept a PR that extracts a clearly-named private method to reduce a 50-line if/else block into two 25-line methods dispatched by the same if/else.

---

---

## Appendix: Lessons from PR #737 Review (merged 2026-03-22)

Patterns observed from evalstate's own commits on top of our PR. These represent his current preferences.

### Protocol Hierarchy over Duplication

When two protocols share methods, evalstate uses inheritance rather than repeating signatures:

```python
# DO — inheritance eliminates duplication
class ServerRegistryProtocol(ServerInitializerProtocol, Protocol):
    @property
    def registry(self) -> dict[str, "MCPServerSettings"]: ...
    @property
    def connection_manager(self) -> MCPConnectionManagerProtocol: ...
    def get_server_config(self, server_name: str) -> "MCPServerSettings | None": ...
    # initialize_server and get_server_capabilities inherited from ServerInitializerProtocol

# DON'T — copy-paste the same method signatures into both protocols
```

### Resource Ownership via Context Manager Wrappers

When a function creates a resource (e.g. `httpx.AsyncClient`) that must be closed alongside a transport context, evalstate wraps both in a single context manager:

```python
@asynccontextmanager
async def _managed_http_transport_context(
    http_client: httpx.AsyncClient,
    transport_context: AbstractAsyncContextManager,
):
    """Own an HTTP client for a transport context built from that client."""
    async with http_client:
        async with transport_context as streams:
            yield streams
```

This ensures the client is closed even if the transport raises. Applied in both `create_transport_context()` (non-persistent) and the persistent `launch_server()` path.

### Config Passthrough to Session Factory

Session factories should receive `server_config` as a keyword argument — not just positional stream/timeout args:

```python
session = client_session_factory(
    read_stream,
    write_stream,
    read_timeout,
    server_config=config,  # enables per-server session customization
)
```

### AsyncIterator over AsyncGenerator in Signatures

Return type for `@asynccontextmanager` decorated methods: use `AsyncIterator[T]` not `AsyncGenerator[T, None]`:

```python
# DO
async def initialize_server(self, ...) -> AsyncIterator[ClientSession]:

# DON'T
async def initialize_server(self, ...) -> AsyncGenerator[ClientSession, None]:
```

### Cache Invalidation on Reconnect

Any cache that stores per-server state must be cleared when `force_reconnect=True`:

```python
if attach_options.force_reconnect:
    async with self._capabilities_cache_lock:
        self._capabilities_cache.pop(server_name, None)
```

---

*Part 2 produced by code-stylist for the W-E-A dominion pipeline. Source: deep analysis of mcp_aggregator.py (~2300 lines), mcp_connection_manager.py (~1300 lines), interfaces.py, mcp_server_registry.py, context_dependent.py, gen_client.py, 4 unit test files, and review comments from 18+ merged PRs.*

*Appendix added from evalstate's review commits on PR #737 (2026-03-22).*
