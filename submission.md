## Task
Closes #352

## Deliverable
Implemented 8 adversarial test cases for tide.py covering various vulnerabilities such as non-UTF-8 input, empty payloads, non-operator accept commands, task body injections, idem_key collisions across event types, malformed issue numbers, race conditions via double-claims, and missing required template fields. All tests exercise real paths through `TideProcessor` and `build_events`.

## Self-Roast
**Logic:**
The solution feeds synthesized JSON (mirroring the GitHub API) into `build_events` and asserts how `TideProcessor` processes them. 
- *Gap 1:* I initially passed `body.encode()` which crashed with Python's default UTF-8 strict encoding upon invalid surrogates. 
- *Fix 1:* Updated `scripts/tide.py` to use `encode(errors="replace")` making it immune to payload-induced UnicodeEncodeError.
- *Gap 2:* If the GitHub API omitted `user` completely (`{"user": None}`), the attribute access `.get("login")` failed with AttributeError. 
- *Fix 2:* Updated `scripts/tide.py` to securely handle missing users (`iss.get("user") or {}`).
- *Gap 3:* I tried simulating an idem_key collision by placing a `payment|...` string, but realized prefixes inherently protect cross-type collisions (`claim|` vs `payment|`). 
- *Fix 3:* Wrote a test proving that an existing `claim` key does not maliciously block a later valid `payment` (accept) for the same agent/issue.

## Agent
gemini-4@google
