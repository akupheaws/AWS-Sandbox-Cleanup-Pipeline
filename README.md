# Daily AWS sandbox cleanup

Run a daily and on-demand AWS Nuke sweep in a dedicated commercial AWS sandbox. Set up GitHub OIDC and create demo resources in the AWS Management Console. Preview and run the cleanup from GitHub Actions.

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
- `README.md`

Keep the two JSON templates under `iam/` available for the AWS Console steps. You can also include the unchanged templates in the project repository.

## 3. Configure OIDC in the AWS Console

**Get the exact GitHub subject.** In **Actions → Show AWS OIDC Subject → Run workflow**, select the default branch and start the run. Open the run’s **Summary** and copy the subject shown there. The helper reads the token's subject and audience in the runner and reports those values. This works with both GitHub's earlier and immutable subject formats. [GitHub OIDC claims](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)

**Register GitHub as an identity provider.** In the sandbox, go to **IAM → Identity providers → Add provider**, select **OpenID Connect**, enter `https://token.actions.githubusercontent.com` for **Provider URL**, enter `sts.amazonaws.com` for **Audience**, then choose **Add provider**. If the provider exists already, open it and check its audience list. Add `sts.amazonaws.com` if it is missing. [AWS IAM identity provider setup](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)

**Create the role.**

1. Go to **IAM → Roles → Create role → Custom trust policy**. Paste `iam/github-trust-policy.json` in the editor. Replace `SANDBOX_ACCOUNT_ID` with the 12-digit account ID and `GITHUB_OIDC_SUBJECT` with the exact subject from the GitHub run. Retain the JSON quotes and the `StringEquals` conditions.
2. Choose **Next**, select the AWS managed **AdministratorAccess** policy, then **Next**. Enter `GitHubSandboxCleanup` as the role name and choose **Create role**. The broad permissions support scanning and removal across services in this disposable account. Both runnable workflows use this role.
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

1. Open **Actions → AWS Sandbox Cleanup → Run workflow** on the default branch and select `dry-run`. Match the EC2 IDs, bucket and demo role, plus any queues you created, to the run logs. Look for the role under `global`. Confirm the cleanup role and GitHub provider are filtered. Review the full candidate list before enabling deletion.
2. Edit `ENABLE_AWS_DELETION` to `true`. Run **AWS Sandbox Cleanup** manually with `delete`. The sweep can delete other eligible resources in the POC account.
3. Refresh the AWS Console. Both EC2 IDs should show **Terminated** or disappear. The demo VPCs and subnets, the bucket, the demo role, and any queues should disappear from their service lists. SQS deletion can take up to 60 seconds. Run another `dry-run` to confirm OIDC still works. [EC2 termination](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html) · [SQS deletion timing](https://docs.aws.amazon.com/cli/latest/reference/sqs/delete-queue.html)
4. After the next 3:17 a.m. Central window, confirm a run triggered by `schedule` shows `delete` in its summary.

Run cleanup promptly after the demo because EC2 and EBS can incur charges while provisioned. [EC2 pricing](https://aws.amazon.com/ec2/pricing/on-demand/) · [EBS pricing](https://aws.amazon.com/ebs/pricing/)

## Operate the reset

The cron is `17 3 * * *` in `America/Chicago`. Before you enable deletion, it runs a dry run. Manual runs default to `dry-run`. To return future runs to preview mode, set `ENABLE_AWS_DELETION` to `false`. Use **Cancel workflow** for an active run. AWS can still complete requests it already accepted. [GitHub scheduling](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

The sweep uses `regions: [all]` for enabled regions and supported global resources. It preserves IAM users, their login credentials, IAM groups and customer-managed IAM policies, along with GitHub access and AWS Budgets. It targets default VPCs and eligible IAM roles outside the filters. Resource support, AWS retention and disabled regions limit coverage. GitHub can delay or miss scheduled runs. Review Actions scan errors and remaining charges after deployment. [AWS Nuke coverage](https://aws-nuke.ekristen.dev/resources/) · [AWS region behavior](https://docs.aws.amazon.com/accounts/latest/reference/manage-acct-regions.html)
