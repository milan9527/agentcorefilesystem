"""Shell command execution router.

Provides endpoints for executing shell commands in AgentCore Runtime sessions
via the InvokeAgentRuntimeCommand API.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.agentcore import agentcore_client

router = APIRouter(prefix="/api/shell", tags=["shell"])


class CommandRequest(BaseModel):
    """Request to execute a shell command."""

    session_id: str = Field(
        ..., min_length=33, description="Runtime session ID (>= 33 chars)"
    )
    command: str = Field(
        ..., min_length=1, max_length=65536, description="Shell command to execute"
    )
    timeout: int = Field(
        default=60, ge=1, le=3600, description="Timeout in seconds"
    )


class CommandResponse(BaseModel):
    """Response from shell command execution."""

    stdout: str
    stderr: str
    exit_code: int | None
    status: str | None


@router.post("/execute", response_model=CommandResponse)
async def execute_command(request: CommandRequest):
    """Execute a shell command in the user's AgentCore Runtime session.

    The command runs inside the session's microVM container and has access
    to all mounted filesystems:
    - /mnt/workspace (session storage - isolated per session)
    - /mnt/datasets (EFS - shared across sessions)
    - /mnt/tools (S3 Files - shared across sessions)

    Commands are one-shot: each spawns a new bash process. State between
    commands must be encoded in the command itself (e.g., cd /dir && cmd).
    """
    try:
        result = agentcore_client.execute_command(
            session_id=request.session_id,
            command=request.command,
            timeout=request.timeout,
        )
        return CommandResponse(**result)
    except Exception as e:
        error_msg = str(e)
        if "ResourceNotFoundException" in error_msg:
            raise HTTPException(
                status_code=404,
                detail="Session not found. The session may not be active.",
            )
        if "AccessDeniedException" in error_msg:
            raise HTTPException(
                status_code=403,
                detail="Access denied. Check IAM permissions for InvokeAgentRuntimeCommand.",
            )
        if "ThrottlingException" in error_msg:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again shortly.",
            )
        raise HTTPException(status_code=500, detail=f"Command execution failed: {error_msg}")
