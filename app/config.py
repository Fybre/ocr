from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Storage
    database_url: str = "sqlite:////data/ocr.db"
    upload_dir: str = "/data/uploads"
    results_dir: str = "/data/results"
    watch_input_dir: str = "/data/watch_input"
    watch_output_dir: str = "/data/watch_output"

    # App
    app_base_url: str = "http://localhost:8000"
    app_version: str = "1.0.0"
    admin_token: str = ""  # if set, required for key management endpoints

    # OpenAI
    openai_api_key: str = ""

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"

    # Local LLM (Ollama)
    local_llm_base_url: str = "http://host.docker.internal:11434/v1"
    local_llm_model: str = "qwen2.5-vl:7b"          # used for OCR / text extraction
    local_classifier_model: str = ""                  # used for content classification; falls back to local_llm_model if empty
    local_cleanup_model: str = ""                     # text-only model to strip thinking commentary from vision model output

    # OCR
    ocr_confidence_threshold: float = 60.0
    ocr_dpi: int = 300

    # Jobs
    job_retention_days: int = 30

    # Folder watcher
    watch_default_mode: str = "auto"
    watch_default_format: str = "plain"
    watch_default_languages: str = "eng"

    def ensure_dirs(self) -> None:
        for d in [self.upload_dir, self.results_dir, self.watch_input_dir, self.watch_output_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_azure(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def has_local_llm(self) -> bool:
        return bool(self.local_llm_base_url)

    @property
    def effective_classifier_model(self) -> str:
        """Classifier model, falling back to the extraction model if not separately configured."""
        return self.local_classifier_model.strip() or self.local_llm_model.strip()


settings = Settings()
