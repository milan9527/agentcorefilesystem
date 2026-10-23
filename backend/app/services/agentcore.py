"""AgentCore Runtime client for shell command execution and session management.

Uses the Bedrock AgentCore data plane APIs:
- InvokeAgentRuntimeCommand: Execute shell commands in a session
- InvokeAgentRuntime: Invoke the agent for reasoning tasks
- StopRuntimeSession: Stop a session (persists storage)
"""

import json
import time
import uuid

import boto3

from app.config import settings

# API Gateway HTTP API cuts integrations off at 30s; keep retries well inside it.
COLD_START_RETRY_BUDGET_SECONDS = 20
COLD_START_RETRY_INTERVAL_SECONDS = 4


def _call_with_cold_start_retry(fn, **kwargs):
    """Call an AgentCore data plane API, retrying only while the microVM boots.

    Application errors from the runtime (e.g. "Received error (500/502) from
    runtime") are raised immediately — retrying them only burns time until
    API Gateway times out with a 503.
    """
    deadline = time.monotonic() + COLD_START_RETRY_BUDGET_SECONDS
    while True:
        try:
            return fn(**kwargs)
        except Exception as e:
            is_cold_start = "health check" in str(e)
            if is_cold_start and time.monotonic() + COLD_START_RETRY_INTERVAL_SECONDS < deadline:
                time.sleep(COLD_START_RETRY_INTERVAL_SECONDS)
                continue
            raise


class AgentCoreClient:
    """Client wrapping the Bedrock AgentCore Runtime data plane APIs.

    Provides methods for:
    - Executing shell commands via InvokeAgentRuntimeCommand
    - Invoking the agent via InvokeAgentRuntime
    - Managing sessions (stop/resume)
    - Listing files via shell commands
    """

    def __init__(self):
        self._client = boto3.client(
            "bedrock-agentcore", region_name=settings.aws_region
        )

    @staticmethod
    def get_user_session_id(user_id: str, session_name: str = "default") -> str:
        """Get a stable session ID for a user + session name combo.

        Session IDs must be at least 33 characters per API requirement.
        """
        base = f"user-{user_id}-session-{session_name}"
        if len(base) < 33:
            base = base + "-" + "0" * (33 - len(base))
        return base

    def invoke_agent(self, session_id: str, prompt: str) -> dict:
        """Invoke the agent for reasoning tasks.

        Uses InvokeAgentRuntime to send a prompt to the agent running
        in the session's microVM. The agent has access to all mounted
        filesystems.

        Args:
            session_id: The runtime session ID (>= 33 chars).
            prompt: The prompt to send to the agent.

        Returns:
            Dict with the agent's response.
        """
        payload = json.dumps({"prompt": prompt, "session_id": session_id})
        response = _call_with_cold_start_retry(
            self._client.invoke_agent_runtime,
            agentRuntimeArn=settings.agentcore_runtime_arn,
            runtimeSessionId=session_id,
            qualifier="DEFAULT",
            payload=payload.encode("utf-8"),
        )

        # Read the streaming response
        body_parts = []
        for chunk in response.get("response", []):
            if isinstance(chunk, bytes):
                body_parts.append(chunk)
            elif isinstance(chunk, dict) and "chunk" in chunk:
                body_parts.append(chunk["chunk"].get("bytes", b""))

        body = b"".join(body_parts)
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"response": body.decode("utf-8", errors="replace")}

    def execute_command(
        self, session_id: str, command: str, timeout: int | None = None
    ) -> dict:
        """Execute a shell command in an AgentCore Runtime session.

        Uses InvokeAgentRuntimeCommand to run the command inside the
        session's microVM container. The command sees the same filesystem
        as the agent, including all mounted storage:
        - /mnt/workspace (session storage - isolated per session)
        - /mnt/datasets (EFS - shared)
        - /mnt/tools (S3 Files - shared)

        Args:
            session_id: The runtime session ID (>= 33 chars).
            command: Shell command to execute.
            timeout: Command timeout in seconds (1-3600).

        Returns:
            Dict with stdout, stderr, exit_code, and status.
        """
        timeout = timeout or settings.default_command_timeout
        response = _call_with_cold_start_retry(
            self._client.invoke_agent_runtime_command,
            agentRuntimeArn=settings.agentcore_runtime_arn,
            runtimeSessionId=session_id,
            qualifier="DEFAULT",
            contentType="application/json",
            accept="application/vnd.amazon.eventstream",
            body={
                "command": f'/bin/bash -c "{command}"',
                "timeout": min(timeout, settings.max_command_timeout),
            },
        )

        stdout_parts = []
        stderr_parts = []
        exit_code = None
        status = None

        for event in response.get("stream", []):
            if "chunk" in event:
                chunk = event["chunk"]

                if "contentDelta" in chunk:
                    delta = chunk["contentDelta"]
                    if delta.get("stdout"):
                        stdout_parts.append(delta["stdout"])
                    if delta.get("stderr"):
                        stderr_parts.append(delta["stderr"])

                if "contentStop" in chunk:
                    stop = chunk["contentStop"]
                    exit_code = stop.get("exitCode")
                    status = stop.get("status")

        return {
            "stdout": "".join(stdout_parts),
            "stderr": "".join(stderr_parts),
            "exit_code": exit_code,
            "status": status,
        }

    def list_files(self, session_id: str, path: str) -> dict:
        """List files at a given path in the session's filesystem."""
        command = f"ls -la {path} 2>&1 || echo 'PATH_NOT_FOUND'"
        return self.execute_command(session_id, command, timeout=10)

    def read_file(self, session_id: str, file_path: str) -> dict:
        """Read file contents from the session's filesystem."""
        command = f"cat {file_path} 2>&1"
        return self.execute_command(session_id, command, timeout=10)

    def write_file(self, session_id: str, file_path: str, content: str) -> dict:
        """Write content to a file in the session's filesystem."""
        escaped = content.replace("'", "'\\''")
        command = f"cat > {file_path} << 'AGENTCORE_EOF'\n{escaped}\nAGENTCORE_EOF"
        return self.execute_command(session_id, command, timeout=10)

    def get_storage_info(self, session_id: str) -> dict:
        """Get information about all mounted filesystems in the session."""
        command = (
            "echo '=== Mount Points ===' && "
            "df -h /mnt/workspace /mnt/datasets /mnt/tools 2>/dev/null && "
            "echo '=== Session Storage ===' && "
            "du -sh /mnt/workspace 2>/dev/null && "
            "echo '=== EFS (Datasets) ===' && "
            "du -sh /mnt/datasets 2>/dev/null && "
            "echo '=== S3 Files (Tools) ===' && "
            "du -sh /mnt/tools 2>/dev/null"
        )
        return self.execute_command(session_id, command, timeout=15)

    def stop_session(self, session_id: str) -> dict:
        """Stop a runtime session, persisting session storage."""
        self._client.stop_runtime_session(
            agentRuntimeArn=settings.agentcore_runtime_arn,
            runtimeSessionId=session_id,
            qualifier="DEFAULT",
        )
        return {"status": "stopped", "session_id": session_id}


# Singleton client instance
agentcore_client = AgentCoreClient()
