"""API web del Radar de Licitaciones. Ejecutar con: uvicorn app.main:app --reload"""
import tempfile

from fastapi import FastAPI, HTTPException, UploadFile

from app import mercadopublico
from app.extraccion import Hallazgo, extraer
from app.pdf import leer_paginas

app = FastAPI(title="Radar de Licitaciones")

PALABRAS_RUBRO = ["colchon", "colchones", "colchoneta"]


@app.get("/licitaciones")
def licitaciones_del_rubro() -> list[dict]:
    """Licitaciones activas de colchonería según el nombre de la licitación."""
    try:
        return mercadopublico.buscar_por_palabras(PALABRAS_RUBRO)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))


@app.get("/licitaciones/{codigo}")
def detalle_licitacion(codigo: str) -> dict:
    ficha = mercadopublico.detalle(codigo)
    if ficha is None:
        raise HTTPException(status_code=404, detail="Licitación no encontrada")
    return ficha


@app.post("/extraer")
async def extraer_bases(archivo: UploadFile) -> list[Hallazgo]:
    """Recibe las bases en PDF y devuelve requisitos, documentos, plazos, etc., con su página."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporal:
        temporal.write(await archivo.read())
    return extraer(leer_paginas(temporal.name))
