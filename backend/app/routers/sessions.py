"""Session management router.

Provides endpoints for creating, stopping, and resuming AgentCore Runtime
sessions. Each user gets their own session with isolated session storage
but shared access to EFS and S3 Files mounts.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.agentcore import agentcore_client

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# In-memory session registry (use a database in production)
_active_sessions: dict[str, dict] = {}


class CreateSessionRequest(BaseModel):
    """Request to create/join a session for a user."""

    user_id: str = Field(..., min_length=1, max_length=64, description="User identifier")
    session_name: str = Field(
        default="default", description="Session name (user can have multiple)"
    )


class SessionResponse(BaseModel):
    """Session information returned to the client."""

    session_id: str
    user_id: str
    session_name: str
    status: str
    mounts: dict


class StopSessionRequest(BaseModel):
    """Request to stop a session."""

    session_id: str = Field(..., min_length=33)


@router.post("/create", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest):
    """Create or resume a session for a user.

    Each user gets a unique session ID that maps to an isolated microVM
    in AgentCore Runtime. The session has:
    - /mnt/workspace: Private session storage (only this user sees it)
    - /mnt/datasets: Shared EFS (all users see the same data)
    - /mnt/tools: Shared S3 Files (all users see the same tools)

    If the user already has an active session with this name, returns
    the existing session (resume behavior).
    """
    session_id = agentcore_client.get_user_session_id(
        request.user_id, request.session_name
    )

    # Check if session already exists
    if session_id in _active_sessions:
        session = _active_sessions[session_id]
        return SessionResponse(
            session_id=session_id,
            user_id=request.user_id,
            session_name=request.session_name,
            status="active",
            mounts=session["mounts"],
        )

    # Register new session
    mounts = {
        "session_storage": {
            "path": settings.session_storage_mount,
            "type": "Session Storage",
            "scope": "private",
        },
        "efs": {
            "path": settings.efs_mount,
            "type": "Amazon EFS",
            "scope": "shared",
        },
        "s3files": {
            "path": settings.s3files_mount,
            "type": "Amazon S3 Files",
            "scope": "shared",
        },
    }

    # Start the session by invoking the agent (provisions the microVM)
    try:
        agentcore_client.invoke_agent(session_id, "Session initialized")
    except Exception:
        pass  # Session may already be active from a previous invocation

    _active_sessions[session_id] = {
        "user_id": request.user_id,
        "session_name": request.session_name,
        "status": "active",
        "mounts": mounts,
    }

    return SessionResponse(
        session_id=session_id,
        user_id=request.user_id,
        session_name=request.session_name,
        status="active",
        mounts=mounts,
    )


@router.post("/stop")
async def stop_session(request: StopSessionRequest):
    """Stop a session, persisting session storage.

    After stopping:
    - Session storage data is flushed to durable storage
    - The microVM is terminated
    - The session can be resumed later with the same session ID
    - EFS and S3 Files data remains accessible from other sessions
    """
    try:
        result = agentcore_client.stop_session(request.session_id)
        if request.session_id in _active_sessions:
            _active_sessions[request.session_id]["status"] = "stopped"
        return {
            "session_id": request.session_id,
            "status": "stopped",
            "message": "Session stopped. Storage persisted. Resume with same session ID.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active")
async def list_active_sessions():
    """List all active sessions (for demo/admin purposes)."""
    return {
        "sessions": [
            {
                "session_id": sid,
                "user_id": info["user_id"],
                "session_name": info["session_name"],
                "status": info["status"],
            }
            for sid, info in _active_sessions.items()
        ]
    }


@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get details for a specific session."""
    if session_id not in _active_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    info = _active_sessions[session_id]
    return {
        "session_id": session_id,
        **info,
    }
