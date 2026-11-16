#!/usr/bin/env bash
set -euo pipefail

: "${AWS_SANDBOX_ACCOUNT_ID:?Missing AWS_SANDBOX_ACCOUNT_ID}"
: "${CLEANUP_MODE:?Missing CLEANUP_MODE}"
: "${GITHUB_STEP_SUMMARY:?Missing GITHUB_STEP_SUMMARY}"

case "$CLEANUP_MODE" in
  dry-run|delete) ;;
  *) echo '::error::Unknown cleanup mode.'; exit 1 ;;
esac

identity=$(aws sts get-caller-identity --query '[Account, Arn]' --output text)
read -r account caller_arn <<< "$identity"
expected_role="arn:aws:sts::${AWS_SANDBOX_ACCOUNT_ID}:assumed-role/GitHubSandboxCleanup/"
if [[ "$account" != "$AWS_SANDBOX_ACCOUNT_ID" || "$caller_arn" != "$expected_role"* ]]; then
  echo '::error::AWS caller is outside the expected sandbox cleanup role.'
  exit 1
fi

args=(run --config nuke.yml --no-prompt --log-format json)
log_dir=$(mktemp -d)
trap 'rm -rf "$log_dir"' EXIT
printf '### AWS sandbox cleanup\n\n- Mode: `%s`\n- Account: `%s`\n' \
  "$CLEANUP_MODE" "$account" >> "$GITHUB_STEP_SUMMARY"

run_sweep() {
  local phase=$1
  shift
  local status=0
  aws-nuke "${args[@]}" "$@" 2>&1 | tee "$log_dir/$phase.jsonl" || status=$?
  python3 scripts/cleanup_report.py \
    --log "$log_dir/$phase.jsonl" \
    --phase "$phase" \
    --command-exit "$status" \
    --summary "$GITHUB_STEP_SUMMARY"
}

# Every deletion request gets a fresh discovery check before any removal starts.
# set -e stops here if discovery, permissions, or the command itself fails.
run_sweep preview
if [[ "$CLEANUP_MODE" == delete ]]; then
  run_sweep delete --no-dry-run
fi
