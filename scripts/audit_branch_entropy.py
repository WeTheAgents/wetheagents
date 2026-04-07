import subprocess
import json
import re
import sys
import argparse

def get_merged_agent_branches():
    """Returns a list of remote branches that are merged into origin/main and start with origin/agent/"""
    try:
        output = subprocess.check_output(['git', 'branch', '-r', '--merged', 'origin/main'], text=True)
    except subprocess.CalledProcessError as e:
        print("Error running git branch:", e)
        return []
        
    branches = []
    for line in output.splitlines():
        branch = line.strip()
        # remote branches look like origin/agent/...
        if branch.startswith('origin/agent/'):
            branches.append(branch)
            
    return branches

def get_open_issues():
    """Returns a set of open issue numbers as strings"""
    try:
        output = subprocess.check_output(['gh', 'issue', 'list', '--state', 'open', '--json', 'number'], text=True)
        data = json.loads(output)
        return {str(issue['number']) for issue in data}
    except Exception as e:
        print(f"Error fetching open issues: {e}")
        return set()

def parse_issue_number(branch):
    """
    Branch format: origin/agent/<agent-name>/<issue-number>-<short-slug>
    Returns the issue number as string if found, else None
    """
    parts = branch.split('/')
    if len(parts) >= 4:
        last_part = parts[-1]
        m = re.match(r'^(\d+)-', last_part)
        if m:
            return m.group(1)
    return None

def main():
    parser = argparse.ArgumentParser(description="Audit and clean up merged agent branches.")
    parser.add_argument('--delete', action='store_true', help="Actually delete the branches")
    parser.add_argument('--force', action='store_true', help="Force deletion")
    args = parser.parse_args()

    merged_branches = get_merged_agent_branches()
    if not merged_branches:
        print("No merged agent branches found.")
        sys.exit(0)

    open_issues = get_open_issues()
    
    candidates = []
    for branch in merged_branches:
        issue_number = parse_issue_number(branch)
        if issue_number and issue_number in open_issues:
            print(f"Skipping {branch} because issue #{issue_number} is still open.")
            continue
        candidates.append(branch)

    if not candidates:
        print("No deletion candidates found.")
        sys.exit(0)

    print("Deletion candidates:")
    for branch in candidates:
        print(f" - {branch}")

    if args.delete:
        for branch in candidates:
            # branch is like origin/agent/...
            local_branch_name = branch[len('origin/'):]
            cmd = ['git', 'push', 'origin', '--delete', local_branch_name]
            if args.force:
                cmd.append('--force')
            print(f"Running: {' '.join(cmd)}")
            try:
                subprocess.check_call(cmd)
            except subprocess.CalledProcessError as e:
                print(f"Failed to delete {branch}: {e}")
                
    sys.exit(2)

if __name__ == '__main__':
    main()
