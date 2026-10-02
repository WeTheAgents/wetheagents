"""Submit and read private Domain Access requests through GitHub."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import UUID, uuid4

from wea_vnext import access_control as control
from wea_vnext.access_github import COMMENT_LIMIT, GitHub, Journal, comments, repository
from wea_vnext.tide.collection import API_ROOT, REPOSITORY
from wea_vnext.tide.github import GitHubError
from wea_vnext.tide.replay import canonical, digest


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, encoding="utf-8")
    if result.returncode:
        raise ValueError("GitHub authentication/read failed; check gh auth status")
    return result.stdout.strip()


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "access", help="Request or read a seven-day Domain trip"
    )
    commands = parser.add_subparsers(dest="access_command", required=True)
    grant = commands.add_parser(
        "grant", help="Submit a request; only journal publication grants Access"
    )
    grant.add_argument("--agent", required=True)
    grant.add_argument("--domain", required=True)
    grant.add_argument("--request-id", help="Resume the same retained request UUID")
    grant.add_argument("--issuer", choices=("agent0", "operator"), default="agent0")
    grant.add_argument("--binding-id", default="pilot-agent0-role-v1")
    grant.add_argument("--binding-version", type=int, default=1)
    grant.set_defaults(_handler=command)
    show = commands.add_parser(
        "show", help="Rebuild current Access from the canonical journal"
    )
    group = show.add_mutually_exclusive_group(required=True)
    group.add_argument("--agent")
    group.add_argument("--request-id")
    group.add_argument(
        "--initiative", help="Read an initiative card and its exact revision"
    )
    group.add_argument(
        "--registry",
        action="store_true",
        help="Read immutable Domain binding revisions",
    )
    show.set_defaults(_handler=command)


def read(
    api: GitHub, args: argparse.Namespace, account: str, journal: Journal | None = None
) -> dict:
    reader = journal or Journal(api, verify_closure=False)
    head, genesis, entries, commits = reader.read()
    if genesis is None:
        return {"status": "disabled"}
    repository(api, genesis["issue_number"])
    now = control.utcnow()
    from wea_vnext.initiatives import POLICY, State

    if getattr(args, "registry", False):
        groups = (
            reader.state.groups if isinstance(reader.state, State) else (reader.state,)
        )
        return {
            "status": "observed",
            "journal_commit": head,
            "policy": POLICY if isinstance(reader.state, State) else None,
            "registry": reader.state.registry.to_mapping(),
            "registry_revision": reader.state.registry_revision
            if isinstance(reader.state, State)
            else reader.state.registry.registry_hash,
            "binding_revisions": {
                r.domain_id: reader.state.binding_revision(r.domain_id)
                if isinstance(reader.state, State)
                else r.record_hash
                for r in reader.state.registry.records
            },
            "binding_history": [group.registry.to_mapping() for group in groups],
        }
    if getattr(args, "initiative", None):
        if not isinstance(reader.state, State):
            return {"status": "disabled", "journal_commit": head}
        card = reader.state.initiatives.get(args.initiative)
        return {
            "status": "observed" if card else "not-found",
            "journal_commit": head,
            "initiative": card,
            "revision": digest(card) if card else None,
        }
    selected = []
    for entry, commit in zip(entries, commits, strict=True):
        decision = entry["decision"]
        request = decision.get("request") or {}
        if getattr(args, "request_id", None):
            matches = (
                request.get("request_id") == args.request_id
                and entry["source"]["original_author_account_id"] == account
            )
        else:
            matches = (
                request.get("agent_id", request.get("payload", {}).get("agent_id"))
                == args.agent
            )
        if matches:
            selected.append(control.view(entry, commit, now))
    pending = []
    processed = {e["source"]["object_id"] for e in entries}
    for row in comments(api, genesis["issue_number"]):
        if str(row["id"]) in processed or control.timestamp(
            row["created_at"]
        ) <= control.timestamp(genesis["cutoff"]):
            continue
        try:
            from wea_vnext.initiatives import MARKER
            from wea_vnext.initiatives import request as initiative_request

            body = row.get("body") or ""
            request = (
                initiative_request(body)
                if body.startswith(MARKER)
                else control.request(body)
            )
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
        if (
            getattr(args, "request_id", None)
            and request["request_id"] == args.request_id
            and str(row["user"]["id"]) == account
        ) or (
            not getattr(args, "request_id", None)
            and request.get("agent_id", request.get("payload", {}).get("agent_id"))
            == args.agent
        ):
            pending.append(
                {"status": "pending", "request": request, "source_url": row["html_url"]}
            )
    return {
        "status": "observed" if selected else "pending" if pending else "not-found",
        "journal_commit": head,
        "evaluated_at": now.isoformat(),
        "evaluation": "actual-utc-read",
        "decisions": selected,
        "pending": pending,
    }


def submit(api: GitHub, args: argparse.Namespace, account: str, root: Path) -> dict:
    journal = Journal(api)
    _, genesis, _, _ = journal.read()
    if genesis is None:
        return {"status": "disabled"}
    repository(api, genesis["issue_number"])
    identifier = args.request_id or str(uuid4())
    if str(UUID(identifier)) != identifier:
        raise ValueError("request_id must be a canonical UUID")
    issuer = (
        {
            "kind": "operator",
            "subject": str(control.OPERATOR),
            "binding_id": "canonical-operator",
            "binding_version": 1,
        }
        if args.issuer == "operator"
        else {
            "kind": "agent0",
            "subject": "agent0@system",
            "binding_id": args.binding_id,
            "binding_version": args.binding_version,
        }
    )
    request = {
        "schema": control.SCHEMA,
        "request_id": identifier,
        "agent_id": args.agent,
        "domain_id": args.domain,
        "issuer": issuer,
        "registry_hash": genesis["registry_hash"],
    }
    from wea_vnext.initiatives import MARKER, SCHEMA, State

    if isinstance(journal.state, State):
        request = {
            "schema": SCHEMA,
            "request_id": identifier,
            "actor": issuer,
            "operation": "grant",
            "payload": {
                "agent_id": args.agent,
                "domain_id": args.domain,
                "issuer": issuer,
                "registry_hash": journal.state.registry_revision,
                "binding_revision": journal.state.binding_revision(args.domain),
            },
        }
        body = MARKER + canonical(request).decode("utf-8")
    else:
        body = control.MARKER + canonical(request).decode("utf-8")
        control.request(body)
    saved = {
        "repository": REPOSITORY,
        "account_id": account,
        "body": body,
        "issue_number": genesis["issue_number"],
    }
    directory = root / ".wea_runs" / "access-requests"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{identifier}.json"
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(canonical(saved).decode("utf-8"))
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError:
        retained = control.strict_json(path.read_text(encoding="utf-8"))
        # Resume retained bytes even if the current registry pointer moved.
        from wea_vnext.initiatives import request as initiative_request

        retained_body = retained.get("body", "")
        retained_request = (
            initiative_request(retained_body)
            if retained_body.startswith(MARKER)
            else control.request(retained_body)
        )
        retained_payload = retained_request.get("payload", retained_request)
        if (
            {k: retained.get(k) for k in ("repository", "account_id", "issue_number")}
            != {k: saved[k] for k in ("repository", "account_id", "issue_number")}
            or retained_request["request_id"] != identifier
            or retained_payload.get("agent_id") != args.agent
            or retained_payload.get("domain_id") != args.domain
            or retained_payload.get("issuer") != issuer
            or retained_request.get("operation", "grant") != "grant"
        ):
            raise ValueError(
                "retained request ID belongs to a different account or payload"
            ) from None
        request, body = retained_request, retained_body
    print(
        json.dumps(
            {"status": "retained", "request_id": identifier, "local_request": str(path)}
        ),
        flush=True,
    )
    args.request_id = identifier
    observed = read(api, args, account, journal)
    if observed["status"] != "not-found":
        matches = observed.get("decisions", []) + observed.get("pending", [])
        if any(item.get("request") != request for item in matches):
            raise ValueError("request ID already belongs to a different payload")
        return observed
    if len(comments(api, genesis["issue_number"])) >= COMMENT_LIMIT:
        raise ValueError(
            "Access request pending locally: Issue comment capacity reached"
        )
    try:
        api.request(
            "POST",
            f"{API_ROOT}/issues/{genesis['issue_number']}/comments",
            {"body": body},
        )
    except GitHubError:
        observed = read(api, args, account, journal)
        if observed["status"] == "not-found":
            return {
                "status": "submission-unconfirmed",
                "request_id": identifier,
                "next": "Resume with the same --request-id; do not invent another UUID",
            }
        return observed
    for attempt in range(3):
        if attempt:
            time.sleep(2)
        observed = read(api, args, account, journal)
        if observed["status"] == "observed":
            break
    return observed


def command(args: argparse.Namespace) -> int:
    try:
        if args.repo != REPOSITORY:
            raise ValueError("Access is restricted to the canonical repository")
        account = str(json.loads(gh("api", "user"))["id"])
        api = GitHub(gh("auth", "token"))
        root = (
            Path(args.root)
            if args.root
            else Path(
                subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    check=True,
                    capture_output=True,
                    encoding="utf-8",
                ).stdout.strip()
            )
        )
        result = (
            submit(api, args, account, root)
            if args.access_command == "grant"
            else read(api, args, account)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "observed" else 2
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        GitHubError,
        subprocess.CalledProcessError,
    ) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}))
        return 1
