"""AgentCore Runtime agent with hybrid filesystem support.

This agent runs inside the AgentCore Runtime microVM and has access to:
- /mnt/workspace: Session Storage (private per session)
- /mnt/datasets: EFS (shared across sessions)
- /mnt/tools: S3 Files (shared, synced with S3 bucket)

The agent handles /invocations for reasoning tasks.
Shell commands are executed separately via InvokeAgentRuntimeCommand.
"""

import json
import os
import subprocess

os.environ["BYPASS_TOOL_CONSENT"] = "true"

from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()

WORKSPACE = "/mnt/workspace"
DATASETS = "/mnt/datasets"
TOOLS = "/mnt/tools"


@app.entrypoint
def handle_request(payload):
    """Handle agent invocation requests.

    For this demo, we provide a simple command execution interface.
    The real shell access happens via InvokeAgentRuntimeCommand API.
    """
    prompt = payload.get("prompt", "")

    # Simple response showing filesystem info
    result = {
        "response": f"Agent received: {prompt}",
        "filesystem": {
            "workspace": WORKSPACE,
            "datasets": DATASETS,
            "tools": TOOLS,
        },
    }

    return result


if __name__ == "__main__":
    app.run()
