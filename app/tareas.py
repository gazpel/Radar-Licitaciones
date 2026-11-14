"""Tareas largas en segundo plano (leer bases, calcular la conveniencia) y su avance.

Leer unas bases con un modelo local toma varios minutos: el panel no puede quedarse esperando.
La tarea corre aparte y el panel consulta su estado cada pocos segundos.
El estado vive en memoria: si se reinicia el servidor, se pierde (suficiente para el MVP).
"""
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from app import db
from app.bases import hallazgos_vigentes, procesar_bases
from app.conveniencia import evaluar
from app.db import Licitacion, empresa_actual


@dataclass
class Estado:
    descripcion: str
    inicio: datetime
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


def iniciar(codigo: str, descripcion: str) -> None:
    with _candado:
        _estados[codigo] = Estado(descripcion, datetime.now())


def evaluar_y_guardar(codigo: str) -> None:
    """Calcula el puntaje de conveniencia con los hallazgos vigentes y lo guarda en la licitación."""
    with db.sesion() as s:
        licitacion = s.get(Licitacion, codigo)
        hallazgos = hallazgos_vigentes(s, codigo)
        resultado = evaluar(licitacion, empresa_actual(s), hallazgos)
        licitacion.puntaje = resultado.puntaje
        licitacion.conveniencia = {
            **resultado.model_dump(),
            "con_bases": bool(hallazgos),
            "fecha": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        s.add(licitacion)
        s.commit()


def leer_bases(codigo: str, ruta_pdf: str) -> None:
    """Tarea completa de la carga asistida: leer, verificar, guardar y recalcular la conveniencia."""
    try:
        def avance(i, total, bloque):
            _actualizar(codigo, descripcion=f"Leyendo las bases: bloque {i} de {total} "
                                            f"(páginas {bloque[0]}-{bloque[-1]})")

        with db.sesion() as s:
            procesar_bases(s, codigo, ruta_pdf, al_avanzar=avance)
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
