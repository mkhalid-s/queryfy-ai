"""
QueryfyAI Benchmarks - Configuration Models

Pydantic models for benchmark run configuration.  Configs can be loaded
from YAML/JSON files (see ``benchmarks/configs/``) or constructed
programmatically in test harnesses.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class SuiteConfig(BaseModel):
    """Configuration for a single benchmark suite within a run.

    A *suite* maps one dataset to one database with a chosen set of
    evaluation metrics.

    Attributes:
        name: Human-readable suite label used in reports.
        dataset: Identifier matching a registered ``BenchmarkDataset.NAME``.
        db_type: Database category string (e.g., ``"sql"``, ``"nosql_document"``).
        metrics: List of metric identifiers to evaluate (e.g.,
            ``["exact_match", "execution_accuracy"]``).
        max_cases: Optional cap on the number of cases to run.  ``None``
            means run all cases in the dataset.
        difficulties: Optional list of difficulty levels to include.  ``None``
            means include all levels.
        transpile_from: When set, the runner first generates SQL then
            transpiles it to the target dialect (useful for NoSQL benchmarks
            that go through an intermediate SQL representation).
        connection_url: Database connection string.  Can use environment
            variable references (``$ENV_VAR``) that are resolved at runtime.
        tags: Arbitrary tags for grouping / filtering suites.
    """

    name: str
    dataset: str
    db_type: str = "sql"
    metrics: List[str] = Field(default_factory=lambda: ["exact_match"])
    max_cases: Optional[int] = None
    difficulties: Optional[List[str]] = None
    transpile_from: Optional[str] = None
    connection_url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class LLMBenchmarkConfig(BaseModel):
    """LLM provider settings for benchmark query generation.

    Supports all 15 providers configured in the app: openai, anthropic,
    azure, bedrock, vertex_ai, gemini, groq, ollama, together, mistral,
    cohere, replicate, deepseek, oauth_gateway, and custom.

    Attributes:
        provider: LLM provider identifier (must match a backend LlmProviders value).
        model: Model name or deployment ID.
        api_key_env: Name of the environment variable holding the API key.
            The runner reads the key at startup rather than storing secrets
            in config files.
        temperature: Sampling temperature.  Lower values improve
            reproducibility.
        max_tokens: Maximum tokens for the LLM response.
        base_url: Base URL override for azure, ollama, bedrock, custom, and
            deepseek providers.
        token_url: OAuth2 token endpoint URL (oauth_gateway provider).
        client_id: OAuth2 client ID (oauth_gateway provider).
        client_secret_env: Environment variable holding the OAuth2 client
            secret (oauth_gateway provider).
        auth_scope: OAuth2 scope (oauth_gateway provider).
        auth_type: OAuth2 grant type (oauth_gateway provider).
        tenant: Tenant identifier (oauth_gateway provider).
        star: Star identifier (oauth_gateway provider).
        chat_endpoint: Chat completion endpoint path (oauth_gateway provider).
        fast_model: Faster/cheaper model for complexity routing.
        enable_complexity_routing: Enable automatic model selection based
            on query complexity.
    """

    _VALID_PROVIDERS: ClassVar[set] = {
        "openai", "anthropic", "azure", "bedrock", "vertex_ai", "gemini",
        "groq", "ollama", "together", "mistral", "cohere", "replicate",
        "deepseek", "oauth_gateway", "custom",
    }

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key_env: str = "OPENAI_API_KEY"

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v not in cls._VALID_PROVIDERS:
            raise ValueError(
                f"Unknown provider {v!r}. Valid providers: "
                + ", ".join(sorted(cls._VALID_PROVIDERS))
            )
        return v
    temperature: float = 0.0
    max_tokens: int = 4096

    # Provider-specific fields (azure, ollama, bedrock, custom, deepseek)
    base_url: Optional[str] = None

    # OAuth Gateway fields (oauth_gateway provider)
    token_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret_env: Optional[str] = None
    auth_scope: Optional[str] = None
    auth_type: Optional[str] = "client_credentials"
    tenant: Optional[str] = None
    star: Optional[str] = None
    chat_endpoint: Optional[str] = None

    # Complexity routing
    fast_model: Optional[str] = None
    enable_complexity_routing: bool = False


class BenchmarkConfig(BaseModel):
    """Top-level configuration for a benchmark run.

    Attributes:
        name: Run name used in output filenames and reports.
        description: Free-text description for context in reports.
        llm: LLM configuration block.
        data_dir: Root directory where dataset files are stored / downloaded.
        output_dir: Directory for result JSON and reports.
        max_concurrent: Maximum concurrent case evaluations.  Controls
            semaphore width to avoid overwhelming the LLM API.
        generator_mode: How queries are generated:
            - ``"direct"``: single-shot LLM call
            - ``"react"``: multi-step ReAct agent
            - ``"chat"``: conversational (stateful) generation
        suites: One or more suite configurations to run sequentially.
    """

    name: str = "benchmark_run"
    description: str = ""
    llm: LLMBenchmarkConfig = Field(default_factory=LLMBenchmarkConfig)
    data_dir: Path = Field(default_factory=lambda: Path("benchmarks/data"))
    output_dir: Path = Field(default_factory=lambda: Path("benchmarks/results"))
    max_concurrent: int = Field(default=5, ge=1, le=50)
    generator_mode: Literal["direct", "react", "chat"] = "direct"
    suites: List[SuiteConfig] = Field(default_factory=list)
