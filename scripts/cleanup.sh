#!/usr/bin/env bash
set -euo pipefail

: "${AWS_SANDBOX_ACCOUNT_ID:?Missing AWS_SANDBOX_ACCOUNT_ID}"
: "${CLEANUP_MODE:?Missing CLEANUP_MODE}"
: "${GITHUB_STEP_SUMMARY:?Missing GITHUB_STEP_SUMMARY}"

identity=$(aws sts get-caller-identity --query '[Account, Arn]' --output text)
read -r account caller_arn <<< "$identity"
expected_role="arn:aws:sts::${AWS_SANDBOX_ACCOUNT_ID}:assumed-role/GitHubSandboxCleanup/"
if [[ "$account" != "$AWS_SANDBOX_ACCOUNT_ID" || "$caller_arn" != "$expected_role"* ]]; then
  echo '::error::AWS caller is outside the expected sandbox cleanup role.'
  exit 1
fi

args=(run --config nuke.yml --no-prompt --log-format json)
case "$CLEANUP_MODE" in
  dry-run) ;;
  delete) args+=(--no-dry-run) ;;
  *) echo '::error::Unknown cleanup mode.'; exit 1 ;;
esac

log_file=$(mktemp)
trap 'rm -f "$log_file"' EXIT
printf '### AWS sandbox cleanup\n\n- Mode: `%s`\n- Account: `%s`\n' \
  "$CLEANUP_MODE" "$account" >> "$GITHUB_STEP_SUMMARY"

status=0
aws-nuke "${args[@]}" 2>&1 | tee "$log_file" || status=$?

issues=$(jq -Rn '[inputs | fromjson? | select(
  .level == "error" or .level == "fatal" or .msg == "item queue is full, not all resources will be enqueued"
)] | length' < "$log_file")
jq -Rr 'fromjson? | select(has("nukeable") or (has("failed") and (.msg | startswith("Nuke complete:"))))
  | "- " + (.msg | rtrimstr("\n"))' < "$log_file" >> "$GITHUB_STEP_SUMMARY"

if (( status != 0 || issues != 0 )); then
  printf -- '- Result: Review the logs (command exit %s, %s errors or queue warnings).\n' \
    "$status" "$issues" >> "$GITHUB_STEP_SUMMARY"
  echo '::error::Cleanup reported a failure or incomplete coverage. Review the AWS Nuke logs.'
  exit 1
fi
