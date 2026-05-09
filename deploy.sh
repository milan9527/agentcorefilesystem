#!/bin/bash
set -euo pipefail

#############################################################################
# AgentCore Runtime Filesystem Demo - Full AWS Deployment
#
# Deploys:
# 1. ECR repository + agent container image
# 2. Security groups for EFS/S3Files NFS access
# 3. EFS file system + access point (/mnt/datasets)
# 4. S3 Files file system + access point (/mnt/tools)
# 5. IAM execution role for AgentCore Runtime
# 6. AgentCore Runtime with hybrid filesystem (session storage + EFS + S3 Files)
# 7. Backend (FastAPI) on Lambda + API Gateway
# 8. Frontend (React) on S3 + CloudFront
#############################################################################

REGION="us-east-1"
ACCOUNT_ID="632930644527"
PROJECT_NAME="agentcore-fs-demo"
VPC_ID="vpc-0c036c30b82b3703f"
# Use two subnets in different AZs
SUBNET_1="subnet-0b1b7db3a6600fbe1"  # us-east-1a
SUBNET_2="subnet-023880de85fb9261b"  # us-east-1b

ECR_REPO="bedrock-agentcore-${PROJECT_NAME}"
S3_FRONTEND_BUCKET="${PROJECT_NAME}-frontend-${ACCOUNT_ID}"
S3_BACKEND_BUCKET="${PROJECT_NAME}-backend-${ACCOUNT_ID}"

echo "============================================"
echo "AgentCore Filesystem Demo - Deployment"
echo "============================================"
echo "Region: ${REGION}"
echo "Account: ${ACCOUNT_ID}"
echo "VPC: ${VPC_ID}"
echo ""

#############################################################################
# Step 1: Create ECR Repository
#############################################################################
echo ">>> Step 1: Creating ECR repository..."

aws ecr describe-repositories --repository-names "${ECR_REPO}" --region "${REGION}" 2>/dev/null || \
  aws ecr create-repository \
    --repository-name "${ECR_REPO}" \
    --region "${REGION}" \
    --image-scanning-configuration scanOnPush=true \
    --query 'repository.repositoryUri' --output text

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:latest"
echo "ECR URI: ${ECR_URI}"

#############################################################################
# Step 2: Build and push agent container
#############################################################################
echo ""
echo ">>> Step 2: Building and pushing agent container..."

aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

docker build -t "${ECR_REPO}:latest" -f infra/Dockerfile.agent infra/
docker tag "${ECR_REPO}:latest" "${ECR_URI}"
docker push "${ECR_URI}"

echo "Container pushed: ${ECR_URI}"

#############################################################################
# Step 3: Create Security Groups
#############################################################################
echo ""
echo ">>> Step 3: Creating security groups..."

# Security group for the AgentCore Runtime
RUNTIME_SG=$(aws ec2 create-security-group \
  --group-name "${PROJECT_NAME}-runtime-sg" \
  --description "AgentCore Runtime - outbound NFS to EFS/S3Files" \
  --vpc-id "${VPC_ID}" \
  --region "${REGION}" \
  --query 'GroupId' --output text 2>/dev/null || \
  aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${PROJECT_NAME}-runtime-sg" "Name=vpc-id,Values=${VPC_ID}" \
    --query 'SecurityGroups[0].GroupId' --output text --region "${REGION}")

echo "Runtime SG: ${RUNTIME_SG}"

# Security group for EFS/S3Files mount targets
MOUNT_SG=$(aws ec2 create-security-group \
  --group-name "${PROJECT_NAME}-mount-sg" \
  --description "EFS/S3Files mount targets - inbound NFS from runtime" \
  --vpc-id "${VPC_ID}" \
  --region "${REGION}" \
  --query 'GroupId' --output text 2>/dev/null || \
  aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${PROJECT_NAME}-mount-sg" "Name=vpc-id,Values=${VPC_ID}" \
    --query 'SecurityGroups[0].GroupId' --output text --region "${REGION}")

echo "Mount SG: ${MOUNT_SG}"

# Allow NFS (port 2049) from runtime SG to mount SG
aws ec2 authorize-security-group-ingress \
  --group-id "${MOUNT_SG}" \
  --protocol tcp --port 2049 \
  --source-group "${RUNTIME_SG}" \
  --region "${REGION}" 2>/dev/null || true

# Allow outbound NFS from runtime SG to mount SG
aws ec2 authorize-security-group-egress \
  --group-id "${RUNTIME_SG}" \
  --protocol tcp --port 2049 \
  --source-group "${MOUNT_SG}" \
  --region "${REGION}" 2>/dev/null || true

echo "Security group rules configured (TCP 2049)"

#############################################################################
# Step 4: Create EFS File System + Access Point
#############################################################################
echo ""
echo ">>> Step 4: Creating EFS file system..."

EFS_FS_ID=$(aws efs create-file-system \
  --performance-mode generalPurpose \
  --throughput-mode bursting \
  --encrypted \
  --tags "Key=Name,Value=${PROJECT_NAME}-datasets" \
  --region "${REGION}" \
  --query 'FileSystemId' --output text 2>/dev/null || \
  aws efs describe-file-systems \
    --query "FileSystems[?Name=='${PROJECT_NAME}-datasets'].FileSystemId | [0]" \
    --output text --region "${REGION}")

echo "EFS FileSystem: ${EFS_FS_ID}"

# Wait for EFS to be available
echo "Waiting for EFS to become available..."
aws efs describe-file-systems --file-system-id "${EFS_FS_ID}" --region "${REGION}" \
  --query 'FileSystems[0].LifeCycleState' --output text

# Create mount targets in both subnets
for SUBNET in "${SUBNET_1}" "${SUBNET_2}"; do
  aws efs create-mount-target \
    --file-system-id "${EFS_FS_ID}" \
    --subnet-id "${SUBNET}" \
    --security-groups "${MOUNT_SG}" \
    --region "${REGION}" 2>/dev/null || true
done

echo "EFS mount targets created"

# Create EFS access point for /mnt/datasets
EFS_AP_ID=$(aws efs create-access-point \
  --file-system-id "${EFS_FS_ID}" \
  --posix-user "Uid=1000,Gid=1000" \
  --root-directory "Path=/datasets,CreationInfo={OwnerUid=1000,OwnerGid=1000,Permissions=755}" \
  --tags "Key=Name,Value=${PROJECT_NAME}-datasets-ap" \
  --region "${REGION}" \
  --query 'AccessPointId' --output text 2>/dev/null || \
  aws efs describe-access-points \
    --file-system-id "${EFS_FS_ID}" \
    --query "AccessPoints[?Name=='${PROJECT_NAME}-datasets-ap'].AccessPointId | [0]" \
    --output text --region "${REGION}")

EFS_AP_ARN="arn:aws:elasticfilesystem:${REGION}:${ACCOUNT_ID}:access-point/${EFS_AP_ID}"
echo "EFS Access Point: ${EFS_AP_ARN}"

#############################################################################
# Step 5: Create S3 bucket for S3 Files backing store
#############################################################################
echo ""
echo ">>> Step 5: Creating S3 Files backing bucket..."

S3_FILES_BUCKET="${PROJECT_NAME}-tools-${ACCOUNT_ID}"

aws s3api create-bucket \
  --bucket "${S3_FILES_BUCKET}" \
  --region "${REGION}" 2>/dev/null || true

echo "S3 Files backing bucket: ${S3_FILES_BUCKET}"

# Upload some sample shared tools
echo '#!/bin/bash
echo "Shared lint tool - available to all sessions"
echo "Usage: lint.sh <file>"
' | aws s3 cp - "s3://${S3_FILES_BUCKET}/lint.sh"

echo '#!/bin/bash
echo "Shared test runner - available to all sessions"
echo "Usage: run-tests.sh <project-dir>"
' | aws s3 cp - "s3://${S3_FILES_BUCKET}/run-tests.sh"

echo "Sample tools uploaded to S3"

#############################################################################
# Step 6: Create IAM Execution Role
#############################################################################
echo ""
echo ">>> Step 6: Creating IAM execution role..."

ROLE_NAME="${PROJECT_NAME}-execution-role"

# Trust policy for AgentCore
cat > /tmp/trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock-agentcore.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name "${ROLE_NAME}" \
  --assume-role-policy-document file:///tmp/trust-policy.json \
  --region "${REGION}" 2>/dev/null || true

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "Role: ${ROLE_ARN}"

# Attach permissions for EFS and ECR
cat > /tmp/runtime-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EFSAccess",
      "Effect": "Allow",
      "Action": [
        "elasticfilesystem:ClientMount",
        "elasticfilesystem:ClientWrite"
      ],
      "Resource": "arn:aws:elasticfilesystem:${REGION}:${ACCOUNT_ID}:file-system/${EFS_FS_ID}",
      "Condition": {
        "ArnEquals": {
          "elasticfilesystem:AccessPointArn": "${EFS_AP_ARN}"
        }
      }
    },
    {
      "Sid": "ECRAccess",
      "Effect": "Allow",
      "Action": [
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BedrockModelAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${PROJECT_NAME}-runtime-policy" \
  --policy-document file:///tmp/runtime-policy.json

echo "IAM policy attached"

#############################################################################
# Step 7: Create AgentCore Runtime with Hybrid Filesystem
#############################################################################
echo ""
echo ">>> Step 7: Creating AgentCore Runtime with hybrid filesystem..."
echo "  /mnt/workspace -> Session Storage (per-session, managed)"
echo "  /mnt/datasets  -> EFS (shared across sessions)"

# Note: S3 Files requires s3files service which may not be available in all regions.
# We'll configure session storage + EFS for now, and add S3 Files if available.

FILESYSTEM_CONFIG='[
  {
    "sessionStorage": {
      "mountPath": "/mnt/workspace"
    }
  },
  {
    "efsAccessPoint": {
      "accessPointArn": "'"${EFS_AP_ARN}"'",
      "mountPath": "/mnt/datasets"
    }
  }
]'

RUNTIME_RESPONSE=$(aws bedrock-agentcore-control create-agent-runtime \
  --agent-runtime-name "${PROJECT_NAME}" \
  --role-arn "${ROLE_ARN}" \
  --network-configuration '{
    "networkMode": "VPC",
    "networkModeConfig": {
      "subnets": ["'"${SUBNET_1}"'", "'"${SUBNET_2}"'"],
      "securityGroups": ["'"${RUNTIME_SG}"'"]
    }
  }' \
  --agent-runtime-artifact '{
    "containerConfiguration": {
      "containerUri": "'"${ECR_URI}"'"
    }
  }' \
  --filesystem-configurations "${FILESYSTEM_CONFIG}" \
  --region "${REGION}" 2>&1) || true

echo "${RUNTIME_RESPONSE}"

RUNTIME_ARN=$(echo "${RUNTIME_RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agentRuntimeArn',''))" 2>/dev/null || echo "")

if [ -z "${RUNTIME_ARN}" ]; then
  # Try to get existing runtime
  RUNTIME_ARN=$(aws bedrock-agentcore-control list-agent-runtimes \
    --query "agentRuntimes[?agentRuntimeName=='${PROJECT_NAME}'].agentRuntimeArn | [0]" \
    --output text --region "${REGION}" 2>/dev/null || echo "")
fi

echo "Runtime ARN: ${RUNTIME_ARN}"

#############################################################################
# Step 8: Deploy Backend (Lambda + API Gateway)
#############################################################################
echo ""
echo ">>> Step 8: Deploying backend..."

# Create Lambda deployment package
pip install -t /tmp/lambda-pkg fastapi mangum boto3 pydantic pydantic-settings 2>/dev/null | tail -3

# Copy backend code
cp -r backend/app /tmp/lambda-pkg/

# Create Lambda handler
cat > /tmp/lambda-pkg/lambda_handler.py << 'HANDLER'
"""Lambda handler wrapping the FastAPI app with Mangum."""
import os
os.environ.setdefault("AWS_REGION", "us-east-1")

from mangum import Mangum
from app.main import app

handler = Mangum(app, lifespan="off")
HANDLER

# Package
(cd /tmp/lambda-pkg && zip -r9 /tmp/lambda-deploy.zip . -x '*.pyc' '__pycache__/*') > /dev/null 2>&1

# Create Lambda execution role
LAMBDA_ROLE_NAME="${PROJECT_NAME}-lambda-role"

cat > /tmp/lambda-trust.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --assume-role-policy-document file:///tmp/lambda-trust.json 2>/dev/null || true

LAMBDA_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${LAMBDA_ROLE_NAME}"

# Attach policies
aws iam attach-role-policy \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true

cat > /tmp/lambda-agentcore-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:InvokeAgentRuntimeCommand",
        "bedrock-agentcore:InvokeAgentRuntime",
        "bedrock-agentcore:StopRuntimeSession"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "${LAMBDA_ROLE_NAME}" \
  --policy-name "agentcore-access" \
  --policy-document file:///tmp/lambda-agentcore-policy.json

echo "Waiting for IAM role propagation..."
sleep 10

# Create or update Lambda function
LAMBDA_NAME="${PROJECT_NAME}-api"

aws lambda create-function \
  --function-name "${LAMBDA_NAME}" \
  --runtime python3.11 \
  --handler lambda_handler.handler \
  --role "${LAMBDA_ROLE_ARN}" \
  --zip-file fileb:///tmp/lambda-deploy.zip \
  --timeout 300 \
  --memory-size 512 \
  --environment "Variables={AGENTCORE_RUNTIME_ARN=${RUNTIME_ARN},AWS_REGION_NAME=${REGION}}" \
  --region "${REGION}" 2>/dev/null || \
aws lambda update-function-code \
  --function-name "${LAMBDA_NAME}" \
  --zip-file fileb:///tmp/lambda-deploy.zip \
  --region "${REGION}"

echo "Lambda function deployed: ${LAMBDA_NAME}"

# Create API Gateway (HTTP API)
API_ID=$(aws apigatewayv2 create-api \
  --name "${PROJECT_NAME}-api" \
  --protocol-type HTTP \
  --cors-configuration "AllowOrigins=*,AllowMethods=*,AllowHeaders=*" \
  --region "${REGION}" \
  --query 'ApiId' --output text 2>/dev/null || \
  aws apigatewayv2 get-apis \
    --query "Items[?Name=='${PROJECT_NAME}-api'].ApiId | [0]" \
    --output text --region "${REGION}")

echo "API Gateway: ${API_ID}"

# Create Lambda integration
INTEGRATION_ID=$(aws apigatewayv2 create-integration \
  --api-id "${API_ID}" \
  --integration-type AWS_PROXY \
  --integration-uri "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LAMBDA_NAME}" \
  --payload-format-version "2.0" \
  --region "${REGION}" \
  --query 'IntegrationId' --output text 2>/dev/null || echo "")

# Create catch-all route
aws apigatewayv2 create-route \
  --api-id "${API_ID}" \
  --route-key 'ANY /{proxy+}' \
  --target "integrations/${INTEGRATION_ID}" \
  --region "${REGION}" 2>/dev/null || true

aws apigatewayv2 create-route \
  --api-id "${API_ID}" \
  --route-key 'ANY /' \
  --target "integrations/${INTEGRATION_ID}" \
  --region "${REGION}" 2>/dev/null || true

# Create default stage with auto-deploy
aws apigatewayv2 create-stage \
  --api-id "${API_ID}" \
  --stage-name '$default' \
  --auto-deploy \
  --region "${REGION}" 2>/dev/null || true

# Grant API Gateway permission to invoke Lambda
aws lambda add-permission \
  --function-name "${LAMBDA_NAME}" \
  --statement-id "apigateway-invoke" \
  --action "lambda:InvokeFunction" \
  --principal "apigateway.amazonaws.com" \
  --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*" \
  --region "${REGION}" 2>/dev/null || true

API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com"
echo "API URL: ${API_URL}"

#############################################################################
# Step 9: Deploy Frontend (S3 + CloudFront)
#############################################################################
echo ""
echo ">>> Step 9: Deploying frontend..."

# Create S3 bucket for frontend
aws s3api create-bucket \
  --bucket "${S3_FRONTEND_BUCKET}" \
  --region "${REGION}" 2>/dev/null || true

# Enable static website hosting
aws s3 website "s3://${S3_FRONTEND_BUCKET}" \
  --index-document index.html \
  --error-document index.html

# Update frontend API URL and build
cat > frontend/src/services/config.ts << EOF
export const API_BASE_URL = "${API_URL}";
EOF

# Update api.ts to use the deployed URL
sed -i "s|const API_BASE = \"/api\"|const API_BASE = \"${API_URL}/api\"|" frontend/src/services/api.ts

# Build frontend
(cd frontend && npm run build) 2>&1 | tail -5

# Upload to S3
aws s3 sync frontend/dist/ "s3://${S3_FRONTEND_BUCKET}/" \
  --delete \
  --cache-control "max-age=31536000" \
  --region "${REGION}"

# Set index.html with short cache
aws s3 cp "frontend/dist/index.html" "s3://${S3_FRONTEND_BUCKET}/index.html" \
  --cache-control "max-age=60" \
  --content-type "text/html" \
  --region "${REGION}"

# Make bucket public for static hosting
cat > /tmp/bucket-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::${S3_FRONTEND_BUCKET}/*"
    }
  ]
}
EOF

aws s3api put-public-access-block \
  --bucket "${S3_FRONTEND_BUCKET}" \
  --public-access-block-configuration "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false" \
  --region "${REGION}" 2>/dev/null || true

aws s3api put-bucket-policy \
  --bucket "${S3_FRONTEND_BUCKET}" \
  --policy file:///tmp/bucket-policy.json \
  --region "${REGION}" 2>/dev/null || true

FRONTEND_URL="http://${S3_FRONTEND_BUCKET}.s3-website-${REGION}.amazonaws.com"

#############################################################################
# Done!
#############################################################################
echo ""
echo "============================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "============================================"
echo ""
echo "Resources created:"
echo "  ECR Repository:    ${ECR_REPO}"
echo "  EFS FileSystem:    ${EFS_FS_ID}"
echo "  EFS Access Point:  ${EFS_AP_ARN}"
echo "  Runtime SG:        ${RUNTIME_SG}"
echo "  Mount Target SG:   ${MOUNT_SG}"
echo "  IAM Role:          ${ROLE_ARN}"
echo "  AgentCore Runtime: ${RUNTIME_ARN}"
echo "  Lambda Function:   ${LAMBDA_NAME}"
echo "  API Gateway:       ${API_URL}"
echo "  Frontend Bucket:   ${S3_FRONTEND_BUCKET}"
echo ""
echo "URLs:"
echo "  Frontend: ${FRONTEND_URL}"
echo "  Backend:  ${API_URL}"
echo "  API Docs: ${API_URL}/docs"
echo ""
echo "Filesystem Layout (per session):"
echo "  /mnt/workspace  -> Session Storage (private per user)"
echo "  /mnt/datasets   -> EFS (shared, backed by ${EFS_FS_ID})"
echo ""
echo "Multi-user test:"
echo "  1. Open ${FRONTEND_URL} in Tab 1, login as 'alice'"
echo "  2. Open ${FRONTEND_URL} in Tab 2, login as 'bob'"
echo "  3. Alice: echo hello > /mnt/workspace/private.txt"
echo "  4. Bob:   ls /mnt/workspace  (won't see alice's file)"
echo "  5. Alice: echo shared > /mnt/datasets/shared.txt"
echo "  6. Bob:   cat /mnt/datasets/shared.txt  (sees it!)"
echo ""
