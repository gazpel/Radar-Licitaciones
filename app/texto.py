"""Utilidades de texto compartidas por los módulos."""
import re
import unicodedata


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes y sin signos: "Región del Libertador O´Higgins " -> "region del libertador o higgins"."""
    if not texto:
        return ""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    solo_letras = re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower())
    return solo_letras.strip()
