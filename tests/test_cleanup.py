import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cleanup_report", ROOT / "scripts/cleanup_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def scan(count=1):
    return {"level": "info", "msg": f"Scan complete: {count} total, {count} nukeable, 0 filtered.",
            "total": count, "nukeable": count, "filtered": 0}


def failure(kind="EC2Instance", error="AccessDeniedException: Access denied", region="us-east-1"):
    return {"level": "error", "msg": "listing failed:\n" + error,
            "error": error, "resource_type": kind, "owner": region}


class ReportTests(unittest.TestCase):
    def test_known_account_unavailability_is_reported(self):
        for kinds, response, _ in report.UNAVAILABLE_RESPONSES:
            for kind in kinds:
                with self.subTest(kind=kind):
                    result = report.analyze([failure(kind, response), scan()], "preview", 0)
                    self.assertFalse(result["issues"])
                    self.assertEqual(len(result["unavailable"]), 1)

    def test_cloud_directory_and_fms_account_responses(self):
        for kind, error in [
            ("CloudDirectoryDirectory", "AccessDeniedException: Account: 111122223333 is not authorized for region: us-east-1."),
            ("FMSPolicy", "AccessDeniedException: No default admin could be found for account 111122223333 in Region us-east-1\n\tstatus code: 400"),
        ]:
            self.assertIsNotNone(report.unavailable_reason(failure(kind, error)))

    def test_permission_errors_remain_fatal_even_on_known_services(self):
        for kind in ["EC2Instance", "IAMRole", "Cloud9Environment", "CloudDirectoryDirectory",
                     "FMSPolicy", "ShieldProtection", "BedrockAgentCoreRegistry"]:
            with self.subTest(kind=kind):
                result = report.analyze([failure(kind), scan()], "preview", 0)
                self.assertTrue(result["issues"])
                self.assertFalse(result["unavailable"])

    def test_unavailability_exception_only_applies_to_discovery(self):
        record = failure("ShieldProtection", "ResourceNotFoundException: The subscription does not exist.")
        record["msg"] = "deletion failed"
        self.assertTrue(report.analyze([record, scan()], "delete", 0)["issues"])

    def test_q_business_dns_exception_is_limited_to_ohio(self):
        error = "lookup qbusiness.us-east-2.api.aws on 127.0.0.53:53: no such host"
        self.assertIsNotNone(report.unavailable_reason(failure("QBusinessApplication", error, "us-east-2")))
        self.assertIsNone(report.unavailable_reason(failure("QBusinessApplication", error)))
        self.assertIsNone(report.unavailable_reason(failure("EC2Instance", error, "us-east-2")))

    def test_bedrock_exception_does_not_hide_other_http_errors(self):
        error = "UnknownOperationException: Unknown Operation\n\tstatus code: 404"
        self.assertIsNotNone(report.unavailable_reason(failure("BedrockCustomModel", error, "us-east-2")))
        self.assertIsNone(report.unavailable_reason(failure("BedrockCustomModel", error)))
        self.assertIsNone(report.unavailable_reason(failure("BedrockCustomModel", "status code: 503", "us-east-2")))

    def test_queue_overflow_and_nonzero_command_exit_fail(self):
        overflow = {"level": "warning", "msg": "item queue is full, not all resources will be enqueued"}
        self.assertTrue(report.analyze([overflow, scan()], "preview", 0)["issues"])
        self.assertTrue(report.analyze([scan()], "preview", 1)["issues"])

    def test_empty_or_truncated_log_fails(self):
        self.assertTrue(report.analyze([], "preview", 0)["issues"])
        self.assertTrue(report.analyze([scan()], "delete", 0)["issues"])

    def test_successful_delete_requires_completion(self):
        complete = {"msg": "Nuke complete: 0 failed, 0 skipped, 1 finished.", "failed": 0}
        self.assertFalse(report.analyze([scan(), complete], "delete", 0)["issues"])
        self.assertFalse(report.analyze([scan(0)], "delete", 0)["issues"])
        complete["failed"] = 1
        self.assertTrue(report.analyze([scan(), complete], "delete", 0)["issues"])

    def test_preview_lists_resources_and_escapes_names(self):
        candidate = {"msg": "would remove", "owner": "us-east-1", "type": "EC2Instance",
                     "name": "i-demo|<script>", "prop:tag:Name": "APP"}
        summary = report.render(report.analyze([candidate, scan()], "preview", 0), "preview")
        self.assertIn("i-demo&#124;&lt;script&gt;", summary)
        self.assertIn("APP", summary)

    def test_default_vpc_is_reported_as_preserved_while_its_instance_is_targeted(self):
        default_vpc = {"msg": "filtered: filtered by config", "state": "filtered", "type": "EC2VPC",
                       "owner": "us-east-1", "name": "vpc-default", "prop:IsDefault": "true"}
        instance = {"msg": "would remove", "type": "EC2Instance", "owner": "us-east-1", "name": "i-lab"}
        result = report.analyze([default_vpc, instance, scan()], "preview", 0)
        self.assertEqual([row[2] for row in result["defaults"]], ["vpc-default"])
        self.assertEqual([row[2] for row in result["candidates"]], ["i-lab"])
        self.assertIn("Preserved default resources:", report.render(result, "preview"))


class CleanupControlTests(unittest.TestCase):
    def run_cleanup(self, mode, denied=False, wrong_account=False, invalid_log=False, unavailable=False):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            aws = directory / "aws"
            aws.write_text("#!/bin/sh\nprintf '%s\\n' \"$TEST_IDENTITY\"\n")
            nuke = directory / "aws-nuke"
            nuke.write_text("""#!/usr/bin/env python3
import json, os, sys
with open(os.environ['TEST_CALLS'], 'a') as calls:
    calls.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ['TEST_INVALID'] == '1':
    print('{broken JSON')
    raise SystemExit(0)
if os.environ['TEST_DENIED'] == '1':
    print(json.dumps({'level': 'error', 'msg': 'listing failed:', 'resource_type': 'EC2Instance', 'error': 'AccessDenied'}))
if os.environ['TEST_UNAVAILABLE'] == '1':
    print(json.dumps({'level': 'error', 'msg': 'listing failed:', 'resource_type': 'Cloud9Environment', 'owner': 'us-east-1', 'error': 'This account does not have access to the Cloud9 service'}))
print(json.dumps({'msg': 'would remove', 'owner': 'us-east-1', 'type': 'EC2Instance', 'name': 'i-demo'}))
print(json.dumps({'level': 'info', 'msg': 'Scan complete: 1 total, 1 nukeable, 0 filtered.', 'total': 1, 'nukeable': 1, 'filtered': 0}))
if '--no-dry-run' in sys.argv:
    print(json.dumps({'level': 'info', 'msg': 'Nuke complete: 0 failed, 0 skipped, 1 finished.', 'failed': 0, 'finished': 1}))
""")
            aws.chmod(0o755)
            nuke.chmod(0o755)
            summary = directory / "summary.md"
            calls = directory / "calls.jsonl"
            account = "000000000000" if wrong_account else "111122223333"
            env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"],
                       AWS_SANDBOX_ACCOUNT_ID="111122223333", CLEANUP_MODE=mode,
                       GITHUB_STEP_SUMMARY=str(summary), TEST_CALLS=str(calls),
                       TEST_DENIED=str(int(denied)), TEST_INVALID=str(int(invalid_log)),
                       TEST_UNAVAILABLE=str(int(unavailable)),
                       TEST_IDENTITY=f"{account}\tarn:aws:sts::{account}:assumed-role/GitHubSandboxCleanup/test")
            result = subprocess.run(["bash", "scripts/cleanup.sh"], cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
            commands = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            return result, commands, summary.read_text() if summary.exists() else ""

    def test_dry_run_never_enables_deletion(self):
        result, commands, summary = self.run_cleanup("dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(commands), 1)
        self.assertNotIn("--no-dry-run", commands[0])
        self.assertIn("i-demo", summary)

    def test_delete_previews_before_removing(self):
        result, commands, _ = self.run_cleanup("delete")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(commands), 2)
        self.assertNotIn("--no-dry-run", commands[0])
        self.assertIn("--no-dry-run", commands[1])

    def test_discovery_failure_blocks_deletion(self):
        result, commands, _ = self.run_cleanup("delete", denied=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(commands), 1)
        self.assertNotIn("--no-dry-run", commands[0])

    def test_unavailable_service_is_visible_and_does_not_block(self):
        result, commands, summary = self.run_cleanup("delete", unavailable=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(commands), 2)
        self.assertIn("Unavailable service checks", summary)
        self.assertIn("::warning::", result.stdout)

    def test_wrong_account_and_unknown_mode_do_not_scan(self):
        for mode, wrong_account in [("delete", True), ("invalid", False)]:
            with self.subTest(mode=mode):
                result, commands, _ = self.run_cleanup(mode, wrong_account=wrong_account)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(commands)

    def test_malformed_log_blocks_deletion(self):
        result, commands, summary = self.run_cleanup("delete", invalid_log=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(commands), 1)
        self.assertIn("Incomplete or failed", summary)


if __name__ == "__main__":
    unittest.main()
