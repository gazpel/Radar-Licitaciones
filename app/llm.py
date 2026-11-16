"""Acceso al LLM mediante LangChain. Hoy usa Ollama (local y gratis).

Para cambiar a un modelo en la nube (p. ej. Gemini) basta crear otro "chat" de LangChain
en `_modelo()`: el resto del sistema solo llama a generar_json y no se entera del cambio.
"""
import json
from functools import cache

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from app.config import settings


class RespuestaTruncada(ValueError):
    """El modelo llegó al tope de tokens antes de terminar el JSON."""


@cache
def _modelo(nombre: str, think: bool | None, esquema_json: str) -> ChatOllama:
    """Un cliente por combinación de modelo y esquema (se reutiliza entre llamadas)."""
    return ChatOllama(
        model=nombre,
        base_url=settings.ollama_url,
        temperature=0,  # respuestas reproducibles
        num_ctx=settings.llm_num_ctx,
        num_predict=settings.llm_num_predict,
        format=json.loads(esquema_json),  # salida estructurada: Ollama obliga a cumplir el esquema
        reasoning=think,  # False desactiva el razonamiento de Granite 4.2
        keep_alive=settings.llm_keep_alive_minutos * 60,  # el modelo sigue cargado un rato: la próxima respuesta es más rápida
    )


def generar_json(sistema: str, usuario: str, esquema: dict, modelo: str | None = None,
                 think: bool | None = None) -> dict:
    """Pide al modelo una respuesta que cumpla el esquema JSON entregado (salida estructurada).

    Sin `modelo` ni `think` se usan LLM_MODEL y LLM_THINK del .env.
    """
    nombre = modelo or settings.llm_model
    if think is None and modelo is None:
        think = settings.llm_think
    chat = _modelo(nombre, think, json.dumps(esquema, sort_keys=True))
    respuesta = chat.invoke([SystemMessage(sistema), HumanMessage(usuario)])
    if respuesta.response_metadata.get("done_reason") == "length":
        raise RespuestaTruncada(f"La respuesta superó {settings.llm_num_predict} tokens")
    try:
        return json.loads(respuesta.content)
    except json.JSONDecodeError as error:
        raise RespuestaTruncada(f"JSON incompleto: {error}") from error
