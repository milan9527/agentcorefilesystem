"""File browser router.

Provides endpoints for browsing and managing files across all mounted
filesystems in an AgentCore Runtime session.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.agentcore import agentcore_client

router = APIRouter(prefix="/api/files", tags=["files"])


class FileListRequest(BaseModel):
    """Request to list files at a path."""

    session_id: str = Field(..., min_length=33)
    path: str = Field(default="/mnt", description="Path to list")


class FileWriteRequest(BaseModel):
    """Request to write a file."""

    session_id: str = Field(..., min_length=33)
    file_path: str = Field(..., description="Absolute path for the file")
    content: str = Field(..., description="File content to write")


class FileReadRequest(BaseModel):
    """Request to read a file."""

    session_id: str = Field(..., min_length=33)
    file_path: str = Field(..., description="Absolute path to read")


class StorageInfoResponse(BaseModel):
    """Storage information for all mounted filesystems."""

    session_storage: dict
    efs: dict
    s3files: dict
    raw_output: str


@router.post("/list")
async def list_files(request: FileListRequest):
    """List files at a path in the session's filesystem.

    Accessible paths:
    - /mnt/workspace: Session storage (private to this session)
    - /mnt/datasets: EFS mount (shared - visible to all sessions)
    - /mnt/tools: S3 Files mount (shared - visible to all sessions)
    """
    # Validate path is under allowed mounts
    allowed_prefixes = ["/mnt/workspace", "/mnt/datasets", "/mnt/tools", "/mnt"]
    if not any(request.path.startswith(p) for p in allowed_prefixes):
        raise HTTPException(
            status_code=400,
            detail="Path must be under /mnt/ (workspace, datasets, or tools)",
        )

    try:
        result = agentcore_client.list_files(request.session_id, request.path)
        return {
            "path": request.path,
            "output": result["stdout"],
            "exit_code": result["exit_code"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/read")
async def read_file(request: FileReadRequest):
    """Read a file from the session's filesystem."""
    allowed_prefixes = ["/mnt/workspace", "/mnt/datasets", "/mnt/tools"]
    if not any(request.file_path.startswith(p) for p in allowed_prefixes):
        raise HTTPException(
            status_code=400,
            detail="File must be under /mnt/ (workspace, datasets, or tools)",
        )

    try:
        result = agentcore_client.read_file(request.session_id, request.file_path)
        return {
            "file_path": request.file_path,
            "content": result["stdout"],
            "exit_code": result["exit_code"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/write")
async def write_file(request: FileWriteRequest):
    """Write a file to the session's filesystem.

    Only session storage (/mnt/workspace) is writable per-session.
    EFS and S3 Files are shared and writable by all sessions.
    """
    allowed_prefixes = ["/mnt/workspace", "/mnt/datasets", "/mnt/tools"]
    if not any(request.file_path.startswith(p) for p in allowed_prefixes):
        raise HTTPException(
            status_code=400,
            detail="File must be under /mnt/ (workspace, datasets, or tools)",
        )

    try:
        result = agentcore_client.write_file(
            request.session_id, request.file_path, request.content
        )
        return {
            "file_path": request.file_path,
            "status": "written" if result["exit_code"] == 0 else "failed",
            "exit_code": result["exit_code"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/storage-info")
async def get_storage_info(request: FileListRequest):
    """Get storage usage information for all mounted filesystems."""
    try:
        result = agentcore_client.get_storage_info(request.session_id)
        return {
            "mounts": {
                "session_storage": {
                    "path": settings.session_storage_mount,
                    "type": "Session Storage (Managed)",
                    "scope": "Isolated per session",
                    "description": "Private workspace for this session's code and project files",
                },
                "efs": {
                    "path": settings.efs_mount,
                    "type": "Amazon EFS",
                    "scope": "Shared across all sessions",
                    "description": "Shared datasets accessible by all users and sessions",
                },
                "s3files": {
                    "path": settings.s3files_mount,
                    "type": "Amazon S3 Files",
                    "scope": "Shared across all sessions",
                    "description": "Shared tools and scripts synced with S3 bucket",
                },
            },
            "raw_output": result["stdout"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
