from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DIGEST_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    gemini_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Paths
    data_dir: Path = Path("./data")
    output_dir: Path = Path("./outputs")

    # Spark
    spark_driver_memory: str = "4g"
    spark_shuffle_partitions: int = 4

    # Logging
    log_level: str = "INFO"

    @property
    def bronze_path(self) -> str:
        return str(self.data_dir / "bronze")

    @property
    def silver_path(self) -> str:
        return str(self.data_dir / "silver")

    @property
    def gold_path(self) -> str:
        return str(self.data_dir / "gold")

    @property
    def digests_path(self) -> Path:
        return self.output_dir / "digests"

    @property
    def logs_path(self) -> Path:
        return self.output_dir / "logs"


settings = Settings()
