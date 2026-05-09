"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings for the AgentCore Filesystem Demo backend."""

    aws_region: str = "us-east-1"
    agentcore_runtime_arn: str = (
        "arn:aws:bedrock-agentcore:us-east-1:632930644527:runtime/agentcore_fs_demo-vQv834FKFx"
    )

    # Mount paths matching the runtime configuration
    session_storage_mount: str = "/mnt/workspace"
    efs_mount: str = "/mnt/datasets"
    s3files_mount: str = "/mnt/tools"

    # Command execution defaults
    default_command_timeout: int = 60
    max_command_timeout: int = 300

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
