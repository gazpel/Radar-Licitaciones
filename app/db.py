"""Base de datos SQLite con SQLModel.

Cada clase con table=True es una tabla; cada atributo, una columna. Para pasar a PostgreSQL
basta cambiar DB_URL en el .env. Las listas (regiones, palabras, códigos) se guardan como JSON.

Las fechas se guardan en hora de Chile sin zona horaria (NaiveDatetime), igual que las entrega la API.

Tablas:
- Empresa: el perfil de la PyME que define qué licitaciones le sirven.
- Licitacion: las licitaciones que pasaron el filtro, con el motivo.
- Ingesta: el registro de cada ejecución (cuántas llegaron, pasaron y eran nuevas).
- Extraccion: cada lectura de unas bases con un modelo (archivo, modelo, tiempo).
- HallazgoGuardado: requisitos, plazos, etc. extraídos de las bases, con su nivel de verificación.
- Fragmento: trozos de las bases con su embedding, para responder preguntas (RAG, app/rag.py).
- Pregunta: cada pregunta hecha a las bases, con su respuesta, citas y nivel de verificación.
"""
from datetime import datetime
from pathlib import Path

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, inspect, text
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
    similitud: float | None = None  # parecido semántico con el perfil (0 a 1), ver app/busqueda.py
    puntaje: int | None = None  # conveniencia de 1 a 5, ver app/conveniencia.py
    conveniencia: dict | None = Field(default=None, sa_column=Column(JSON))  # a_favor, en_contra, resumen
    ingesta_id: int | None = Field(default=None, foreign_key="ingesta.id")  # en qué ingesta apareció
    primera_vez: NaiveDatetime = Field(default_factory=datetime.now)
    ultima_vez: NaiveDatetime = Field(default_factory=datetime.now)


class Extraccion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    licitacion_codigo: str = Field(foreign_key="licitacion.codigo", index=True)
    archivo: str  # ruta del PDF de las bases
    paginas: int
    modelo: str
    segundos: float
    fecha: NaiveDatetime = Field(default_factory=datetime.now)
    en_curso: bool | None = False  # True mientras se leen las bases (los hallazgos se guardan por bloque)


class HallazgoGuardado(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    extraccion_id: int = Field(foreign_key="extraccion.id", index=True)
    licitacion_codigo: str = Field(foreign_key="licitacion.codigo", index=True)
    tipo: str
    descripcion: str
    pagina: int
    cita: str  # lo que citó el modelo
    texto_real: str = ""  # lo que dice el PDF (difiere de la cita cuando el nivel es "aproximada")
    nivel: str  # textual, aproximada, interpretado o sin_respaldo (ver app/verificacion.py)
    confiable: bool = False


class Fragmento(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    extraccion_id: int = Field(foreign_key="extraccion.id", index=True)
    licitacion_codigo: str = Field(foreign_key="licitacion.codigo", index=True)
    pagina: int
    orden: int  # posición del fragmento dentro de las bases
    texto: str
    vector: bytes | None = None  # embedding (float32); vacío si no se pudo calcular


class Pregunta(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    licitacion_codigo: str = Field(foreign_key="licitacion.codigo", index=True)
    pregunta: str
    encontrado: bool
    respuesta: str
    nivel: str  # textual, aproximada, interpretado o sin_respaldo
    citas: list[dict] = Field(default_factory=list, sa_column=Column(JSON))  # pagina, cita, nivel, texto_real
    fragmentos: list[int] = Field(default_factory=list, sa_column=Column(JSON))  # páginas de lo recuperado
    modelo: str
    segundos: float
    fecha: NaiveDatetime = Field(default_factory=datetime.now)


def _crear_motor(url: str):
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url)


motor = _crear_motor(settings.db_url)


def crear_tablas(motor_=None) -> None:
    """Crea las tablas que no existan y agrega las columnas nuevas (no borra datos)."""
    motor_ = motor_ or motor
    SQLModel.metadata.create_all(motor_)
    _agregar_columnas_nuevas(motor_)


def _agregar_columnas_nuevas(motor_) -> None:
    """Migración mínima: si a una tabla le falta una columna definida en el código, se agrega vacía.

    create_all solo crea tablas nuevas; no modifica las existentes. Esto evita borrar radar.db
    cada vez que un sprint agrega un campo. (Para cambios mayores se usaría Alembic.)
    """
    inspector = inspect(motor_)
    with motor_.begin() as conexion:
        for tabla in SQLModel.metadata.sorted_tables:
            existentes = {c["name"] for c in inspector.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name not in existentes:
                    tipo = columna.type.compile(motor_.dialect)
                    conexion.execute(text(f'ALTER TABLE "{tabla.name}" ADD COLUMN "{columna.name}" {tipo}'))


def sesion(motor_=None) -> Session:
    return Session(motor_ or motor)


def empresa_actual(s: Session) -> Empresa | None:
    """Por ahora hay una sola empresa (la del caso de estudio)."""
    return s.exec(select(Empresa)).first()
