"""API web y panel del Radar de Licitaciones. Ejecutar con: uvicorn app.main:app --reload

- Panel para personas: http://localhost:8000/ (rutas en app/panel.py)
- API JSON para programas: http://localhost:8000/docs (rutas de este archivo)

Los datos salen de la base SQLite que llena la ingesta (python -m scripts.ingesta),
no de la API de Mercado Público: así la página responde rápido y no gasta consultas.
"""
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from sqlmodel import select

from app import db, mercadopublico, panel
from app.bases import PDFSinTexto, hallazgos_vigentes, procesar_bases, ultima_extraccion
from app.db import Empresa, Extraccion, HallazgoGuardado, Ingesta, Licitacion


@asynccontextmanager
async def al_iniciar(app: FastAPI):
    db.crear_tablas()
    yield


app = FastAPI(title="Radar de Licitaciones", lifespan=al_iniciar)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(panel.router)


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


@app.get("/licitaciones/{codigo}/hallazgos")
def hallazgos_licitacion(codigo: str) -> list[HallazgoGuardado]:
    """Requisitos, documentos, plazos, etc. de la última lectura de las bases, con su nivel de verificación."""
    with db.sesion() as s:
        return hallazgos_vigentes(s, codigo)


@app.post("/licitaciones/{codigo}/bases")
def subir_bases(codigo: str, archivo: UploadFile) -> Extraccion:
    """Carga asistida: recibe el PDF de las bases (descargado a mano desde la ficha) y lo procesa.

    Puede tardar varios minutos con un modelo local. Es una función normal (no async) para que
    FastAPI la ejecute en otro hilo y el resto de la API siga respondiendo mientras tanto.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporal:
        temporal.write(archivo.file.read())
    with db.sesion() as s:
        try:
            procesar_bases(s, codigo, temporal.name)
        except PDFSinTexto as error:
            raise HTTPException(status_code=422, detail=str(error))
        except (ValueError, mercadopublico.ErrorAPI) as error:
            raise HTTPException(status_code=404, detail=str(error))
        return ultima_extraccion(s, codigo)
