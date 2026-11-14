"""Búsqueda semántica con embeddings: ¿qué tan parecida es una licitación al rubro de la empresa?

Un embedding es una lista de números (un vector) que representa el significado de un texto.
Textos con significado parecido tienen vectores que apuntan en direcciones parecidas, aunque no
compartan palabras: "colchones clínicos antiescaras" queda cerca de "fabricación de colchones".
La similitud coseno mide esa cercanía: 1 = mismo significado, 0 = nada que ver.

Se usa en dos lugares:
- Etapa 1 del filtro: rescata licitaciones cuyo nombre no tiene palabras clave pero sí el sentido.
- Orden del panel: las licitaciones más parecidas al perfil primero.
"""
import numpy as np
from langchain_ollama import OllamaEmbeddings

from app.config import settings
from app.db import Empresa, Licitacion

_cliente: OllamaEmbeddings | None = None


def _embeddings() -> OllamaEmbeddings:
    global _cliente
    if _cliente is None:
        _cliente = OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_url)
    return _cliente


def embeber(textos: list[str]) -> np.ndarray:
    """Devuelve una matriz: una fila (vector normalizado) por texto."""
    vectores = np.array(_embeddings().embed_documents(textos), dtype=np.float32)
    normas = np.linalg.norm(vectores, axis=1, keepdims=True)
    return vectores / np.where(normas == 0, 1, normas)


def similitudes(perfil: np.ndarray, textos: np.ndarray) -> np.ndarray:
    """Similitud coseno entre el perfil y cada texto (los vectores ya vienen normalizados)."""
    return textos @ perfil


def similitud_con_perfil(perfil: str, textos: list[str], lote: int = 128) -> list[float]:
    """Similitud de cada texto con el perfil. Se envía por lotes para no saturar a Ollama."""
    vector_perfil = embeber([perfil])[0]
    resultado: list[float] = []
    for inicio in range(0, len(textos), lote):
        resultado.extend(similitudes(vector_perfil, embeber(textos[inicio:inicio + lote])).tolist())
    return resultado


def texto_perfil(empresa: Empresa) -> str:
    return f"{empresa.rubro}. Productos: {', '.join(empresa.palabras_clave)}."


def texto_licitacion(licitacion: Licitacion) -> str:
    productos = ", ".join(licitacion.productos)
    return f"{licitacion.nombre}. {licitacion.descripcion}. Productos: {productos}."
