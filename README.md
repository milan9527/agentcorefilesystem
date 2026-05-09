# AgentCore Runtime Filesystem Demo

A full-stack demo showcasing **Amazon Bedrock AgentCore Runtime** hybrid filesystem configurations with multi-user shell access.

## Live URLs

- **Frontend**: https://d190psp42zgs69.cloudfront.net
- **Backend API**: https://v11opo7s17.execute-api.us-east-1.amazonaws.com
- **API Health**: https://v11opo7s17.execute-api.us-east-1.amazonaws.com/health

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│              AgentCore Runtime (per-session microVM)                 │
│                                                                     │
│  /mnt/workspace  ← Session Storage (isolated per user/session)      │
│  /mnt/datasets   ← EFS Access Point (shared across all sessions)    │
│  /mnt/tools      ← S3 Files Access Point (shared, synced with S3)   │
│                                                                     │
│  Shell access via InvokeAgentRuntimeCommand API                     │
└─────────────────────────────────────────────────────────────────────┘
         ▲                              ▲
         │                              │
┌────────┴────────┐            ┌────────┴────────┐
│  User A Session │            │  User B Session │
│  (own workspace)│            │  (own workspace)│
│  sees shared EFS│            │  sees shared EFS│
└─────────────────┘            └─────────────────┘
         ▲                              ▲
         │         ┌──────────┐         │
         └─────────┤ Backend  ├─────────┘
                   │ (Lambda) │
                   └────┬─────┘
                        │
                   ┌────┴─────┐
                   │ Frontend │
                   │ (S3/Web) │
                   └──────────┘
```

## Storage Modes (Hybrid)

| Mount Path | Type | Scope | Use Case |
|---|---|---|---|
| `/mnt/workspace` | Session Storage | Per-user session (isolated) | Code files, project state |
| `/mnt/datasets` | Amazon EFS | Shared across all sessions | Datasets, shared data |
| `/mnt/tools` | Amazon S3 Files | Shared across all sessions | Shared tools, synced with S3 |

## Multi-User Isolation (Verified)

```
Alice writes: /mnt/workspace/alice.txt     → Only Alice sees it
Alice writes: /mnt/datasets/shared.csv     → Bob also sees it
Bob writes:   /mnt/datasets/bob-shared.txt → Alice also sees it
Bob reads:    /mnt/workspace/              → Empty (can't see Alice's files)
```

## AWS Resources Deployed

| Resource | ID/ARN |
|---|---|
| AgentCore Runtime | `agentcore_fs_demo-vQv834FKFx` |
| ECR Repository | `bedrock-agentcore-agentcore-fs-demo` |
| EFS File System | `fs-06f39f3fbb48c23b4` |
| EFS Access Point | `fsap-0c1a42d3983842f9b` |
| Runtime Security Group | `sg-08d5925d7237c02db` |
| Mount Target Security Group | `sg-082c3d1739ac21ddd` |
| Lambda Function | `agentcore-fs-demo-api` |
| API Gateway | `v11opo7s17` |
| Frontend S3 Bucket | `agentcore-fs-demo-frontend-632930644527` (private, no public access) |
| CloudFront Distribution | `E3N0RR1E8EANGW` (`d190psp42zgs69.cloudfront.net`) |
| IAM Runtime Role | `agentcore-fs-demo-execution-role` |
| IAM Lambda Role | `agentcore-fs-demo-lambda-role` |
| S3 Files File System | `fs-000cb2840061e04fa` |
| S3 Files Access Point | `fsap-042e1a297141bb8f0` |
| S3 Files Backing Bucket | `agentcore-fs-demo-tools-632930644527` |
| S3 Files IAM Role | `agentcore-fs-demo-s3files-role` |

## How It Works

1. **User logs in** via the frontend → creates a session with a unique ID
2. **Session creation** invokes the agent (`InvokeAgentRuntime`) to provision the microVM
3. **Shell commands** are executed via `InvokeAgentRuntimeCommand` in the same session
4. **Each session** gets its own isolated `/mnt/workspace` (session storage)
5. **All sessions** share the same `/mnt/datasets` (EFS mount)
6. **Stopping a session** persists workspace data; resuming restores it

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/api/sessions/create` | Create/resume a user session |
| POST | `/api/sessions/stop` | Stop session (persists storage) |
| GET | `/api/sessions/active` | List active sessions |
| POST | `/api/shell/execute` | Execute shell command in session |
| POST | `/api/files/list` | List files at a path |
| POST | `/api/files/read` | Read a file |
| POST | `/api/files/write` | Write a file |
| POST | `/api/files/storage-info` | Get storage usage info |

## Local Development

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Cleanup

```bash
# Stop all active sessions first
# Then delete resources:
aws lambda delete-function --function-name agentcore-fs-demo-api
aws apigatewayv2 delete-api --api-id v11opo7s17
aws cloudfront delete-distribution --id E3N0RR1E8EANGW --if-match <ETAG>
aws s3 rb s3://agentcore-fs-demo-frontend-632930644527 --force
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id agentcore_fs_demo-vQv834FKFx
aws efs delete-access-point --access-point-id fsap-0c1a42d3983842f9b
aws efs delete-mount-target --mount-target-id fsmt-0444dbee01ff489ed
aws efs delete-mount-target --mount-target-id fsmt-03d8540b8dc7ef94a
aws efs delete-file-system --file-system-id fs-06f39f3fbb48c23b4
aws ecr delete-repository --repository-name bedrock-agentcore-agentcore-fs-demo --force
```
