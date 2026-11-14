"""Base de datos SQLite con SQLModel.

Cada clase con table=True es una tabla; cada atributo, una columna. Para pasar a PostgreSQL
basta cambiar DB_URL en el .env. Las listas (regiones, palabras, códigos) se guardan como JSON.

Las fechas se guardan en hora de Chile sin zona horaria (NaiveDatetime), igual que las entrega la API.

Tablas:
- Empresa: el perfil de la PyME que define qué licitaciones le sirven.
- Licitacion: las licitaciones que pasaron el filtro, con el motivo.
- Ingesta: el registro de cada ejecución (cuántas llegaron, pasaron y eran nuevas).
- HallazgoGuardado: requisitos, plazos, etc. extraídos de las bases (se llena desde el Sprint 2).
"""
from datetime import datetime
from pathlib import Path

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.config import settings


class Empresa(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    nombre: str
    rubro: str
    regiones: list[str] = Field(default_factory=list, sa_column=Column(JSON))  # vacía = todo Chile
    palabras_clave: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    palabras_excluidas: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    unspsc: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    monto_min: float | None = None
    monto_max: float | None = None


class Ingesta(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    inicio: NaiveDatetime = Field(default_factory=datetime.now)
    fin: NaiveDatetime | None = None
    activas: int = 0  # licitaciones activas en la API
    candidatas: int = 0  # pasaron la etapa 1 (nombre)
    relevantes: int = 0  # pasaron la etapa 2 (detalle)
    nuevas: int = 0  # relevantes que no estaban en la base
    errores: int = 0


class Licitacion(SQLModel, table=True):
    codigo: str = Field(primary_key=True)  # CodigoExterno, p. ej. "2324-136-LE26"
    nombre: str
    descripcion: str = ""
    organismo: str = ""
    region: str = ""
    comuna: str = ""
    monto: float | None = None  # None cuando el organismo no lo publica
    moneda: str = "CLP"
    fecha_publicacion: NaiveDatetime | None = None
    fecha_cierre: NaiveDatetime | None = None
    estado: str = ""
    unspsc: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    productos: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    motivos: list[str] = Field(default_factory=list, sa_column=Column(JSON))  # por qué pasó el filtro
    url_ficha: str = ""  # ficha pública, desde donde la persona descarga las bases
    ingesta_id: int | None = Field(default=None, foreign_key="ingesta.id")  # en qué ingesta apareció
    primera_vez: NaiveDatetime = Field(default_factory=datetime.now)
    ultima_vez: NaiveDatetime = Field(default_factory=datetime.now)


class HallazgoGuardado(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    licitacion_codigo: str = Field(foreign_key="licitacion.codigo", index=True)
    tipo: str
    descripcion: str
    pagina: int
    cita: str
    verificado: bool = False


def _crear_motor(url: str):
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url)


motor = _crear_motor(settings.db_url)


def crear_tablas(motor_=None) -> None:
    """Crea las tablas que no existan (no borra datos)."""
    SQLModel.metadata.create_all(motor_ or motor)


def sesion(motor_=None) -> Session:
    return Session(motor_ or motor)


def empresa_actual(s: Session) -> Empresa | None:
    """Por ahora hay una sola empresa (la del caso de estudio)."""
    return s.exec(select(Empresa)).first()
