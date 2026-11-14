"""Tareas largas en segundo plano (leer bases, calcular la conveniencia, responder preguntas) y su avance.

Leer unas bases con un modelo local toma varios minutos: el panel no puede quedarse esperando.
La tarea corre aparte y el panel consulta su estado cada pocos segundos.
El estado vive en memoria: si se reinicia el servidor, se pierde (suficiente para el MVP).
"""
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from app import db
from app.bases import hallazgos_vigentes, procesar_bases
from app import conveniencia, rag
from app.db import Licitacion


@dataclass
class Estado:
    descripcion: str  # el detalle (cambia con el avance)
    inicio: datetime
    titulo: str = "Procesando"  # lo que se destaca en el panel: "Buscando respuesta", "Leyendo las bases"...
    terminada: bool = False
    error: str = ""


_estados: dict[str, Estado] = {}
_candado = Lock()


def estado(codigo: str) -> Estado | None:
    return _estados.get(codigo)


def en_curso(codigo: str) -> bool:
    e = _estados.get(codigo)
    return e is not None and not e.terminada


def _actualizar(codigo: str, **cambios) -> None:
    with _candado:
        for clave, valor in cambios.items():
            setattr(_estados[codigo], clave, valor)


def iniciar(codigo: str, descripcion: str, titulo: str = "Procesando") -> None:
    with _candado:
        _estados[codigo] = Estado(descripcion, datetime.now(), titulo)


def evaluar_y_guardar(codigo: str) -> None:
    """Calcula el puntaje de conveniencia con los hallazgos vigentes y lo guarda en la licitación."""
    with db.sesion() as s:
        conveniencia.evaluar_y_guardar(s, s.get(Licitacion, codigo), hallazgos_vigentes(s, codigo))


def leer_bases(codigo: str, ruta_pdf: str) -> None:
    """Tarea completa de la carga asistida: leer, verificar, guardar y recalcular la conveniencia."""
    try:
        def avance(i, total, bloque):
            _actualizar(codigo, descripcion=f"Leyendo las bases: bloque {i} de {total} "
                                            f"(páginas {bloque[0]}-{bloque[-1]})")

        with db.sesion() as s:
            procesar_bases(s, codigo, ruta_pdf, al_avanzar=avance)
            _actualizar(codigo, descripcion="Preparando las bases para responder preguntas (embeddings)")
            rag.fragmentos_vigentes(s, codigo)
        _actualizar(codigo, descripcion="Calculando la conveniencia con los datos de las bases")
        evaluar_y_guardar(codigo)
        _actualizar(codigo, descripcion="Listo", terminada=True)
    except Exception as error:  # se muestra en el panel en vez de perderse en la consola
        _actualizar(codigo, descripcion="Falló", terminada=True, error=str(error))


def calcular_conveniencia(codigo: str) -> None:
    try:
        evaluar_y_guardar(codigo)
        _actualizar(codigo, descripcion="Listo", terminada=True)
    except Exception as error:
        _actualizar(codigo, descripcion="Falló", terminada=True, error=str(error))


def responder_pregunta(codigo: str, pregunta: str) -> None:
    try:
        with db.sesion() as s:
            rag.preguntar(s, codigo, pregunta)
        _actualizar(codigo, descripcion="Listo", terminada=True)
    except Exception as error:
        _actualizar(codigo, descripcion="Falló", terminada=True, error=str(error))


REVISION = "__revision__"  # clave del estado de la revisión de Mercado Público (no es una licitación)


def revisar_mercado_publico() -> None:
    """Lo mismo que python -m scripts.ingesta, lanzado desde el panel: ingesta + puntaje con la ficha."""
    from app.conveniencia import puntuar_sin_puntaje
    from app.ingesta import ejecutar, similitud_configurada

    try:
        def avance_detalle(i, total, codigo):
            _actualizar(REVISION, descripcion=f"Revisando el detalle de las candidatas: {i} de {total}")

        def avance_puntaje(i, total, codigo):
            _actualizar(REVISION, descripcion=f"Calculando el puntaje con la ficha: {i} de {total}")

        _actualizar(REVISION, descripcion="Descargando el listado de licitaciones activas de Mercado Público")
        with db.sesion() as s:
            r = ejecutar(s, al_avanzar=avance_detalle, similitud=similitud_configurada())
            _, errores = puntuar_sin_puntaje(s, al_avanzar=avance_puntaje)
        resumen = (f"Listo: {r.ingesta.activas} activas revisadas, {r.ingesta.relevantes} del rubro, "
                   f"{r.ingesta.nuevas} nuevas")
        _actualizar(REVISION, descripcion=resumen, terminada=True,
                    error="; ".join(r.errores + errores)[:300])
    except Exception as error:
        _actualizar(REVISION, descripcion="Falló", terminada=True, error=str(error))
