# AgentCore Runtime Persistent Storage & File System Guide

## Overview

Amazon Bedrock AgentCore Runtime provides persistent file system capabilities that allow AI agents to maintain state across sessions. This document describes the three storage options, their architectures, per-user isolation patterns, and the recommended hybrid solution.

AgentCore Runtime supports mounting file systems into the microVM at paths under `/mnt/`. The runtime handles all mount operations automatically — no custom mount code, privileged containers, or download orchestration required.

---

## Storage Options

| Feature | Session Storage | Amazon EFS | Amazon S3 Files |
|---------|----------------|------------|-----------------|
| Category | Managed | Bring-your-own | Bring-your-own |
| Scope | Per-session (isolated) | Shared across sessions | Shared across sessions |
| Persistence | Survives stop/resume; 14-day idle expiry | Permanent (customer-managed) | Permanent (syncs to S3 bucket) |
| VPC Required | No | Yes | Yes |
| Protocol | Service-managed | NFSv4.1 over TLS | NFSv4.2 over TLS |
| Max per runtime | 1 | 2 | 2 |
| Consistency | Local filesystem | Close-to-open | Close-to-open (NFS); eventual (S3 side) |

---

## Solution 1: Managed Session Storage

### Architecture

Session Storage is a fully managed capability where AgentCore handles all storage operations transparently. Each session gets its own isolated persistent directory.

```
┌──────────────────────────────────────────────────┐
│            AgentCore Runtime MicroVM              │
│                                                  │
│   Agent Process                                  │
│     │                                            │
│     ▼                                            │
│   /mnt/workspace  (local filesystem)             │
│     │                                            │
│     ▼  (async replication)                       │
│   AgentCore Managed Durable Storage              │
└──────────────────────────────────────────────────┘
```

**How the agent accesses persistent files:**

1. Agent reads/writes to `/mnt/workspace` using standard file operations (`open`, `read`, `write`, `mkdir`).
2. Data is asynchronously replicated to AgentCore-managed durable storage.
3. On session stop, pending data is flushed during graceful shutdown.
4. On resume (same `runtimeSessionId`), file system state is restored from durable storage.

**Configuration:**

```json
{
  "filesystemConfigurations": [
    {
      "sessionStorage": {
        "mountPath": "/mnt/workspace"
      }
    }
  ]
}
```

**Characteristics:**
- Zero infrastructure setup — no VPC, no IAM for storage
- Isolated per session — no cross-session data leakage
- Standard POSIX operations: `ls`, `git`, `npm`, `pip` all work
- Data resets after 14 days idle or on runtime version update

---

## Solution 2: Amazon EFS (Elastic File System)

### Architecture

EFS provides a shared POSIX-compliant file system accessible by all sessions simultaneously via NFS mount targets in your VPC.

```
┌─────────────────────────────────────────────────────────────┐
│                         Your VPC                            │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐                      │
│  │  MicroVM A   │    │  MicroVM B   │                      │
│  │  (Session 1) │    │  (Session 2) │                      │
│  │  /mnt/data ──┼──┐ │  /mnt/data ──┼──┐                  │
│  └──────────────┘  │ └──────────────┘  │                   │
│                    │                    │                   │
│                    ▼                    ▼                   │
│              ┌──────────────────────────────┐              │
│              │   EFS Mount Target (AZ-a)    │              │
│              │   EFS Mount Target (AZ-b)    │              │
│              └──────────────┬───────────────┘              │
│                             │                              │
│                             ▼                              │
│              ┌──────────────────────────────┐              │
│              │     Amazon EFS File System    │              │
│              │     (Access Point: /data)     │              │
│              └──────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

**How the agent accesses persistent files:**

1. AgentCore mounts the EFS access point via NFSv4.1 over TLS (port 2049) using IAM authentication.
2. Agent reads/writes to the mount path using standard file operations.
3. All sessions see the same data — changes are immediately visible to other sessions (close-to-open consistency).
4. Data persists permanently until explicitly deleted.

**Configuration:**

```json
{
  "filesystemConfigurations": [
    {
      "efsAccessPoint": {
        "accessPointArn": "arn:aws:elasticfilesystem:<region>:<account>:access-point/<ap-id>",
        "mountPath": "/mnt/datasets"
      }
    }
  ]
}
```

**IAM permissions required on execution role:**

```json
{
  "Effect": "Allow",
  "Action": [
    "elasticfilesystem:ClientMount",
    "elasticfilesystem:ClientWrite"
  ],
  "Resource": "arn:aws:elasticfilesystem:<region>:<account>:file-system/<fs-id>",
  "Condition": {
    "ArnEquals": {
      "elasticfilesystem:AccessPointArn": "<access-point-arn>"
    }
  }
}
```

**Characteristics:**
- Full POSIX semantics: hard links, symlinks, advisory file locking
- Concurrent read-write from multiple sessions
- Elastic capacity — grows/shrinks automatically
- Requires VPC with mount targets in same AZ as runtime subnets
- Security group must allow TCP 2049

---

## Solution 3: Amazon S3 Files

### Architecture

S3 Files provides a file system interface backed by an S3 bucket with bidirectional sync. Data is accessible both via NFS mount and standard S3 APIs.

```
┌─────────────────────────────────────────────────────────────┐
│                         Your VPC                            │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐                      │
│  │  MicroVM A   │    │  MicroVM B   │                      │
│  │  (Session 1) │    │  (Session 2) │                      │
│  │  /mnt/tools──┼──┐ │  /mnt/tools──┼──┐                  │
│  └──────────────┘  │ └──────────────┘  │                   │
│                    │                    │                   │
│                    ▼                    ▼                   │
│              ┌──────────────────────────────┐              │
│              │  S3 Files Mount Target (AZ)  │              │
│              └──────────────┬───────────────┘              │
│                             │                              │
│                             ▼                              │
│              ┌──────────────────────────────┐              │
│              │   S3 Files File System        │              │
│              │   (Access Point: /tools)      │              │
│              └──────────────┬───────────────┘              │
└─────────────────────────────┼───────────────────────────────┘
                              │ bidirectional sync
                              ▼
                ┌──────────────────────────────┐
                │      Amazon S3 Bucket         │
                │  (s3://my-tools-bucket/)      │
                └──────────────────────────────┘
```

**How the agent accesses persistent files:**

1. AgentCore mounts the S3 Files access point via NFSv4.2 over TLS (port 2049) with mandatory IAM authentication.
2. Agent reads/writes to the mount path using standard file operations.
3. Changes sync bidirectionally to the backing S3 bucket.
4. External systems can also read/write via S3 APIs — changes propagate to the NFS mount.

**Configuration:**

```json
{
  "filesystemConfigurations": [
    {
      "s3FilesAccessPoint": {
        "accessPointArn": "arn:aws:s3files:<region>:<account>:file-system/<fs-id>/access-point/<ap-id>",
        "mountPath": "/mnt/tools"
      }
    }
  ]
}
```

**IAM permissions required on execution role:**

```json
{
  "Effect": "Allow",
  "Action": [
    "s3files:ClientMount",
    "s3files:ClientWrite",
    "s3files:GetAccessPoint"
  ],
  "Resource": "arn:aws:s3files:<region>:<account>:file-system/<fs-id>",
  "Condition": {
    "ArnEquals": {
      "s3files:AccessPointArn": "<access-point-arn>"
    }
  }
}
```

**Characteristics:**
- Bidirectional sync between NFS and S3
- Dual access: file system operations + S3 APIs
- Requires versioning enabled on backing bucket
- Close-to-open consistency for NFS; eventual consistency for S3 side
- Max file size: 48 TiB
- Requires VPC with mount targets

---

## Per-User Isolation with Access Points

### The Challenge

When multiple users share an agent runtime, you need to control who can access what data. Each storage type offers different isolation mechanisms.

### Session Storage: Built-in Isolation

Session Storage is inherently isolated — each `runtimeSessionId` gets its own private file system. No additional configuration needed.

```
User Alice (session-alice-001) → /mnt/workspace → [Alice's private files]
User Bob   (session-bob-001)   → /mnt/workspace → [Bob's private files]
```

Alice cannot see Bob's workspace and vice versa. This is enforced by the service.

### EFS: Per-User Access Points

EFS supports multiple access points on a single file system. Each access point can enforce a different root directory and POSIX identity.

```
EFS File System: fs-abc123
├── Access Point 1: /users/alice  (UID: 1001, GID: 1001)
├── Access Point 2: /users/bob    (UID: 1002, GID: 1002)
└── Access Point 3: /shared       (UID: 0, GID: 0)
```

**Per-user pattern:**
- Create one access point per user with `rootDirectory: /users/<user-id>`
- Each user's agent runtime references their specific access point ARN
- The access point enforces the root directory — the user cannot navigate above it

**Limitation:** You'd need a separate agent runtime (or dynamic runtime updates) per user since the access point ARN is configured at runtime creation time. This is impractical for multi-tenant scenarios with many users.

### S3 Files: Per-User Access Points

Same pattern as EFS — create per-user access points with different root directories:

```
S3 Files File System: fs-xyz789 (backed by s3://my-bucket)
├── Access Point 1: /users/alice  → s3://my-bucket/users/alice/
├── Access Point 2: /users/bob    → s3://my-bucket/users/bob/
└── Access Point 3: /shared       → s3://my-bucket/shared/
```

**Same limitation applies:** Access points are bound at runtime creation time.

### Practical Multi-User Isolation

For true multi-user isolation without per-user runtimes, the recommended approach is:

| Need | Solution |
|------|----------|
| Private per-user data | Session Storage (automatic isolation) |
| Shared read-only data | Single EFS/S3 Files access point (all users share) |
| Per-user persistent data beyond session lifecycle | Application-level isolation within shared EFS (e.g., `/mnt/data/<user-id>/`) |

---

## Comparison

| Criteria | Session Storage | EFS | S3 Files |
|----------|----------------|-----|----------|
| **Setup complexity** | None | Medium (VPC, mount targets, SG rules) | Medium-High (VPC, mount targets, SG, bucket, versioning) |
| **Per-user isolation** | Built-in | Requires access points or app-level | Requires access points or app-level |
| **Data sharing** | Not possible | Native (all sessions see same data) | Native (all sessions + S3 API access) |
| **External access** | None | Via NFS mount from EC2/ECS | Via S3 APIs from anywhere |
| **Performance** | High (local-like) | High (NFS, elastic throughput) | Good (NFS + S3 sync latency) |
| **Cost** | Included in AgentCore | EFS pricing (per GB stored + throughput) | S3 pricing + S3 Files pricing |
| **Durability** | Service-managed (14-day expiry) | Customer-managed (permanent) | Customer-managed (permanent, S3 durability) |
| **Max capacity** | Service limits | Petabyte-scale | 48 TiB per file |
| **Concurrent access** | Single session only | Multiple sessions + external | Multiple sessions + S3 clients |
| **Use case** | Agent workspace, installed packages, project state | Shared datasets, multi-agent collaboration | Shared tools, S3 pipeline integration |

---

## Recommended Hybrid Solution: Session Storage + EFS + S3 Files

The best architecture for multi-user agent applications combines **Session Storage for private data**, **EFS for truly shared data**, and **S3 Files for shared tools with external access**.

This is the architecture deployed in the current demo.

### Why This Combination

- **Session Storage** gives each user automatic isolation without any infrastructure setup. Perfect for code, packages, git repos, and agent state.
- **EFS** provides a single shared namespace for data that genuinely needs to be accessed by all users — datasets, reference materials, shared analysis results.
- **S3 Files** adds shared tool storage with bidirectional S3 sync — external systems (Lambda, Glue, CI/CD) can push tools into the bucket and agents see them immediately via NFS.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AgentCore Runtime                                 │
│                                                                     │
│  ┌─────────────────────┐         ┌─────────────────────┐           │
│  │   User Alice         │         │   User Bob           │           │
│  │   Session: alice-001 │         │   Session: bob-001   │           │
│  │                      │         │                      │           │
│  │  /mnt/workspace ─────┼── X ──┼── /mnt/workspace      │           │
│  │  (PRIVATE)           │         │  (PRIVATE)           │           │
│  │                      │         │                      │           │
│  │  /mnt/datasets ──────┼── ✓ ──┼── /mnt/datasets       │           │
│  │  (SHARED - EFS)      │         │  (SHARED - EFS)      │           │
│  │                      │         │                      │           │
│  │  /mnt/tools ─────────┼── ✓ ──┼── /mnt/tools          │           │
│  │  (SHARED - S3 Files) │         │  (SHARED - S3 Files) │           │
│  └──────────┬───────────┘         └──────────┬───────────┘           │
└─────────────┼────────────────────────────────┼───────────────────────┘
              │                                │
              │  Session Storage               │  Session Storage
              │  (isolated per session)        │  (isolated per session)
              ▼                                ▼
    ┌──────────────────┐            ┌──────────────────┐
    │ Alice's durable  │            │ Bob's durable    │
    │ storage (managed)│            │ storage (managed)│
    └──────────────────┘            └──────────────────┘

              │ EFS (shared)                   │ EFS (shared)
              └────────────┬───────────────────┘
                           ▼
                ┌──────────────────────┐
                │   Amazon EFS         │
                │   (single access pt) │
                │   /shared-datasets   │
                └──────────────────────┘

              │ S3 Files (shared)              │ S3 Files (shared)
              └────────────┬───────────────────┘
                           ▼
                ┌──────────────────────┐        ┌──────────────────┐
                │   S3 Files FS        │───────▶│   S3 Bucket      │
                │   (access point)     │◀───────│   (tools)        │
                │   /shared-tools      │  sync  └──────────────────┘
                └──────────────────────┘              ▲
                                                     │ S3 API
                                              ┌──────┴─────────┐
                                              │ External Systems│
                                              │ (Lambda, CI/CD) │
                                              └────────────────┘
```

### Detailed Configuration

**Runtime creation:**

```python
import boto3

client = boto3.client("bedrock-agentcore-control", region_name="us-east-1")

response = client.create_agent_runtime(
    agentRuntimeName="multi-user-agent",
    roleArn="arn:aws:iam::<account>:role/AgentExecutionRole",
    networkConfiguration={
        "networkMode": "VPC",
        "networkModeConfig": {
            "subnets": ["subnet-aaa", "subnet-bbb"],
            "securityGroups": ["sg-runtime"]
        }
    },
    agentRuntimeArtifact={
        "containerConfiguration": {
            "containerUri": "<account>.dkr.ecr.<region>.amazonaws.com/my-agent:latest"
        }
    },
    filesystemConfigurations=[
        # Private per-session workspace
        {
            "sessionStorage": {
                "mountPath": "/mnt/workspace"
            }
        },
        # Shared datasets (all users see same data)
        {
            "efsAccessPoint": {
                "accessPointArn": "arn:aws:elasticfilesystem:<region>:<account>:access-point/<ap-id>",
                "mountPath": "/mnt/datasets"
            }
        },
        # Shared tools (synced with S3 bucket, accessible externally)
        {
            "s3FilesAccessPoint": {
                "accessPointArn": "arn:aws:s3files:<region>:<account>:file-system/<fs-id>/access-point/<ap-id>",
                "mountPath": "/mnt/tools"
            }
        }
    ]
)
```

**Agent code pattern:**

```python
import os

WORKSPACE = "/mnt/workspace"   # Private: code, packages, state
DATASETS = "/mnt/datasets"     # Shared: reference data, results (EFS)
TOOLS = "/mnt/tools"           # Shared: scripts, utilities (S3 Files)

@app.entrypoint
def handle_request(payload):
    session_id = payload.get("session_id")
    
    # Private workspace operations
    project_dir = f"{WORKSPACE}/project"
    os.makedirs(project_dir, exist_ok=True)
    # Install packages, write code, run builds — all private
    
    # Shared EFS data access
    with open(f"{DATASETS}/reference/config.json") as f:
        shared_config = json.load(f)
    
    # Write shared results (visible to all users via EFS)
    with open(f"{DATASETS}/results/{session_id}_output.csv", "w") as f:
        f.write(results)
    
    # Use shared tools (synced from S3 bucket)
    os.system(f"bash {TOOLS}/scripts/analyze.sh")
    
    # Write tools (syncs back to S3 for external access)
    with open(f"{TOOLS}/outputs/report.json", "w") as f:
        json.dump(report, f)
```

**Multi-user invocation:**

```python
# Alice's session — gets her own /mnt/workspace, sees shared /mnt/datasets
client.invoke_agent_runtime(
    agentRuntimeArn=runtime_arn,
    runtimeSessionId="user-alice-session-default-00000000",
    payload=b'{"prompt": "Analyze the dataset and save results"}'
)

# Bob's session — gets his own /mnt/workspace, sees SAME /mnt/datasets
client.invoke_agent_runtime(
    agentRuntimeArn=runtime_arn,
    runtimeSessionId="user-bob-session-default-000000000",
    payload=b'{"prompt": "Read Alice results from /mnt/datasets/results/"}'
)
```

### Infrastructure Requirements

| Component | Details |
|-----------|---------|
| VPC | Required (for EFS and S3 Files mount targets) |
| Subnets | At least 2 in different AZs (recommended) |
| Security Groups | Runtime SG → allow outbound TCP 2049; Mount target SG → allow inbound TCP 2049 from runtime SG |
| EFS File System | One file system with mount targets in same AZs as runtime subnets |
| EFS Access Point | One shared access point (UID/GID matching container user) |
| S3 Files File System | One file system backed by an S3 bucket (versioning enabled) |
| S3 Files Mount Targets | In same VPC/AZs as runtime subnets |
| S3 Files Access Point | One shared access point (UID/GID matching container user) |
| IAM (execution role) | `elasticfilesystem:ClientMount` + `ClientWrite`; `s3files:ClientMount` + `ClientWrite` + `GetAccessPoint` |
| Session Storage | No additional infrastructure — managed by AgentCore |

### Data Flow Summary

| Action | Where | Who Sees It |
|--------|-------|-------------|
| `echo "hello" > /mnt/workspace/test.txt` | Session Storage | Only this session |
| `pip install pandas` (in /mnt/workspace) | Session Storage | Only this session |
| `git clone ... /mnt/workspace/repo` | Session Storage | Only this session |
| `cp results.csv /mnt/datasets/` | EFS | All sessions immediately |
| `echo "tool" > /mnt/tools/script.sh` | S3 Files | All sessions + syncs to S3 bucket |
| External `aws s3 cp tool.sh s3://bucket/` | S3 Files | All sessions (after sync) |
| Stop session → Resume | Session Storage restored | Same session only |
| Delete runtime | Session Storage deleted | EFS + S3 Files data preserved |

### When to Use Each Mount

| Mount | Use For |
|-------|---------|
| `/mnt/workspace` (Session Storage) | Source code, installed packages, build artifacts, git repos, agent state |
| `/mnt/datasets` (EFS) | Reference datasets, shared analysis results, multi-agent collaboration files |
| `/mnt/tools` (S3 Files) | Shared scripts/utilities, CI/CD artifacts, data accessible via S3 API externally |

---

## Summary

For multi-user agent applications (as deployed in this demo):

1. **Use Session Storage** (`/mnt/workspace`) for everything private: source code, installed packages, build artifacts, agent state, git repos.
2. **Use EFS** (`/mnt/datasets`) for truly shared data: reference datasets, shared results, multi-agent collaboration files.
3. **Use S3 Files** (`/mnt/tools`) for shared tools with external access: scripts, utilities, and data that external systems need to read/write via S3 APIs.

This hybrid approach gives you automatic per-user isolation (no access point management per user) combined with efficient data sharing and external system integration — the best of all worlds.
