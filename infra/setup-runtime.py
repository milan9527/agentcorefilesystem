"""Infrastructure setup script for AgentCore Runtime with hybrid filesystem.

This script creates an AgentCore Runtime configured with all three filesystem
types in hybrid mode:
- Session Storage: /mnt/workspace (per-session, managed)
- EFS Access Point: /mnt/datasets (shared, bring-your-own)
- S3 Files Access Point: /mnt/tools (shared, bring-your-own)

Prerequisites:
- AWS credentials configured
- VPC with subnets and security groups
- EFS file system with access point
- S3 Files file system with access point
- IAM execution role with required permissions

Usage:
    python setup-runtime.py

Environment variables:
    AWS_REGION: AWS region (default: us-west-2)
    ACCOUNT_ID: AWS account ID
    CONTAINER_URI: ECR container URI for the agent
    EXECUTION_ROLE_ARN: IAM role ARN for the runtime
    SUBNET_1, SUBNET_2: VPC subnet IDs
    SECURITY_GROUP: Security group ID
    EFS_ACCESS_POINT_ARN: EFS access point ARN
    S3FILES_ACCESS_POINT_ARN: S3 Files access point ARN
"""

import json
import os

import boto3

# Configuration from environment
REGION = os.environ.get("AWS_REGION", "us-west-2")
ACCOUNT_ID = os.environ.get("ACCOUNT_ID", "111122223333")
CONTAINER_URI = os.environ.get(
    "CONTAINER_URI",
    f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/coding-agent:latest",
)
EXECUTION_ROLE_ARN = os.environ.get(
    "EXECUTION_ROLE_ARN",
    f"arn:aws:iam::{ACCOUNT_ID}:role/AgentCoreExecutionRole",
)
SUBNET_1 = os.environ.get("SUBNET_1", "subnet-0123456789abcdef0")
SUBNET_2 = os.environ.get("SUBNET_2", "subnet-0123456789abcdef1")
SECURITY_GROUP = os.environ.get("SECURITY_GROUP", "sg-0123456789abcdef0")
EFS_ACCESS_POINT_ARN = os.environ.get(
    "EFS_ACCESS_POINT_ARN",
    f"arn:aws:elasticfilesystem:{REGION}:{ACCOUNT_ID}:access-point/fsap-0123456789abcdef0",
)
S3FILES_ACCESS_POINT_ARN = os.environ.get(
    "S3FILES_ACCESS_POINT_ARN",
    f"arn:aws:s3files:{REGION}:{ACCOUNT_ID}:file-system/fs-0123456789abcdef0/access-point/ap-0123456789abcdef0",
)


def create_hybrid_runtime():
    """Create an AgentCore Runtime with hybrid filesystem configuration.

    Combines all three storage types:
    1. Session Storage at /mnt/workspace - isolated per session
    2. EFS at /mnt/datasets - shared datasets
    3. S3 Files at /mnt/tools - shared tools synced with S3
    """
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    print("Creating AgentCore Runtime with hybrid filesystem...")
    print(f"  Region: {REGION}")
    print(f"  Container: {CONTAINER_URI}")
    print(f"  Role: {EXECUTION_ROLE_ARN}")
    print()
    print("Filesystem Configuration:")
    print(f"  /mnt/workspace -> Session Storage (managed, per-session)")
    print(f"  /mnt/datasets  -> EFS ({EFS_ACCESS_POINT_ARN})")
    print(f"  /mnt/tools     -> S3 Files ({S3FILES_ACCESS_POINT_ARN})")
    print()

    response = client.create_agent_runtime(
        agentRuntimeName="coding-agent-hybrid-storage",
        roleArn=EXECUTION_ROLE_ARN,
        # VPC required for BYO filesystems (EFS, S3 Files)
        networkConfiguration={
            "networkMode": "VPC",
            "networkModeConfig": {
                "subnets": [SUBNET_1, SUBNET_2],
                "securityGroups": [SECURITY_GROUP],
            },
        },
        # Container with dev tools (git, node, python, etc.)
        agentRuntimeArtifact={
            "containerConfiguration": {"containerUri": CONTAINER_URI}
        },
        # Hybrid filesystem: Session Storage + EFS + S3 Files
        filesystemConfigurations=[
            # 1. Session Storage - per-session isolated workspace
            #    Each user's session gets its own private workspace.
            #    Data persists across stop/resume cycles.
            #    Resets after 14 days idle or runtime version update.
            {
                "sessionStorage": {
                    "mountPath": "/mnt/workspace",
                }
            },
            # 2. EFS - shared datasets across all sessions
            #    All users/sessions see the same data.
            #    Full POSIX semantics, concurrent read-write.
            #    Permanent until you delete it.
            {
                "efsAccessPoint": {
                    "accessPointArn": EFS_ACCESS_POINT_ARN,
                    "mountPath": "/mnt/datasets",
                }
            },
            # 3. S3 Files - shared tools synced with S3 bucket
            #    All users/sessions see the same tools.
            #    Bidirectional sync with backing S3 bucket.
            #    Accessible via both NFS and S3 APIs.
            {
                "s3FilesAccessPoint": {
                    "accessPointArn": S3FILES_ACCESS_POINT_ARN,
                    "mountPath": "/mnt/tools",
                }
            },
        ],
    )

    runtime_arn = response.get("agentRuntimeArn")
    print(f"✓ Runtime created successfully!")
    print(f"  ARN: {runtime_arn}")
    print()
    print("Next steps:")
    print("  1. Wait for runtime to become ACTIVE")
    print("  2. Set AGENTCORE_RUNTIME_ARN in backend/.env")
    print("  3. Start the backend: cd backend && uvicorn app.main:app --port 8000")
    print("  4. Start the frontend: cd frontend && npm run dev")
    print()
    print("Multi-user usage:")
    print("  - User A creates session -> gets private /mnt/workspace")
    print("  - User B creates session -> gets different private /mnt/workspace")
    print("  - Both users see the SAME /mnt/datasets (EFS) and /mnt/tools (S3)")
    print()

    return response


def print_iam_policy():
    """Print the required IAM policy for the execution role."""
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "EFSAccess",
                "Effect": "Allow",
                "Action": [
                    "elasticfilesystem:ClientMount",
                    "elasticfilesystem:ClientWrite",
                ],
                "Resource": f"arn:aws:elasticfilesystem:{REGION}:{ACCOUNT_ID}:file-system/*",
                "Condition": {
                    "ArnEquals": {
                        "elasticfilesystem:AccessPointArn": EFS_ACCESS_POINT_ARN
                    }
                },
            },
            {
                "Sid": "S3FilesAccess",
                "Effect": "Allow",
                "Action": [
                    "s3files:ClientMount",
                    "s3files:ClientWrite",
                    "s3files:GetAccessPoint",
                ],
                "Resource": f"arn:aws:s3files:{REGION}:{ACCOUNT_ID}:file-system/*",
                "Condition": {
                    "ArnEquals": {
                        "s3files:AccessPointArn": S3FILES_ACCESS_POINT_ARN
                    }
                },
            },
        ],
    }

    print("Required IAM Policy for Execution Role:")
    print(json.dumps(policy, indent=2))
    print()


def print_security_group_rules():
    """Print required security group rules."""
    print("Required Security Group Rules:")
    print()
    print("Agent Runtime Security Group (outbound):")
    print("  - TCP 2049 -> EFS Mount Target SG")
    print("  - TCP 2049 -> S3 Files Mount Target SG")
    print()
    print("EFS Mount Target Security Group (inbound):")
    print("  - TCP 2049 <- Agent Runtime SG")
    print()
    print("S3 Files Mount Target Security Group (inbound):")
    print("  - TCP 2049 <- Agent Runtime SG")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("AgentCore Runtime - Hybrid Filesystem Setup")
    print("=" * 60)
    print()

    print_iam_policy()
    print_security_group_rules()

    confirm = input("Create the runtime? (y/N): ").strip().lower()
    if confirm == "y":
        create_hybrid_runtime()
    else:
        print("Aborted. Set environment variables and run again.")
