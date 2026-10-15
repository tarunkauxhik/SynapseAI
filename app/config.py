"""Configuration management for the research app."""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Supabase Configuration
    supabase_url: str = Field(default="http://localhost:8000")
    supabase_key: str = Field(default="test-key")
    supabase_service_role_key: Optional[str] = Field(default=None)  # Use for backend operations

    # LLM (any OpenAI-compatible endpoint)
    llm_base_url: str = Field(default="https://llm-gateway-azure.penpencil.guru/v1")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="MiniMax-M3")

    # Research Tools API Keys
    tavily_api_key: Optional[str] = Field(default=None)  # For web search

    # Evals: comma-separated agent model allowlist (first = default), the judge, and the run key
    eval_agent_models: str = Field(default="MiniMax-M3,MiniMax-M2.5-highspeed")
    eval_judge_model: str = Field(default="MiniMax-M2.7")
    eval_run_key: Optional[str] = Field(default=None)  # unset = eval runs disabled

    @property
    def eval_agent_model_list(self) -> list:
        """Allowed eval agent models; the judge is never allowed as an agent."""
        models = [m.strip() for m in self.eval_agent_models.split(",") if m.strip()]
        return [m for m in models if m != self.eval_judge_model]


# Create settings instance, allowing for test overrides
def get_settings() -> Settings:
    """Get settings instance."""
    return Settings()


settings = get_settings()
