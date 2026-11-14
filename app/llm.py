"""Acceso al LLM mediante LangChain. Hoy usa Ollama (local y gratis).

Para cambiar a un modelo en la nube (p. ej. Gemini) basta crear otro "chat" de LangChain
en `_modelo()`: el resto del sistema solo llama a generar_json y no se entera del cambio.
"""
import json
from functools import cache

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.config import settings


@cache
def _modelo(esquema_json: str) -> ChatOllama:
    """Un cliente por esquema (se reutiliza entre llamadas)."""
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_url,
        temperature=0,  # respuestas reproducibles
        num_ctx=settings.llm_num_ctx,
        format=json.loads(esquema_json),  # salida estructurada: Ollama obliga a cumplir el esquema
        reasoning=settings.llm_think,  # False desactiva el razonamiento de Granite 4.2
    )


def generar_json(sistema: str, usuario: str, esquema: dict) -> dict:
    """Pide al modelo una respuesta que cumpla el esquema JSON entregado (salida estructurada)."""
    modelo = _modelo(json.dumps(esquema, sort_keys=True))
    respuesta = modelo.invoke([SystemMessage(sistema), HumanMessage(usuario)])
    return json.loads(respuesta.content)
