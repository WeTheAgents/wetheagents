#!/usr/bin/env python3
"""Setup the Pipeline Hub GitHub Project board.

Creates the Project, custom fields, and populates it with existing
stage:* issues. Idempotent — safe to re-run.

Requirements:
  - `gh` CLI authenticated with `project` and `read:project` scopes
  - Run: gh auth refresh -s read:project,project

Usage:
  python scripts/setup_pipeline_hub.py [--owner OWNER] [--repo REPO] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "pipeline" / "config.json"

REPO_DEFAULT = "WeTheAgents/wetheagents"
OWNER_DEFAULT = "WeTheAgents"


def gh_graphql(query: str, json_vars: dict | None = None, **variables: str) -> dict:
    """Execute a GraphQL query via gh CLI.

    String variables are passed with -f (as strings).
    json_vars are passed with -F (parsed as JSON for complex types).
    """
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        cmd.extend(["-f", f"{k}={v}"])
    if json_vars:
        for k, v in json_vars.items():
            cmd.extend(["-F", f"{k}={json.dumps(v)}"])
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"GraphQL error:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def gh_cli(*args: str) -> str:
    """Execute a gh CLI command and return stdout."""
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(f"gh error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def check_scopes() -> bool:
    """Check if the token has project scopes by parsing Token scopes line."""
    result = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True, check=False
    )
    output = result.stdout + result.stderr
    # Find the Token scopes line for the active account
    for line in output.splitlines():
        if "Token scopes" in line:
            # Line looks like: "  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'"
            scopes = line.split(":", 1)[-1] if ":" in line else ""
            if "'read:project'" in scopes or "'project'" in scopes:
                return True
    print(
        "ERROR: Token missing project scopes.\n"
        "Run: gh auth refresh -s read:project,project",
        file=sys.stderr,
    )
    return False


def get_owner_id(owner: str) -> str:
    """Get the node ID of the org or user."""
    # Try org first
    data = gh_graphql(
        """
        query($login: String!) {
          organization(login: $login) { id }
        }
        """,
        login=owner,
    )
    org = data.get("data", {}).get("organization")
    if org:
        return org["id"]

    # Fall back to user
    data = gh_graphql(
        """
        query($login: String!) {
          user(login: $login) { id }
        }
        """,
        login=owner,
    )
    user = data.get("data", {}).get("user")
    if user:
        return user["id"]

    print(f"ERROR: Cannot find org or user '{owner}'", file=sys.stderr)
    sys.exit(1)


def find_existing_project(owner: str, title: str) -> dict | None:
    """Find a project by title under the given owner."""
    data = gh_graphql(
        """
        query($login: String!) {
          organization(login: $login) {
            projectsV2(first: 20) {
              nodes { id title number }
            }
          }
        }
        """,
        login=owner,
    )
    org = data.get("data", {}).get("organization")
    if not org:
        # Try user
        data = gh_graphql(
            """
            query($login: String!) {
              user(login: $login) {
                projectsV2(first: 20) {
                  nodes { id title number }
                }
              }
            }
            """,
            login=owner,
        )
        org = data.get("data", {}).get("user")

    if not org:
        return None

    for proj in org["projectsV2"]["nodes"]:
        if proj["title"] == title:
            return proj
    return None


def create_project(owner_id: str, title: str) -> dict:
    """Create a new Project v2."""
    data = gh_graphql(
        """
        mutation($ownerId: ID!, $title: String!) {
          createProjectV2(input: {ownerId: $ownerId, title: $title}) {
            projectV2 { id title number }
          }
        }
        """,
        ownerId=owner_id,
        title=title,
    )
    return data["data"]["createProjectV2"]["projectV2"]


def get_project_fields(project_id: str) -> list[dict]:
    """List existing fields on the project."""
    data = gh_graphql(
        """
        query($projectId: ID!) {
          node(id: $projectId) {
            ... on ProjectV2 {
              fields(first: 30) {
                nodes {
                  ... on ProjectV2Field { id name dataType }
                  ... on ProjectV2SingleSelectField { id name dataType options { id name } }
                  ... on ProjectV2IterationField { id name dataType }
                }
              }
            }
          }
        }
        """,
        projectId=project_id,
    )
    return data["data"]["node"]["fields"]["nodes"]


def create_single_select_field(
    project_id: str, name: str, options: list[dict]
) -> str:
    """Create a SingleSelect custom field with options."""
    opts = [{"name": o["name"], "color": o["color"]} for o in options]
    data = gh_graphql(
        """
        mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
          createProjectV2Field(input: {
            projectId: $projectId,
            dataType: SINGLE_SELECT,
            name: $name,
            singleSelectOptions: $options
          }) {
            projectV2Field { ... on ProjectV2SingleSelectField { id name } }
          }
        }
        """,
        json_vars={"options": opts},
        projectId=project_id,
        name=name,
    )
    return data["data"]["createProjectV2Field"]["projectV2Field"]["id"]


def create_field(project_id: str, name: str, data_type: str) -> str:
    """Create a TEXT, DATE, or NUMBER custom field."""
    data = gh_graphql(
        """
        mutation($projectId: ID!, $name: String!, $dataType: ProjectV2CustomFieldType!) {
          createProjectV2Field(input: {
            projectId: $projectId,
            dataType: $dataType,
            name: $name
          }) {
            projectV2Field { ... on ProjectV2Field { id name } }
          }
        }
        """,
        projectId=project_id,
        name=name,
        dataType=data_type,
    )
    return data["data"]["createProjectV2Field"]["projectV2Field"]["id"]


def get_stage_issues(repo: str) -> list[dict]:
    """Find all open issues with stage:* labels."""
    stages = ["stage:triage", "stage:negativa", "stage:spec", "stage:impl", "stage:verify"]
    issues = []
    for stage in stages:
        result = subprocess.run(
            ["gh", "issue", "list", "--repo", repo, "--label", stage,
             "--state", "open", "--json", "number,title,nodeId,labels"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            for issue in json.loads(result.stdout):
                if not any(i["number"] == issue["number"] for i in issues):
                    issues.append(issue)
    return issues


def add_item_to_project(project_id: str, content_id: str) -> str | None:
    """Add an issue to the project. Returns item ID."""
    data = gh_graphql(
        """
        mutation($projectId: ID!, $contentId: ID!) {
          addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
            item { id }
          }
        }
        """,
        projectId=project_id,
        contentId=content_id,
    )
    item = data.get("data", {}).get("addProjectV2ItemById", {}).get("item")
    return item["id"] if item else None


def set_single_select_value(
    project_id: str, item_id: str, field_id: str, option_id: str
) -> None:
    """Set a SingleSelect field value on a project item."""
    gh_graphql(
        """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
          updateProjectV2ItemFieldValue(input: {
            projectId: $projectId,
            itemId: $itemId,
            fieldId: $fieldId,
            value: {singleSelectOptionId: $optionId}
          }) {
            projectV2Item { id }
          }
        }
        """,
        projectId=project_id,
        itemId=item_id,
        fieldId=field_id,
        optionId=option_id,
    )


def label_to_stage_option(labels: list[dict]) -> str | None:
    """Map issue labels to a Stage option name."""
    label_map = {
        "stage:triage": "Triage",
        "stage:negativa": "Via Negativa",
        "stage:spec": "Spec",
        "stage:impl": "Implementation",
        "stage:verify": "Verification",
        "rejected:via-negativa": "Rejected",
        "rejected:stale": "Rejected",
        "rejected:duplicate": "Rejected",
    }
    for label in labels:
        name = label.get("name", "")
        if name in label_map:
            return label_map[name]
    return None


def main():
    parser = argparse.ArgumentParser(description="Setup Pipeline Hub GitHub Project")
    parser.add_argument("--owner", default=OWNER_DEFAULT, help="GitHub org/user")
    parser.add_argument("--repo", default=REPO_DEFAULT, help="owner/repo")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    args = parser.parse_args()

    # Load config
    config = json.loads(CONFIG_PATH.read_text())
    board_config = config["project_board"]

    # Check scopes
    if not args.dry_run and not check_scopes():
        sys.exit(1)

    print(f"Setting up Pipeline Hub for {args.owner}...")

    # --- Step 1: Find or create project ---
    existing = find_existing_project(args.owner, board_config["title"])
    if existing:
        project_id = existing["id"]
        project_number = existing["number"]
        print(f"  Found existing project: #{project_number} '{board_config['title']}'")
    else:
        if args.dry_run:
            print(f"  [DRY RUN] Would create project '{board_config['title']}'")
            project_id = None
            project_number = "?"
        else:
            owner_id = get_owner_id(args.owner)
            project = create_project(owner_id, board_config["title"])
            project_id = project["id"]
            project_number = project["number"]
            print(f"  Created project: #{project_number} '{board_config['title']}'")

    # --- Step 2: Create custom fields ---
    if args.dry_run and project_id is None:
        existing_fields = []
    else:
        existing_fields = get_project_fields(project_id)
    existing_names = {f.get("name") for f in existing_fields}

    # Stage field (SingleSelect)
    stage_field_name = board_config["stage_field"]
    stage_field_id = None
    stage_options_map = {}

    if stage_field_name in existing_names:
        print(f"  Field '{stage_field_name}' already exists, skipping")
        for f in existing_fields:
            if f.get("name") == stage_field_name:
                stage_field_id = f["id"]
                for opt in f.get("options", []):
                    stage_options_map[opt["name"]] = opt["id"]
    else:
        if args.dry_run:
            print(f"  [DRY RUN] Would create SingleSelect field '{stage_field_name}'")
        else:
            stage_field_id = create_single_select_field(
                project_id, stage_field_name, board_config["stage_options"]
            )
            print(f"  Created field: {stage_field_name}")
            # Re-fetch to get option IDs
            for f in get_project_fields(project_id):
                if f.get("name") == stage_field_name:
                    for opt in f.get("options", []):
                        stage_options_map[opt["name"]] = opt["id"]

    # Other custom fields
    for field_def in board_config["custom_fields"]:
        if field_def["name"] in existing_names:
            print(f"  Field '{field_def['name']}' already exists, skipping")
            continue
        if args.dry_run:
            print(f"  [DRY RUN] Would create {field_def['type']} field '{field_def['name']}'")
        else:
            create_field(project_id, field_def["name"], field_def["type"])
            print(f"  Created field: {field_def['name']} ({field_def['type']})")

    # --- Step 3: Add existing stage:* issues ---
    issues = get_stage_issues(args.repo)
    print(f"  Found {len(issues)} open issues with stage:* labels")

    for issue in issues:
        stage_option = label_to_stage_option(issue.get("labels", []))
        if args.dry_run:
            print(f"  [DRY RUN] Would add #{issue['number']}: {issue['title']} -> {stage_option}")
            continue

        item_id = add_item_to_project(project_id, issue["nodeId"])
        if item_id and stage_field_id and stage_option:
            option_id = stage_options_map.get(stage_option)
            if option_id:
                set_single_select_value(project_id, item_id, stage_field_id, option_id)
        print(f"  Added #{issue['number']}: {issue['title']} -> {stage_option}")

    # --- Done ---
    # Detect org vs user for correct URL
    is_org = gh_graphql(
        'query($login: String!) { organization(login: $login) { id } }',
        login=args.owner,
    ).get("data", {}).get("organization") is not None if not args.dry_run else True
    url_type = "orgs" if is_org else "users"
    print(f"\nPipeline Hub ready: https://github.com/{url_type}/{args.owner}/projects/{project_number}")
    print("\nManual steps remaining:")
    print("  1. Open the project in browser")
    print("  2. Create Board view: group by 'Stage' field")
    print("  3. Create Table view: add all custom fields as columns")
    print("  4. Create 'Stalls' view: filter by days-in-stage > threshold")
    print("  5. Configure auto-add: Settings > Workflows > Auto-add items with 'task' label")


if __name__ == "__main__":
    main()
