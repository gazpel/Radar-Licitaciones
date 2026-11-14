"""API web del Radar de Licitaciones. Ejecutar con: uvicorn app.main:app --reload

Los datos salen de la base SQLite que llena la ingesta (python -m scripts.ingesta),
no de la API de Mercado Público: así la página responde rápido y no gasta consultas.
"""
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile
from sqlmodel import select

from app import db
from app.db import Empresa, Ingesta, Licitacion
from app.extraccion import Hallazgo, extraer
from app.pdf import leer_paginas


@asynccontextmanager
async def al_iniciar(app: FastAPI):
    db.crear_tablas()
    yield


app = FastAPI(title="Radar de Licitaciones", lifespan=al_iniciar)


@app.get("/empresa")
def perfil_empresa() -> Empresa:
    with db.sesion() as s:
        empresa = db.empresa_actual(s)
    if empresa is None:
        raise HTTPException(status_code=404, detail="No hay perfil: ejecuta python -m scripts.ingesta")
    return empresa


@app.get("/licitaciones")
def licitaciones_del_rubro(incluir_cerradas: bool = False) -> list[Licitacion]:
    """Licitaciones guardadas por la ingesta, de la que cierra antes a la que cierra después."""
    with db.sesion() as s:
        consulta = select(Licitacion).order_by(Licitacion.fecha_cierre)
        if not incluir_cerradas:
            consulta = consulta.where(Licitacion.fecha_cierre >= datetime.now())
        return list(s.exec(consulta))


@app.get("/licitaciones/{codigo}")
def detalle_licitacion(codigo: str) -> Licitacion:
    with db.sesion() as s:
        licitacion = s.get(Licitacion, codigo)
    if licitacion is None:
        raise HTTPException(status_code=404, detail="Licitación no encontrada en la base")
    return licitacion


@app.get("/ingestas")
def historial_ingestas(limite: int = 10) -> list[Ingesta]:
    """Últimas ejecuciones de la ingesta, la más reciente primero."""
    with db.sesion() as s:
        return list(s.exec(select(Ingesta).order_by(Ingesta.id.desc()).limit(limite)))


@app.post("/extraer")
async def extraer_bases(archivo: UploadFile) -> list[Hallazgo]:
    """Recibe las bases en PDF y devuelve requisitos, documentos, plazos, etc., con su página."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporal:
        temporal.write(await archivo.read())
    return extraer(leer_paginas(temporal.name))
