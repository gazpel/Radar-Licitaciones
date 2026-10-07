"""Cliente de la API de Mercado Público (licitaciones).

Documentación: https://api.mercadopublico.cl/documentos/Documentación%20API%20Mercado%20Publico%20-%20Licitaciones.pdf
La API entrega metadatos (fechas, montos, ítems UNSPSC), pero NO los PDF de las bases.
"""
import unicodedata

import httpx

from app.config import settings

BASE_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def _consultar(params: dict) -> list[dict]:
    if not settings.mp_ticket:
        raise RuntimeError("Falta MP_TICKET en el archivo .env")
    params = {**params, "ticket": settings.mp_ticket}
    respuesta = httpx.get(BASE_URL, params=params, timeout=60)
    respuesta.raise_for_status()
    return respuesta.json().get("Listado", [])


def licitaciones_activas() -> list[dict]:
    """Listado resumido de todas las licitaciones publicadas hoy (código, nombre, fecha de cierre)."""
    return _consultar({"estado": "activas"})


def detalle(codigo: str) -> dict | None:
    """Ficha completa de una licitación: comprador, región, fechas, monto e ítems."""
    listado = _consultar({"codigo": codigo})
    return listado[0] if listado else None


def buscar_por_palabras(palabras: list[str]) -> list[dict]:
    """Filtra las licitaciones activas cuyo nombre contiene alguna de las palabras clave."""
    claves = [_normalizar(p) for p in palabras]
    return [
        lic for lic in licitaciones_activas()
        if any(clave in _normalizar(lic.get("Nombre", "")) for clave in claves)
    ]
