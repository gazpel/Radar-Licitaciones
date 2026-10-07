"""Acceso al LLM. Hoy usa Ollama (local y gratis); otro proveedor se agrega aquí sin tocar el resto."""
import json

import httpx

from app.config import settings


def generar_json(sistema: str, usuario: str, esquema: dict) -> dict:
    """Pide al modelo una respuesta que cumpla el esquema JSON entregado (salida estructurada)."""
    cuerpo = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": usuario},
        ],
        "format": esquema,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": settings.llm_num_ctx},
    }
    if settings.llm_think is not None:
        cuerpo["think"] = settings.llm_think
    respuesta = httpx.post(f"{settings.ollama_url}/api/chat", json=cuerpo, timeout=600)
    respuesta.raise_for_status()
    return json.loads(respuesta.json()["message"]["content"])
