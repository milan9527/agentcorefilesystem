# AgentCore Runtime 持久化存储与文件系统指南

## 概述

Amazon Bedrock AgentCore Runtime 提供持久化文件系统能力，使 AI Agent 能够跨会话保持状态。本文档描述三种存储方案、架构设计、用户隔离模式以及推荐的混合方案。

AgentCore Runtime 支持将文件系统挂载到 microVM 的 `/mnt/` 路径下。运行时自动处理所有挂载操作——无需自定义挂载代码、特权容器或下载编排。

---

## 存储方案概览

| 特性 | Session Storage | Amazon EFS | Amazon S3 Files |
|------|----------------|------------|-----------------|
| 类别 | 托管型 | 自带型 (BYO) | 自带型 (BYO) |
| 作用域 | 单会话隔离 | 跨会话共享 | 跨会话共享 |
| 持久性 | 停止/恢复后保留；空闲14天过期 | 永久（客户管理） | 永久（与 S3 桶同步） |
| 需要 VPC | 否 | 是 | 是 |
| 协议 | 服务托管 | NFSv4.1 over TLS | NFSv4.2 over TLS |
| 每运行时最大数量 | 1 | 2 | 2 |
| 一致性 | 本地文件系统 | Close-to-open | Close-to-open (NFS)；最终一致 (S3) |

---

## 方案一：托管 Session Storage

### 架构

Session Storage 是完全托管的能力，AgentCore 透明地处理所有存储操作。每个会话获得独立的持久化目录。

```
┌──────────────────────────────────────────────────┐
│            AgentCore Runtime MicroVM              │
│                                                  │
│   Agent 进程                                     │
│     │                                            │
│     ▼                                            │
│   /mnt/workspace  (本地文件系统)                  │
│     │                                            │
│     ▼  (异步复制)                                 │
│   AgentCore 托管持久化存储                        │
└──────────────────────────────────────────────────┘
```

**Agent 如何访问持久化文件：**

1. Agent 使用标准文件操作（`open`、`read`、`write`、`mkdir`）读写 `/mnt/workspace`。
2. 数据异步复制到 AgentCore 托管的持久化存储。
3. 会话停止时，待写入数据在优雅关闭期间刷新。
4. 恢复时（相同 `runtimeSessionId`），文件系统状态从持久化存储恢复。

**配置：**

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

**特点：**
- 零基础设施配置——无需 VPC、无需存储相关 IAM
- 会话级隔离——无跨会话数据泄露
- 标准 POSIX 操作：`ls`、`git`、`npm`、`pip` 均可正常工作
- 空闲14天或运行时版本更新后数据重置

---

## 方案二：Amazon EFS（弹性文件系统）

### 架构

EFS 提供共享的 POSIX 兼容文件系统，所有会话通过 VPC 中的 NFS 挂载目标同时访问。

```
┌─────────────────────────────────────────────────────────────┐
│                         您的 VPC                            │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐                      │
│  │  MicroVM A   │    │  MicroVM B   │                      │
│  │  (会话 1)    │    │  (会话 2)    │                      │
│  │  /mnt/data ──┼──┐ │  /mnt/data ──┼──┐                  │
│  └──────────────┘  │ └──────────────┘  │                   │
│                    │                    │                   │
│                    ▼                    ▼                   │
│              ┌──────────────────────────────┐              │
│              │   EFS 挂载目标 (AZ-a)        │              │
│              │   EFS 挂载目标 (AZ-b)        │              │
│              └──────────────┬───────────────┘              │
│                             │                              │
│                             ▼                              │
│              ┌──────────────────────────────┐              │
│              │     Amazon EFS 文件系统       │              │
│              │     (接入点: /data)           │              │
│              └──────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

**Agent 如何访问持久化文件：**

1. AgentCore 通过 NFSv4.1 over TLS（端口 2049）使用 IAM 认证挂载 EFS 接入点。
2. Agent 使用标准文件操作读写挂载路径。
3. 所有会话看到相同数据——更改对其他会话立即可见（close-to-open 一致性）。
4. 数据永久保留，直到显式删除。

**配置：**

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

**执行角色所需 IAM 权限：**

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
      "elasticfilesystem:AccessPointArn": "<接入点 ARN>"
    }
  }
}
```

**特点：**
- 完整 POSIX 语义：硬链接、符号链接、建议性文件锁
- 多会话并发读写
- 弹性容量——自动扩缩
- 需要 VPC，挂载目标需与运行时子网在同一可用区
- 安全组需允许 TCP 2049

---

## 方案三：Amazon S3 Files

### 架构

S3 Files 提供由 S3 桶支撑的文件系统接口，支持双向同步。数据可通过 NFS 挂载和标准 S3 API 双重访问。

```
┌─────────────────────────────────────────────────────────────┐
│                         您的 VPC                            │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐                      │
│  │  MicroVM A   │    │  MicroVM B   │                      │
│  │  (会话 1)    │    │  (会话 2)    │                      │
│  │  /mnt/tools──┼──┐ │  /mnt/tools──┼──┐                  │
│  └──────────────┘  │ └──────────────┘  │                   │
│                    │                    │                   │
│                    ▼                    ▼                   │
│              ┌──────────────────────────────┐              │
│              │  S3 Files 挂载目标 (AZ)      │              │
│              └──────────────┬───────────────┘              │
│                             │                              │
│                             ▼                              │
│              ┌──────────────────────────────┐              │
│              │   S3 Files 文件系统           │              │
│              │   (接入点: /tools)            │              │
│              └──────────────┬───────────────┘              │
└─────────────────────────────┼───────────────────────────────┘
                              │ 双向同步
                              ▼
                ┌──────────────────────────────┐
                │      Amazon S3 桶             │
                │  (s3://my-tools-bucket/)      │
                └──────────────────────────────┘
```

**Agent 如何访问持久化文件：**

1. AgentCore 通过 NFSv4.2 over TLS（端口 2049）使用强制 IAM 认证挂载 S3 Files 接入点。
2. Agent 使用标准文件操作读写挂载路径。
3. 更改双向同步到后端 S3 桶。
4. 外部系统也可通过 S3 API 读写——更改会传播到 NFS 挂载。

**配置：**

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

**执行角色所需 IAM 权限：**

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
      "s3files:AccessPointArn": "<接入点 ARN>"
    }
  }
}
```

**特点：**
- NFS 与 S3 之间双向同步
- 双重访问：文件系统操作 + S3 API
- 后端桶需启用版本控制
- NFS 端 close-to-open 一致性；S3 端最终一致性
- 最大文件大小：48 TiB
- 需要 VPC 和挂载目标

---

## 用户隔离与接入点

### 挑战

当多用户共享一个 Agent Runtime 时，需要控制谁能访问什么数据。每种存储类型提供不同的隔离机制。

### Session Storage：内置隔离

Session Storage 天然隔离——每个 `runtimeSessionId` 获得独立的私有文件系统，无需额外配置。

```
用户 Alice (session-alice-001) → /mnt/workspace → [Alice 的私有文件]
用户 Bob   (session-bob-001)   → /mnt/workspace → [Bob 的私有文件]
```

Alice 无法看到 Bob 的工作空间，反之亦然。这由服务强制执行。

### EFS：每用户接入点

EFS 支持在单个文件系统上创建多个接入点。每个接入点可强制不同的根目录和 POSIX 身份。

```
EFS 文件系统: fs-abc123
├── 接入点 1: /users/alice  (UID: 1001, GID: 1001)
├── 接入点 2: /users/bob    (UID: 1002, GID: 1002)
└── 接入点 3: /shared       (UID: 0, GID: 0)
```

**每用户模式：**
- 为每个用户创建一个接入点，`rootDirectory: /users/<user-id>`
- 每个用户的 Agent Runtime 引用其特定的接入点 ARN
- 接入点强制根目录——用户无法导航到其上层

**限制：** 需要为每个用户创建单独的 Agent Runtime（或动态更新运行时），因为接入点 ARN 在运行时创建时配置。对于多租户场景不实用。

### S3 Files：每用户接入点

与 EFS 相同的模式——创建不同根目录的每用户接入点：

```
S3 Files 文件系统: fs-xyz789 (后端桶: s3://my-bucket)
├── 接入点 1: /users/alice  → s3://my-bucket/users/alice/
├── 接入点 2: /users/bob    → s3://my-bucket/users/bob/
└── 接入点 3: /shared       → s3://my-bucket/shared/
```

**同样的限制：** 接入点在运行时创建时绑定。

### 实用的多用户隔离方案

对于无需每用户运行时的真正多用户隔离，推荐方案：

| 需求 | 方案 |
|------|------|
| 用户私有数据 | Session Storage（自动隔离） |
| 共享只读数据 | 单个 EFS/S3 Files 接入点（所有用户共享） |
| 超出会话生命周期的用户持久数据 | 共享 EFS 内的应用层隔离（如 `/mnt/data/<user-id>/`） |

---

## 方案对比

| 评估维度 | Session Storage | EFS | S3 Files |
|----------|----------------|-----|----------|
| **配置复杂度** | 无 | 中等（VPC、挂载目标、安全组） | 中高（VPC、挂载目标、安全组、桶、版本控制） |
| **用户隔离** | 内置 | 需要接入点或应用层 | 需要接入点或应用层 |
| **数据共享** | 不可能 | 原生（所有会话看到相同数据） | 原生（所有会话 + S3 API 访问） |
| **外部访问** | 无 | 通过 EC2/ECS 的 NFS 挂载 | 通过 S3 API 从任何地方访问 |
| **性能** | 高（类本地） | 高（NFS，弹性吞吐） | 良好（NFS + S3 同步延迟） |
| **成本** | 包含在 AgentCore 中 | EFS 定价（按存储量 + 吞吐量） | S3 定价 + S3 Files 定价 |
| **持久性** | 服务托管（14天过期） | 客户管理（永久） | 客户管理（永久，S3 持久性） |
| **最大容量** | 服务限制 | PB 级 | 每文件 48 TiB |
| **并发访问** | 仅单会话 | 多会话 + 外部 | 多会话 + S3 客户端 |
| **适用场景** | Agent 工作空间、安装包、项目状态 | 共享数据集、多 Agent 协作 | 共享工具、S3 管道集成 |

---

## 推荐混合方案：Session Storage + EFS + S3 Files

多用户 Agent 应用的最佳架构是将 **Session Storage 用于私有数据** + **EFS 用于真正的共享数据** + **S3 Files 用于需要外部访问的共享工具**。

这正是当前演示项目所部署的架构。

### 为什么选择这个组合

- **Session Storage** 为每个用户提供自动隔离，无需任何基础设施配置。适合代码、包、git 仓库和 Agent 状态。
- **EFS** 提供单一共享命名空间，用于所有用户确实需要访问的数据——数据集、参考资料、共享分析结果。
- **S3 Files** 添加共享工具存储并支持与 S3 双向同步——外部系统（Lambda、Glue、CI/CD）可以将工具推送到桶中，Agent 通过 NFS 立即看到。

### 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AgentCore Runtime                                 │
│                                                                     │
│  ┌─────────────────────┐         ┌─────────────────────┐           │
│  │   用户 Alice         │         │   用户 Bob           │           │
│  │   会话: alice-001    │         │   会话: bob-001      │           │
│  │                      │         │                      │           │
│  │  /mnt/workspace ─────┼── ✗ ──┼── /mnt/workspace      │           │
│  │  (私有)              │         │  (私有)              │           │
│  │                      │         │                      │           │
│  │  /mnt/datasets ──────┼── ✓ ──┼── /mnt/datasets       │           │
│  │  (共享 - EFS)        │         │  (共享 - EFS)        │           │
│  │                      │         │                      │           │
│  │  /mnt/tools ─────────┼── ✓ ──┼── /mnt/tools          │           │
│  │  (共享 - S3 Files)   │         │  (共享 - S3 Files)   │           │
│  └──────────┬───────────┘         └──────────┬───────────┘           │
└─────────────┼────────────────────────────────┼───────────────────────┘
              │                                │
              │  Session Storage               │  Session Storage
              │  (会话级隔离)                   │  (会话级隔离)
              ▼                                ▼
    ┌──────────────────┐            ┌──────────────────┐
    │ Alice 的持久存储  │            │ Bob 的持久存储    │
    │ (托管)           │            │ (托管)           │
    └──────────────────┘            └──────────────────┘

              │ EFS (共享)                     │ EFS (共享)
              └────────────┬───────────────────┘
                           ▼
                ┌──────────────────────┐
                │   Amazon EFS         │
                │   (单一接入点)        │
                │   /shared-datasets   │
                └──────────────────────┘

              │ S3 Files (共享)                │ S3 Files (共享)
              └────────────┬───────────────────┘
                           ▼
                ┌──────────────────────┐        ┌──────────────────┐
                │   S3 Files 文件系统   │───────▶│   S3 桶          │
                │   (接入点)           │◀───────│   (工具)         │
                │   /shared-tools      │  同步  └──────────────────┘
                └──────────────────────┘              ▲
                                                     │ S3 API
                                              ┌──────┴─────────┐
                                              │ 外部系统        │
                                              │ (Lambda, CI/CD) │
                                              └────────────────┘
```

### 详细配置

**运行时创建：**

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
        # 私有的会话级工作空间
        {
            "sessionStorage": {
                "mountPath": "/mnt/workspace"
            }
        },
        # 共享数据集（所有用户看到相同数据）
        {
            "efsAccessPoint": {
                "accessPointArn": "arn:aws:elasticfilesystem:<region>:<account>:access-point/<ap-id>",
                "mountPath": "/mnt/datasets"
            }
        },
        # 共享工具（与 S3 桶同步，外部可访问）
        {
            "s3FilesAccessPoint": {
                "accessPointArn": "arn:aws:s3files:<region>:<account>:file-system/<fs-id>/access-point/<ap-id>",
                "mountPath": "/mnt/tools"
            }
        }
    ]
)
```

**Agent 代码模式：**

```python
import os

WORKSPACE = "/mnt/workspace"   # 私有：代码、包、状态
DATASETS = "/mnt/datasets"     # 共享：参考数据、结果 (EFS)
TOOLS = "/mnt/tools"           # 共享：脚本、工具 (S3 Files)

@app.entrypoint
def handle_request(payload):
    session_id = payload.get("session_id")
    
    # 私有工作空间操作
    project_dir = f"{WORKSPACE}/project"
    os.makedirs(project_dir, exist_ok=True)
    # 安装包、写代码、运行构建——全部私有
    
    # 共享 EFS 数据访问
    with open(f"{DATASETS}/reference/config.json") as f:
        shared_config = json.load(f)
    
    # 写入共享结果（通过 EFS 对所有用户可见）
    with open(f"{DATASETS}/results/{session_id}_output.csv", "w") as f:
        f.write(results)
    
    # 使用共享工具（从 S3 桶同步）
    os.system(f"bash {TOOLS}/scripts/analyze.sh")
    
    # 写入工具（同步回 S3 供外部访问）
    with open(f"{TOOLS}/outputs/report.json", "w") as f:
        json.dump(report, f)
```

**多用户调用：**

```python
# Alice 的会话——获得自己的 /mnt/workspace，看到共享的 /mnt/datasets
client.invoke_agent_runtime(
    agentRuntimeArn=runtime_arn,
    runtimeSessionId="user-alice-session-default-00000000",
    payload=b'{"prompt": "分析数据集并保存结果"}'
)

# Bob 的会话——获得自己的 /mnt/workspace，看到相同的 /mnt/datasets
client.invoke_agent_runtime(
    agentRuntimeArn=runtime_arn,
    runtimeSessionId="user-bob-session-default-000000000",
    payload=b'{"prompt": "从 /mnt/datasets/results/ 读取 Alice 的结果"}'
)
```

### 基础设施要求

| 组件 | 详情 |
|------|------|
| VPC | 必需（用于 EFS 和 S3 Files 挂载目标） |
| 子网 | 至少2个不同可用区（推荐） |
| 安全组 | 运行时 SG → 允许出站 TCP 2049；挂载目标 SG → 允许来自运行时 SG 的入站 TCP 2049 |
| EFS 文件系统 | 一个文件系统，挂载目标在与运行时子网相同的可用区 |
| EFS 接入点 | 一个共享接入点（UID/GID 匹配容器用户） |
| S3 Files 文件系统 | 一个文件系统，后端 S3 桶需启用版本控制 |
| S3 Files 挂载目标 | 在与运行时子网相同的 VPC/可用区 |
| S3 Files 接入点 | 一个共享接入点（UID/GID 匹配容器用户） |
| IAM（执行角色） | `elasticfilesystem:ClientMount` + `ClientWrite`；`s3files:ClientMount` + `ClientWrite` + `GetAccessPoint` |
| Session Storage | 无需额外基础设施——由 AgentCore 托管 |

### 数据流向总结

| 操作 | 存储位置 | 谁能看到 |
|------|----------|----------|
| `echo "hello" > /mnt/workspace/test.txt` | Session Storage | 仅本会话 |
| `pip install pandas`（在 /mnt/workspace 中） | Session Storage | 仅本会话 |
| `git clone ... /mnt/workspace/repo` | Session Storage | 仅本会话 |
| `cp results.csv /mnt/datasets/` | EFS | 所有会话立即可见 |
| `echo "tool" > /mnt/tools/script.sh` | S3 Files | 所有会话 + 同步到 S3 桶 |
| 外部 `aws s3 cp tool.sh s3://bucket/` | S3 Files | 所有会话（同步后） |
| 停止会话 → 恢复 | Session Storage 恢复 | 仅同一会话 |
| 删除运行时 | Session Storage 删除 | EFS + S3 Files 数据保留 |

### 何时添加 S3 Files

当您需要以下能力时，添加 S3 Files 作为第三个挂载：
- 外部系统通过 S3 API 访问 Agent 数据（Lambda、Glue、SageMaker）
- 与基于 S3 的数据管道集成
- 双重访问模式（Agent 通过 NFS + 外部工具通过 S3）

```json
{
  "s3FilesAccessPoint": {
    "accessPointArn": "arn:aws:s3files:<region>:<account>:file-system/<fs-id>/access-point/<ap-id>",
    "mountPath": "/mnt/tools"
  }
}
```

---

## 总结

对于多用户 Agent 应用（如本演示项目所部署）：

1. **使用 Session Storage**（`/mnt/workspace`）存放所有私有内容：源代码、安装包、构建产物、Agent 状态、git 仓库。
2. **使用 EFS**（`/mnt/datasets`）存放真正的共享数据：参考数据集、共享结果、多 Agent 协作文件。
3. **使用 S3 Files**（`/mnt/tools`）存放需要外部访问的共享工具：脚本、工具以及外部系统需要通过 S3 API 读写的数据。

这种混合方案提供自动的用户隔离（无需为每个用户管理接入点）加上高效的数据共享和外部系统集成——三全其美。
