"""AgentCore Runtime Filesystem Demo - Backend API.

This FastAPI application provides a web interface for interacting with
Amazon Bedrock AgentCore Runtime's hybrid filesystem configurations:

- Session Storage: Per-user isolated workspace (/mnt/workspace)
- Amazon EFS: Shared datasets across all sessions (/mnt/datasets)
- Amazon S3 Files: Shared tools synced with S3 (/mnt/tools)

Users can execute shell commands in their own AgentCore Runtime session
via the InvokeAgentRuntimeCommand API, browse files, and manage sessions.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import files, sessions, shell

app = FastAPI(
    title="AgentCore Runtime Filesystem Demo",
    description=(
        "Demo application showcasing AgentCore Runtime hybrid filesystem "
        "configurations with multi-user shell access."
    ),
    version="1.0.0",
)

# CORS for frontend (CloudFront + local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://d190psp42zgs69.cloudfront.net",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(shell.router)
app.include_router(files.router)
app.include_router(sessions.router)


@app.get("/")
async def root():
    """API root - returns service info and available endpoints."""
    return {
        "service": "AgentCore Runtime Filesystem Demo",
        "version": "1.0.0",
        "description": (
            "Multi-user shell access to AgentCore Runtime with hybrid "
            "filesystem: Session Storage + EFS + S3 Files"
        ),
        "filesystem_layout": {
            "/mnt/workspace": {
                "type": "Session Storage (Managed)",
                "scope": "Isolated per user session",
                "use_case": "Code files, project state, installed packages",
            },
            "/mnt/datasets": {
                "type": "Amazon EFS",
                "scope": "Shared across all sessions",
                "use_case": "Datasets, shared data for analysis",
            },
            "/mnt/tools": {
                "type": "Amazon S3 Files",
                "scope": "Shared across all sessions",
                "use_case": "Shared tools, scripts, utilities (synced with S3)",
            },
        },
        "endpoints": {
            "POST /api/sessions/create": "Create or resume a user session",
            "POST /api/sessions/stop": "Stop a session (persists storage)",
            "GET /api/sessions/active": "List active sessions",
            "POST /api/shell/execute": "Execute shell command in session",
            "POST /api/files/list": "List files at a path",
            "POST /api/files/read": "Read a file",
            "POST /api/files/write": "Write a file",
            "POST /api/files/storage-info": "Get storage usage info",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
