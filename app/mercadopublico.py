"""Cliente de la API de Mercado Público (licitaciones).

Documentación: https://api.mercadopublico.cl/documentos/Documentación%20API%20Mercado%20Publico%20-%20Licitaciones.pdf
La API entrega metadatos (fechas, montos, ítems UNSPSC), pero NO los PDF de las bases.
Si se hacen muchas consultas seguidas responde 429 (Too Many Requests): por eso hay pausa y reintentos.

Las bases tampoco se pueden descargar automáticamente desde la ficha web: la lista de adjuntos está
protegida con reCAPTCHA (spike del Sprint 1, 14/11/2026). Por eso se guarda el enlace a la ficha
y la persona descarga las bases y las sube al radar (carga asistida).
"""
import time

import httpx

from app.config import settings
from app.texto import normalizar

BASE_URL = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
FICHA_URL = "https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion={codigo}"
REINTENTOS = 4


class ErrorAPI(RuntimeError):
    """Error de la API con un mensaje que no incluye el ticket."""


def _consultar(params: dict) -> list[dict]:
    if not settings.mp_ticket:
        raise ErrorAPI("Falta MP_TICKET en el archivo .env")
    params = {**params, "ticket": settings.mp_ticket}

    for intento in range(1, REINTENTOS + 1):
        try:
            respuesta = httpx.get(BASE_URL, params=params, timeout=60)
        except httpx.HTTPError as error:
            estado = f"sin respuesta ({type(error).__name__})"
        else:
            if respuesta.status_code == 200:
                return respuesta.json().get("Listado", [])
            estado = f"HTTP {respuesta.status_code}"
            if respuesta.status_code not in (429, 500, 502, 503, 504):
                break  # error que no se arregla reintentando (p. ej. ticket inválido)
        if intento < REINTENTOS:
            time.sleep(settings.mp_pausa * 2**intento)  # espera creciente: 2, 4, 8 s...

    # El mensaje original de httpx incluye la URL con el ticket: nunca lo mostramos.
    consulta = {k: v for k, v in params.items() if k != "ticket"}
    raise ErrorAPI(f"La API de Mercado Público falló ({estado}) para {consulta}")


def url_ficha(codigo: str) -> str:
    """Enlace a la ficha pública de la licitación, donde están las bases para descargar."""
    return FICHA_URL.format(codigo=codigo)


def licitaciones_activas() -> list[dict]:
    """Listado resumido de todas las licitaciones publicadas hoy (código, nombre, fecha de cierre)."""
    return _consultar({"estado": "activas"})


def detalle(codigo: str) -> dict | None:
    """Ficha completa de una licitación: comprador, región, fechas, monto e ítems."""
    time.sleep(settings.mp_pausa)  # evita el 429 al pedir varios detalles seguidos
    listado = _consultar({"codigo": codigo})
    return listado[0] if listado else None


def buscar_por_palabras(palabras: list[str]) -> list[dict]:
    """Filtra las licitaciones activas cuyo nombre contiene alguna de las palabras clave."""
    claves = [normalizar(p) for p in palabras]
    return [
        lic for lic in licitaciones_activas()
        if any(clave in normalizar(lic.get("Nombre")) for clave in claves)
    ]
