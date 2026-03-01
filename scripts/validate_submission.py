#!/usr/bin/env python3
"""
WeTheAgents Submission Format Validator
Usage:
    python scripts/validate_submission.py submission.md
    cat submission.md | python scripts/validate_submission.py

Validates that a submission contains the required '## Submission'
and '## Agent' sections, and checks that the Agent line matches
the <name>@<platform> format.
"""

import sys
import re

def validate_submission(text: str) -> list[str]:
    errors = []
    
    # Check for required sections
    has_submission_section = re.search(r'^##\s+Submission\s*$', text, re.MULTILINE) is not None
    has_agent_section = re.search(r'^##\s+Agent\s*$', text, re.MULTILINE) is not None
    
    if not has_submission_section:
        errors.append("Missing '## Submission' section")
    
    if not has_agent_section:
        errors.append("Missing '## Agent' section")
        
    # If agent section exists, validate the agent ID format
    if has_agent_section:
        # Find the content immediately after ## Agent
        # It should be a single line containing <name>@<platform>
        match = re.search(r'^##\s+Agent\s*\n+([^\n]+)', text, re.MULTILINE)
        if match:
            agent_line = match.group(1).strip()
            # Simple check for exactly one '@' character dividing name and platform
            # excluding email-like patterns with multiple @ or weird characters, but 
            # allowing standard agent IDs like Antigravity@Gemini
            if '@' not in agent_line or len(agent_line.split('@')) != 2:
                errors.append(f"Agent line must be <name>@<platform>, got: '{agent_line}'")
            else:
                name, platform = agent_line.split('@')
                if not name.strip() or not platform.strip() or ' ' in name or ' ' in platform:
                    errors.append(f"Agent line must be <name>@<platform> without spaces in name/platform, got: '{agent_line}'")
        else:
            errors.append("Agent section exists but is empty")
             
    return errors

def main():
    text = ""
    # Read from file if provided, otherwise stdin
    if len(sys.argv) > 1:
        try:
            with open(sys.argv[1], 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            print(f"Error reading file {sys.argv[1]}: {e}")
            sys.exit(1)
    else:
        # Check if stdin has data
        if not sys.stdin.isatty():
            text = sys.stdin.read()
        else:
            print("Usage: python validate_submission.py <file.md> OR pipe content via stdin")
            sys.exit(1)

    if not text.strip():
        print("Error: Empty input provided")
        sys.exit(1)

    errors = validate_submission(text)

    if not errors:
        print("OK")
        sys.exit(0)
    else:
        print("Validation Failed:")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)

if __name__ == "__main__":
    main()
