"""Ingesta: trae las licitaciones activas, aplica el filtro y guarda las relevantes sin duplicar.

Se puede ejecutar todas las veces que se quiera: si una licitación ya estaba guardada,
solo se actualizan sus datos y la fecha en que se vio por última vez (no se crea otra fila).
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app import mercadopublico
from app.db import Empresa, Ingesta, Licitacion, empresa_actual
from app.filtros import etapa_detalle, etapa_nombre


@dataclass
class Descarte:
    codigo: str
    nombre: str
    rechazos: list[str]


@dataclass
class ResultadoIngesta:
    ingesta: Ingesta
    nuevas: list[Licitacion] = field(default_factory=list)
    actualizadas: list[Licitacion] = field(default_factory=list)
    descartadas: list[Descarte] = field(default_factory=list)  # pasaron la etapa 1 pero no la 2
    errores: list[str] = field(default_factory=list)


def cargar_empresa(s: Session, ruta: str | Path) -> Empresa:
    """Carga el perfil desde un JSON. Si ya existe una empresa, la actualiza con lo del archivo."""
    datos = {k: v for k, v in json.loads(Path(ruta).read_text(encoding="utf-8")).items() if not k.startswith("_")}
    empresa = empresa_actual(s)
    if empresa is None:
        empresa = Empresa(**datos)
    else:
        for clave, valor in datos.items():
            setattr(empresa, clave, valor)
    s.add(empresa)
    s.commit()
    s.refresh(empresa)
    return empresa


def _fecha(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        return None


def _desde_detalle(detalle: dict, motivos: list[str]) -> dict:
    """Traduce el JSON de la API a las columnas de la tabla Licitacion."""
    comprador = detalle.get("Comprador") or {}
    fechas = detalle.get("Fechas") or {}
    items = (detalle.get("Items") or {}).get("Listado") or []
    return {
        "nombre": detalle.get("Nombre", "").strip(),
        "descripcion": (detalle.get("Descripcion") or "").strip(),
        "organismo": (comprador.get("NombreOrganismo") or "").strip(),
        "region": (comprador.get("RegionUnidad") or "").strip(),
        "comuna": (comprador.get("ComunaUnidad") or "").strip(),
        "monto": detalle.get("MontoEstimado"),
        "moneda": detalle.get("Moneda") or "CLP",
        "fecha_publicacion": _fecha(fechas.get("FechaPublicacion")),
        "fecha_cierre": _fecha(fechas.get("FechaCierre") or detalle.get("FechaCierre")),
        "estado": detalle.get("Estado") or "",
        "unspsc": sorted({str(i.get("CodigoProducto")) for i in items}),
        "productos": [(i.get("NombreProducto") or "").strip() for i in items],
        "motivos": motivos,
        "url_ficha": mercadopublico.url_ficha(detalle.get("CodigoExterno", "")),
    }


def ejecutar(s: Session, api=mercadopublico, al_avanzar=None) -> ResultadoIngesta:
    """Corre el embudo completo. `api` se puede reemplazar por una falsa en las pruebas."""
    empresa = empresa_actual(s)
    if empresa is None:
        raise RuntimeError("No hay perfil de empresa: ejecuta primero la carga del perfil")

    ingesta = Ingesta()
    s.add(ingesta)
    s.commit()
    s.refresh(ingesta)
    resultado = ResultadoIngesta(ingesta)

    # Etapa 1: una sola consulta con todas las activas, filtro por nombre
    activas = api.licitaciones_activas()
    candidatas = []
    for lic in activas:
        ev = etapa_nombre(lic, empresa)
        if ev.pasa:
            candidatas.append((lic, ev))
    ingesta.activas, ingesta.candidatas = len(activas), len(candidatas)

    # Etapa 2: una consulta de detalle por candidata
    for i, (lic, ev_nombre) in enumerate(candidatas, start=1):
        codigo = lic["CodigoExterno"]
        if al_avanzar:
            al_avanzar(i, len(candidatas), codigo)
        try:
            detalle = api.detalle(codigo)
        except mercadopublico.ErrorAPI as error:
            resultado.errores.append(str(error))
            continue
        if detalle is None:
            resultado.errores.append(f"{codigo}: la API no devolvió el detalle")
            continue

        ev = etapa_detalle(detalle, empresa)
        if not ev.pasa:
            resultado.descartadas.append(Descarte(codigo, lic.get("Nombre", ""), ev.rechazos))
            continue

        datos = _desde_detalle(detalle, ev_nombre.motivos + ev.motivos)
        existente = s.get(Licitacion, codigo)
        if existente is None:
            nueva = Licitacion(codigo=codigo, ingesta_id=ingesta.id, **datos)
            s.add(nueva)
            resultado.nuevas.append(nueva)
        else:
            for clave, valor in datos.items():
                setattr(existente, clave, valor)
            existente.ultima_vez = datetime.now()
            s.add(existente)
            resultado.actualizadas.append(existente)

    ingesta.relevantes = len(resultado.nuevas) + len(resultado.actualizadas)
    ingesta.nuevas = len(resultado.nuevas)
    ingesta.errores = len(resultado.errores)
    ingesta.fin = datetime.now()
    s.add(ingesta)
    s.commit()
    return resultado
