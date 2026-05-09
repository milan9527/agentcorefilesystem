"""Create AgentCore Runtime with hybrid filesystem configuration."""

import boto3
import json

REGION = "us-east-1"
ACCOUNT_ID = "632930644527"

client = boto3.client("bedrock-agentcore-control", region_name=REGION)

try:
    response = client.create_agent_runtime(
        agentRuntimeName="agentcore-fs-demo",
        roleArn=f"arn:aws:iam::{ACCOUNT_ID}:role/agentcore-fs-demo-execution-role",
        networkConfiguration={
            "networkMode": "VPC",
            "networkModeConfig": {
                "subnets": [
                    "subnet-0b1b7db3a6600fbe1",  # us-east-1a
                    "subnet-023880de85fb9261b",  # us-east-1b
                ],
                "securityGroups": ["sg-08d5925d7237c02db"],
            },
        },
        agentRuntimeArtifact={
            "containerConfiguration": {
                "containerUri": f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/bedrock-agentcore-agentcore-fs-demo:latest"
            }
        },
        filesystemConfigurations=[
            # Session Storage - per-session isolated workspace
            {
                "sessionStorage": {
                    "mountPath": "/mnt/workspace",
                }
            },
            # EFS - shared datasets across all sessions
            {
                "efsAccessPoint": {
                    "accessPointArn": f"arn:aws:elasticfilesystem:{REGION}:{ACCOUNT_ID}:access-point/fsap-0c1a42d3983842f9b",
                    "mountPath": "/mnt/datasets",
                }
            },
        ],
    )
    print(json.dumps(response, indent=2, default=str))
    print(f"\n✓ Runtime ARN: {response.get('agentRuntimeArn')}")
except Exception as e:
    print(f"Error: {e}")
    # Try to get existing
    try:
        runtimes = client.list_agent_runtimes()
        for rt in runtimes.get("agentRuntimes", []):
            if rt["agentRuntimeName"] == "agentcore-fs-demo":
                print(f"Existing runtime found: {rt['agentRuntimeArn']}")
                print(f"Status: {rt['status']}")
                break
    except Exception as e2:
        print(f"List error: {e2}")
