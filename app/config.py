from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mp_ticket: str = ""
    # Segundos de espera entre consultas a la API (evita el error 429)
    mp_pausa: float = 1.0
    db_url: str = "sqlite:///data/radar.db"
    ollama_url: str = "http://localhost:11434"
    # Modelo por defecto: IBM Granite 4.2 8B (el mejor en el puntaje de conveniencia, comparación del 14/11/2026).
    # Alternativas probadas: "mistral" (citas más precisas) y "gemma4:e2b" (más rápido); con ellas LLM_THINK va vacío.
    llm_model: str = "granite4.2:8b"
    llm_num_ctx: int = 8192
    # Tope de tokens de la respuesta. Entrada + respuesta deben caber en llm_num_ctx:
    # si no, Ollama descarta texto y puede no terminar nunca.
    llm_num_predict: int = 4000
    # Modelo de embeddings (multilingüe, para la búsqueda semántica)
    embed_model: str = "granite-embedding:278m"
    # Etapa 1b (rescatar por significado nombres sin palabras clave). Desactivada: medido el 14/11/2026,
    # con títulos cortos el modelo no distingue el rubro (habría que aceptar >1.200 candidatas para no
    # perder ninguna de las 6 de colchones, que las palabras clave ya encuentran todas).
    busqueda_semantica: bool = False
    similitud_minima: float = 0.80
    # Modelos con razonamiento (Granite 4.2): false lo desactiva y reduce el tiempo a la mitad.
    # Vacío = no se envía (para modelos sin razonamiento, como mistral o gemma4:e2b).
    llm_think: bool | None = False
    # Carpeta donde el navegador guarda las descargas (opción A de la carga de bases). Vacío = Descargas del usuario.
    carpeta_descargas: str = ""


settings = Settings()
