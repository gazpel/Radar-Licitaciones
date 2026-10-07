"""Lectura de las bases en PDF, conservando el número de página para poder citar."""
from pathlib import Path

from pypdf import PdfReader


def leer_paginas(ruta: str | Path) -> list[str]:
    """Devuelve el texto de cada página. La posición en la lista + 1 es el número de página."""
    lector = PdfReader(str(ruta))
    return [(pagina.extract_text() or "").strip() for pagina in lector.pages]


def agrupar_paginas(paginas: list[str], max_caracteres: int) -> list[list[int]]:
    """Agrupa páginas consecutivas en bloques que quepan en el contexto del modelo.

    Devuelve listas de números de página (desde 1). Una página más larga que el límite
    queda sola en su bloque.
    """
    bloques, actual, largo = [], [], 0
    for numero, texto in enumerate(paginas, start=1):
        if actual and largo + len(texto) > max_caracteres:
            bloques.append(actual)
            actual, largo = [], 0
        actual.append(numero)
        largo += len(texto)
    if actual:
        bloques.append(actual)
    return bloques
