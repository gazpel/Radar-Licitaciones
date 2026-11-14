"""Resumen del día (HU-06): qué hay de nuevo y qué cierra pronto.

Lo usa el panel (página de inicio) y, desde el Sprint 6, el correo diario.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.conveniencia import PUNTAJE_PARA_BASES
from app.db import Empresa, Extraccion, Ingesta, Licitacion, empresa_actual

DIAS_ALERTA = 5  # licitaciones que cierran dentro de estos días se marcan como urgentes


@dataclass
class Resumen:
    fecha: datetime
    empresa: Empresa | None
    ultima_ingesta: Ingesta | None
    nuevas: list[Licitacion] = field(default_factory=list)  # aparecieron en las últimas 24 horas
    cierran_pronto: list[Licitacion] = field(default_factory=list)
    abiertas: list[Licitacion] = field(default_factory=list)  # todas las que no han cerrado
    con_bases: set[str] = field(default_factory=set)  # códigos de las que ya tienen las bases leídas
    por_cargar: list[Licitacion] = field(default_factory=list)  # conviene descargar sus bases (opción B)


def dias_para_cierre(licitacion: Licitacion, ahora: datetime) -> int | None:
    if licitacion.fecha_cierre is None:
        return None
    return (licitacion.fecha_cierre - ahora).days


def _orden(licitacion: Licitacion) -> tuple:
    """Primero las de mayor puntaje; sin puntaje al final; a igual puntaje, la que cierra antes."""
    puntaje = licitacion.puntaje if licitacion.puntaje is not None else 0
    cierre = licitacion.fecha_cierre or datetime.max
    return (-puntaje, cierre)


def resumen_del_dia(s: Session, ahora: datetime | None = None) -> Resumen:
    ahora = ahora or datetime.now()
    ultima = s.exec(select(Ingesta).where(Ingesta.fin.is_not(None)).order_by(Ingesta.id.desc())).first()
    abiertas = list(s.exec(select(Licitacion).where(Licitacion.fecha_cierre >= ahora)))
    abiertas.sort(key=_orden)
    limite = ahora + timedelta(days=DIAS_ALERTA)
    con_bases = set(s.exec(select(Extraccion.licitacion_codigo)))
    return Resumen(
        fecha=ahora,
        empresa=empresa_actual(s),
        ultima_ingesta=ultima,
        nuevas=[l for l in abiertas if l.primera_vez >= ahora - timedelta(hours=24)],
        cierran_pronto=sorted((l for l in abiertas if l.fecha_cierre <= limite), key=lambda l: l.fecha_cierre),
        abiertas=abiertas,
        con_bases=con_bases,
        por_cargar=[l for l in abiertas
                    if l.codigo not in con_bases and (l.puntaje or 0) >= PUNTAJE_PARA_BASES],
    )


def resumen_texto(r: Resumen) -> str:
    """Versión en texto plano (para la consola y el correo)."""
    lineas = [f"Radar de Licitaciones · {r.fecha:%d/%m/%Y}"]
    if r.empresa:
        lineas.append(r.empresa.nombre)
    lineas += ["", f"{len(r.nuevas)} nuevas en las últimas 24 horas · {len(r.abiertas)} abiertas · "
                   f"{len(r.cierran_pronto)} cierran en {DIAS_ALERTA} días o menos · "
                   f"{len(r.por_cargar)} con bases por cargar", ""]
    for titulo, grupo in (("NUEVAS", r.nuevas), ("CIERRAN PRONTO", r.cierran_pronto),
                          (f"CONVIENE LEER SUS BASES (puntaje {PUNTAJE_PARA_BASES} o más)", r.por_cargar)):
        if grupo:
            lineas.append(titulo)
            for l in grupo:
                puntaje = f"{l.puntaje}/5" if l.puntaje else "sin puntaje"
                lineas.append(f"  - {l.codigo} · {l.nombre[:70]} · cierra {l.fecha_cierre:%d/%m %H:%M} · {puntaje}")
            lineas.append("")
    return "\n".join(lineas)
