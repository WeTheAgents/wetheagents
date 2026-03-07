#!/usr/bin/env bash
# Creates all pipeline labels in GitHub.
# Run once after repo setup: bash scripts/create_labels.sh
# Requires: gh CLI authenticated, correct repo context.

set -euo pipefail

echo "Creating pipeline stage labels..."
gh label create "stage:triage"   --color "D4C5F9" --description "Pipeline: triaging task" --force
gh label create "stage:negativa" --color "E99695" --description "Pipeline: via negativa gate" --force
gh label create "stage:spec"     --color "FEF2C0" --description "Pipeline: writing specification" --force
gh label create "stage:impl"     --color "BFD4F2" --description "Pipeline: implementation in progress" --force
gh label create "stage:verify"   --color "C2E0C6" --description "Pipeline: verification and review" --force

echo "Creating complexity labels..."
gh label create "complexity:clear"       --color "0E8A16" --description "Cynefin: known solution" --force
gh label create "complexity:complicated" --color "FBCA04" --description "Cynefin: requires expert analysis" --force
gh label create "complexity:complex"     --color "D93F0B" --description "Cynefin: requires shaping" --force
gh label create "complexity:chaotic"     --color "B60205" --description "Cynefin: emergency response" --force

echo "Creating appetite labels..."
gh label create "appetite:2h" --color "C5DEF5" --description "Appetite: 2 hours" --force
gh label create "appetite:1d" --color "BFD4F2" --description "Appetite: 1 day" --force
gh label create "appetite:3d" --color "A8C8F0" --description "Appetite: 3 days" --force
gh label create "appetite:6d" --color "91B8E0" --description "Appetite: 6 days" --force

echo "Creating rejection labels (terminal states)..."
gh label create "rejected:via-negativa" --color "000000" --description "Rejected at via negativa gate" --force
gh label create "rejected:stale"        --color "222222" --description "Rejected: no response" --force
gh label create "rejected:duplicate"    --color "333333" --description "Rejected: duplicate" --force

echo "Done. $(gh label list | grep -c 'stage:\|complexity:\|appetite:\|rejected:') pipeline labels active."
