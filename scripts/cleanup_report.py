#!/usr/bin/env python3
"""Report AWS Nuke results, distinguishing unavailable services from scan failures."""

import argparse
import html
import json
import re
from pathlib import Path


# Only specific discovery responses qualify. Ordinary AccessDenied, networking,
# throttling, and deletion errors must still fail the job.
UNAVAILABLE_RESPONSES = (
    ({"Cloud9Environment"}, "This account does not have access to the Cloud9 service",
     "Cloud9 is unavailable to this account"),
    ({"CloudSearchDomain"}, "New domain creation not supported on this account.",
     "CloudSearch is unavailable to this account"),
    ({"MachineLearningBranchPrediction", "MachineLearningDataSource",
      "MachineLearningEvaluation", "MachineLearningMLModel"},
     "AmazonML is no longer available to new customers.",
     "Legacy Amazon ML is unavailable to this account"),
    ({"AWS::Timestream::Database", "AWS::Timestream::Table",
      "AWS::Timestream::ScheduledQuery"},
     "Only existing Timestream for LiveAnalytics customers can access the service.",
     "Timestream for LiveAnalytics is unavailable to this account"),
    ({"GlueDevEndpoint"}, "GetDevEndpoints operation is currently disabled.",
     "Glue development endpoints are disabled for this account"),
    ({"ShieldProtection", "ShieldProtectionGroup"},
     "ResourceNotFoundException: The subscription does not exist.",
     "No Shield Advanced subscription"),
)


def unavailable_reason(record):
    """Return a narrowly scoped service-availability explanation, if recognized."""
    if record.get("level") != "error" or not record.get("msg", "").startswith("listing failed:"):
        return None
    kind = record.get("resource_type", "")
    error = record.get("error", "")
    region = record.get("owner", "")
    for kinds, response, reason in UNAVAILABLE_RESPONSES:
        if kind in kinds and response in error:
            return reason
    if kind in {"CloudDirectoryDirectory", "CloudDirectorySchema"} and re.fullmatch(
        rf"AccessDeniedException: Account: [0-9]{{12}} is not authorized for region: {re.escape(region)}\.",
        error,
    ):
        return "Cloud Directory is unavailable to this account in this region"
    if kind in {"FMSPolicy", "FMSNotificationChannel"} and re.search(
        rf"AccessDeniedException: No default admin could be found for account [0-9]{{12}} in Region {re.escape(region)}(?:\n|$)",
        error,
    ):
        return "No Firewall Manager administrator is configured"
    # Q Business has no Ohio endpoint. Do not suppress DNS failures elsewhere.
    if kind in {"QBusinessApplication", "QBusinessDataSource", "QBusinessIndex",
                "QBusinessPlugin", "QBusinessRetriever", "QBusinessWebExperience"} and region == "us-east-2":
        if "lookup qbusiness.us-east-2.api.aws" in error and "no such host" in error:
            return "Q Business has no endpoint in us-east-2"
    if kind in {"BedrockCustomModel", "BedrockModelCustomizationJob"} and region == "us-east-2":
        if "UnknownOperationException: Unknown Operation" in error and "status code: 404" in error:
            return "This Bedrock customization API is unavailable in us-east-2"
    return None


def analyze(records, phase, command_exit):
    issues, unavailable, candidates, defaults = [], [], [], []
    scan, completion = None, None
    for record in records:
        msg = record.get("msg", "")
        reason = unavailable_reason(record)
        if reason:
            unavailable.append((record.get("owner", ""), record.get("resource_type", ""), reason))
        elif record.get("level") in {"error", "fatal", "panic"} or msg == "item queue is full, not all resources will be enqueued":
            issues.append((record.get("owner", ""), record.get("resource_type", record.get("type", "")),
                           record.get("error", msg)))
        if msg == "would remove":
            candidates.append((record.get("owner", ""), record.get("type", ""), record.get("name", ""),
                               record.get("prop:tag:Name", "")))
        if record.get("state") == "filtered" and (
            record.get("prop:IsDefault") == "true"
            or record.get("prop:DefaultForAz") == "true"
            or record.get("prop:DefaultVPC") == "true"
            or (record.get("type") == "AthenaWorkGroup" and record.get("prop:Name") == "primary")
            or (record.get("type") == "EC2SecurityGroup" and record.get("prop:Name") == "default")
            or (record.get("type") == "EC2NetworkACL" and msg == "filtered: cannot delete default VPC")
        ):
            defaults.append((record.get("owner", ""), record.get("type", ""), record.get("name", "")))
        if msg.startswith("Scan complete:") and all(isinstance(record.get(k), int) for k in ("total", "nukeable", "filtered")):
            scan = record
        if msg.startswith("Nuke complete:"):
            completion = record
    if command_exit:
        issues.append(("", "aws-nuke", f"Command exited with status {command_exit}"))
    if scan is None:
        issues.append(("", "Scan", "No complete scan summary was received"))
    elif phase == "delete" and scan["nukeable"] > 0:
        if completion is None or completion.get("failed") != 0:
            issues.append(("", "Deletion", "Deletion did not finish successfully; review the full log"))
    return {"issues": issues, "unavailable": unavailable, "candidates": candidates, "defaults": defaults,
            "scan": scan, "completion": completion}


def cell(value):
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", "<br>").replace("\r", "")


def table(headers, rows):
    return ["| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)]


def render(result, phase):
    output = ["", f"### {'Preview' if phase == 'preview' else 'Deletion'}", ""]
    if result["scan"]:
        output.extend([result["scan"]["msg"].strip(), ""])
    if phase == "preview":
        output.extend(table(["Region", "Resource type", "Resource", "Name tag"], sorted(result["candidates"])))
        if not result["candidates"]:
            output.extend(["", "No eligible resources were discovered."])
        if result["defaults"]:
            output.extend(["", "Preserved default resources:", ""])
            output.extend(table(["Region", "Resource type", "Resource"], sorted(result["defaults"])))
    if result["completion"]:
        output.extend(["", result["completion"]["msg"].strip()])
    if result["unavailable"]:
        output.extend(["", "Unavailable service checks (not resources found or deleted):", ""])
        output.extend(table(["Region", "Resource type", "Reason"], sorted(set(result["unavailable"]))))
    if result["issues"]:
        output.extend(["", "**Incomplete or failed run.**", ""])
        output.extend(table(["Region", "Resource type", "Error"], result["issues"]))
    else:
        suffix = " with the unavailable service checks listed above" if result["unavailable"] else ""
        output.extend(["", f"Result: {'Preview' if phase == 'preview' else 'Deletion'} completed{suffix}."])
    return "\n".join(output) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--phase", choices=("preview", "delete"), required=True)
    parser.add_argument("--command-exit", type=int, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    try:
        records = [json.loads(line) for line in args.log.read_text().splitlines() if line.strip()]
        if not all(isinstance(record, dict) for record in records):
            raise ValueError("Expected JSON log objects")
        result = analyze(records, args.phase, args.command_exit)
    except (ValueError, OSError) as error:
        result = {"issues": [("", "Log", str(error))], "unavailable": [], "candidates": [], "defaults": [],
                  "scan": None, "completion": None}
    with args.summary.open("a") as summary:
        summary.write(render(result, args.phase))
    if result["unavailable"]:
        print(f"::warning::{len(result['unavailable'])} service checks were unavailable; see the run summary.")
    if result["issues"]:
        print(f"::error::{args.phase} reported a failure or incomplete coverage; see the run summary.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
