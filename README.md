# Daily AWS sandbox cleanup

Run a daily and on-demand AWS Nuke sweep in a dedicated commercial AWS sandbox. GitHub Actions runs the job; no permanent server is required. It targets supported lab resources in `us-east-1`, `us-east-2`, `us-west-2`, and global services, while preserving the configured AWS defaults, IAM logins, budgets, and cleanup access.

| Trigger | Behavior |
| --- | --- |
| Manual `dry-run` | Discover eligible resources and list them in the run summary without deleting them. |
| Manual `delete` | Run a fresh preview, then delete eligible resources if discovery passes and `ENABLE_AWS_DELETION=true`. |
| Daily at 3:17 a.m. Central | Preview while deletion is disabled; preview and delete once `ENABLE_AWS_DELETION=true`. |

## 1. Prepare the standalone AWS account

AWS Organizations is optional. Use a dedicated AWS account named POC for the full reset, with its own 12-digit account ID. An IAM user named POC inside an existing account is a login. Resources created by that user belong to the AWS account, and this workflow scans that account. Keep the full sweep disabled if the account contains workloads that must survive. [AWS resource ownership](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference-arns.html)

1. Sign in to the dedicated sandbox as an administrator. Find the account ID in the account menu. In **IAM → Dashboard**, create a unique account alias such as `your-team-poc-sandbox`. AWS Nuke rejects aliases containing `prod`.
2. For IAM-based access, create a group such as `POCDevelopers` and attach policies for the approved lab services. Create individual console users, add each to the group, and enroll MFA. Keep account settings, IAM administration and the cleanup repository under administrator control. [Create IAM groups](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_groups_create.html) · [Create IAM users](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_create.html)
3. In `nuke.yml`, replace the sample account under `accounts` with the sandbox ID. Preserve the quotes. Add IDs that must never be swept to `blocklist`. Leave its sample entry if you have only the standalone account. [AWS Nuke account protections](https://aws-nuke.ekristen.dev/warning/)

## 2. Add the project to GitHub

Create a private repository initialized with a README. Keep write access with administrators and protect its default branch where available. From the repository root, use **Add file → Create new file** to copy contents from the extracted starter kit into each path below. Enter the whole path including slashes so GitHub creates the directories. Edit the initial README to replace it with this one. Commit the files to the default branch or merge the branch containing them. [Create files in GitHub](https://docs.github.com/en/repositories/working-with-files/managing-files/creating-new-files)

In macOS Finder, press **Command+Shift+Period** to reveal hidden files.

- `.github/workflows/aws-sandbox-cleanup.yml`
- `.github/workflows/show-oidc-subject.yml`
- `nuke.yml`
- `scripts/cleanup.sh`
- `scripts/cleanup_report.py`
- `tests/test_cleanup.py`
- `README.md`

Keep the two JSON templates under `iam/` available for the AWS Console steps. You can also include the unchanged templates in the project repository.

## 3. Configure OIDC in the AWS Console

**Get the exact GitHub subject.** In **Actions → Show AWS OIDC Subject → Run workflow**, select the default branch and start the run. Open the run’s **Summary** and copy the subject shown there. The helper reads the token's subject and audience in the runner and reports those values. This works with both GitHub's earlier and immutable subject formats. [GitHub OIDC claims](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)

**Register GitHub as an identity provider.** In the sandbox, go to **IAM → Identity providers → Add provider**, select **OpenID Connect**, enter `https://token.actions.githubusercontent.com` for **Provider URL**, enter `sts.amazonaws.com` for **Audience**, then choose **Add provider**. If the provider exists already, open it and check its audience list. Add `sts.amazonaws.com` if it is missing. [AWS IAM identity provider setup](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)

**Create the role.**

1. Go to **IAM → Roles → Create role → Custom trust policy**. Paste `iam/github-trust-policy.json` in the editor. Replace `SANDBOX_ACCOUNT_ID` with the 12-digit account ID and `GITHUB_OIDC_SUBJECT` with the exact subject from the GitHub run. Retain the JSON quotes and the `StringEquals` conditions.
2. Choose **Next**, select the AWS managed **AdministratorAccess** policy, then **Next**. Enter `GitHubSandboxCleanup` as the role name and choose **Create role**. The broad permissions support scanning and removal across services in this disposable account. The cleanup workflow uses this role.
3. Open the role. Under **Summary → Edit**, set **Maximum session duration** to **2 hours** (7,200 seconds) and save.
4. On the role’s **Permissions** tab, choose **Add permissions → Create inline policy → JSON**. Paste `iam/cleanup-guardrails.json`. Choose **Next**, name it `ProtectSandboxAccess`, and create it. This policy explicitly denies selected changes to the role, OIDC provider and account controls.

[Create a role with custom trust](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-custom.html) · [IAM maximum session duration](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_update-role-settings.html) · [GitHub OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)

**Set GitHub variables.** Go to **Settings → Secrets and variables → Actions → Variables → New repository variable**.

| Name | Initial value |
| --- | --- |
| `AWS_SANDBOX_ACCOUNT_ID` | The same 12-digit ID as `nuke.yml` and the role trust |
| `ENABLE_AWS_DELETION` | `false` |

GitHub assumes the role using OIDC and gets temporary credentials from AWS STS. The workflow already requests the required GitHub token permission and checks the returned AWS account. [GitHub repository variables](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables)

## 4. Create demo resources in the AWS Console

Keep `ENABLE_AWS_DELETION=false` while setting up the demo. Use only disposable resources in the POC account.

1. In both `us-east-1` and `us-west-2`, open **VPC → Your VPCs → Create VPC**, select **VPC only**, and create `poc-demo-vpc` with IPv4 CIDR `10.0.0.0/24`. Then open **VPC → Subnets → Create subnet**, choose the new VPC, and create `poc-demo-subnet` with IPv4 CIDR `10.0.0.0/26`. Record the VPC and subnet IDs. [Create a VPC](https://docs.aws.amazon.com/vpc/latest/userguide/create-vpc.html) · [Create a subnet](https://docs.aws.amazon.com/vpc/latest/userguide/create-subnets.html)
2. In **EC2 → Instances → Launch instances**, launch one Amazon Linux 2023 (64-bit x86) `t3.micro` in each region. Name them `poc-demo-east` and `poc-demo-west`. Choose **Proceed without a key pair**. Under **Network settings → Edit**, choose the demo VPC and subnet, disable **Auto-assign public IP**, and select that VPC’s default security group. Under **Configure storage → Advanced**, confirm **Delete on termination** is **Yes** for the root volume. Record both instance IDs. [EC2 launch settings](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-launch-parameters.html)
3. In **S3 → General purpose buckets → Create bucket**, choose `us-east-1`, use a unique name such as `poc-demo-unique-suffix`, and keep **Block all public access** enabled. Leave the bucket empty and record its name. [Create an S3 bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/create-bucket-overview.html)
4. In **IAM → Roles → Create role**, choose **AWS service → Lambda** and the basic **Lambda** use case. Continue without attaching any permissions policy, name the role `POC-Cleanup-DemoRole`, and create it. IAM is global. [Create an IAM service role](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-service.html)
5. For an optional messaging example, go to **SQS → Create queue** and create an empty standard queue named `poc-demo-queue` in each region. [Create an SQS queue](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/creating-sqs-standard-queues.html)

## 5. Preview, delete, and verify

1. Open **Actions → AWS Sandbox Cleanup → Run workflow** on the default branch and select `dry-run`. Review the **Preview** candidate table in the run summary and match the EC2 IDs, bucket and demo role, plus any queues you created. Check the **Preserved default resources** table for the default VPCs and networking components. Look for the role under `global` in the logs. Confirm the cleanup role and GitHub provider are filtered. Review all candidates before enabling deletion.
2. Edit `ENABLE_AWS_DELETION` to `true`. Run **AWS Sandbox Cleanup** manually with `delete`. It performs a fresh preview before deletion; unexpected discovery errors in that preview block deletion. It rescans when deleting, so it can also remove eligible resources created since an earlier preview. New errors during deletion can leave a partially cleaned account and fail the run. The **Deletion** summary reports the outcome.
3. Refresh the AWS Console. Both EC2 IDs should show **Terminated** or disappear. The demo VPCs and subnets, the bucket, the demo role, and any queues should disappear from their service lists. SQS deletion can take up to 60 seconds. Run another `dry-run` to confirm OIDC still works. [EC2 termination](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html) · [SQS deletion timing](https://docs.aws.amazon.com/cli/latest/reference/sqs/delete-queue.html)
4. After the next 3:17 a.m. Central window, confirm a run triggered by `schedule` shows `delete` in its summary.

Run cleanup promptly after the demo because EC2 and EBS can incur charges while provisioned. [EC2 pricing](https://aws.amazon.com/ec2/pricing/on-demand/) · [EBS pricing](https://aws.amazon.com/ebs/pricing/)

## Operate the reset

The cron is `17 3 * * *` in `America/Chicago`. Before you enable deletion, it runs a dry run. Manual runs default to `dry-run`. To return future runs to preview mode, set `ENABLE_AWS_DELETION` to `false`. Use **Cancel workflow** for an active run. AWS can still complete requests it already accepted. [GitHub scheduling](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

The sweep is limited to `global`, `us-east-1`, `us-east-2`, and `us-west-2`. Resources created by any engineer in this account are eligible; ownership tags or a particular IAM username are not required. Other regions are outside this cleanup scope.

The preserved baseline includes the default VPC, default subnets, its internet gateway and attachment, default DHCP options, default security-group rules, and the primary Athena workgroup. AWS Nuke also skips built-in resources that AWS does not allow it to delete, such as main route tables, default network ACLs, default security groups, and predefined service configurations. An EC2 instance, custom security group, or other workload inside a default VPC is still eligible. This preserves default resources; it does not revert changes made to them. The explicit baseline rules are in `nuke.yml`; custom resources merely named `default` are not a universal exception. [AWS Nuke resource behavior](https://github.com/ekristen/aws-nuke/tree/v3.69.1/resources)

IAM users, credentials, groups, customer-managed policies, password policy, the named access roles and their policies, the GitHub OIDC provider, the named bootstrap stack, SSO providers, and AWS Budgets remain protected by the configuration. AWS Nuke's default behavior also preserves service-linked and SSO roles. Other eligible IAM roles are removed. A stack filter does not automatically protect every child resource from direct cleanup; baseline resources need their own applicable filters.

Engineer-created CloudWatch log groups and Resource Explorer indexes/views are eligible; the configuration does not preserve all resources in those categories. S3 buckets and their contents, including object versions, are also eligible.

Some service APIs return account-enrollment or subscription errors even when there are no resources to clean. `scripts/cleanup_report.py` recognizes specific discovery responses for Cloud9, CloudSearch, Cloud Directory, legacy Amazon ML, Timestream for LiveAnalytics, disabled Glue development endpoints, Shield, and Firewall Manager. It also identifies the absent Q Business endpoint and the specific unavailable Bedrock customization operations in Ohio. These checks remain visible as warnings and as a table of unavailable service checks in the run summary; they are not reported as deleted resources. Each scan still attempts them, so services that become available can be cleaned. Other permission, network, discovery, queue-overflow, and deletion failures fail the job. A nonzero AWS Nuke exit code always fails it.

Retired service handlers, including Lex V1, are excluded. The pinned AWS Nuke release still calls the retired AgentCore registry preview API, so `BedrockAgentCoreRegistry` and `BedrockAgentCoreRegistryRecord` are excluded too. The replacement **AWS Agent Registry is outside this release's cleanup coverage**. [Lex V1 retirement](https://docs.aws.amazon.com/lex/latest/dg/lex-dg.pdf) · [Registry API migration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-iam-permissions.html) · [Q Business regions](https://docs.aws.amazon.com/general/latest/gr/amazonq.html)

Resource support, AWS retention, permissions, and the configured regions limit coverage. GitHub can delay or miss scheduled runs. Review the run summary, errors, and remaining charges after deployment. [AWS Nuke coverage](https://aws-nuke.ekristen.dev/resources/)

Run the local checks with `bash -n scripts/cleanup.sh` and `python3 -m unittest discover -s tests -v`. The workflow runs these checks and parses `nuke.yml` with `aws-nuke explain-config --account-id "$AWS_SANDBOX_ACCOUNT_ID" --config nuke.yml` before assuming the cleanup role.
