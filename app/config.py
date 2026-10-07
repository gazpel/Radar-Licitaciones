from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mp_ticket: str = ""
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "mistral"
    llm_num_ctx: int = 8192
    # Modelos con razonamiento (Granite 4.2): false lo desactiva. Vacío = no se envía.
    llm_think: bool | None = None


settings = Settings()
