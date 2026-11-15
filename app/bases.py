"""Carga asistida de las bases: la persona sube el PDF y el radar lo lee, verifica y guarda.

Las bases no se descargan solas porque la ficha web las protege con reCAPTCHA (spike del Sprint 1).
Si la licitación todavía no está en la base (p. ej. no pasó el filtro), se agrega desde la API.
"""
import shutil
import time
from pathlib import Path

from sqlmodel import Session, select

from app import mercadopublico
from app.config import settings
from app.db import Extraccion, HallazgoGuardado, Licitacion
from app.extraccion import Hallazgo, extraer
from app.ingesta import datos_licitacion
from app.pdf import leer_paginas

CARPETA_BASES = Path("data/bases")
MIN_CARACTERES_POR_PAGINA = 50  # menos que esto: probablemente un PDF escaneado (imagen sin texto)


class PDFSinTexto(ValueError):
    """El PDF no tiene texto que leer (escaneado o protegido)."""


def registrar_licitacion(s: Session, codigo: str, api=mercadopublico) -> Licitacion:
    """Devuelve la licitación; si no estaba guardada, la trae desde la API."""
    licitacion = s.get(Licitacion, codigo)
    if licitacion is not None:
        return licitacion
    detalle = api.detalle(codigo)
    if detalle is None:
        raise ValueError(f"La licitación {codigo} no existe en Mercado Público")
    licitacion = Licitacion(codigo=codigo, **datos_licitacion(detalle, ["agregada a mano al cargar sus bases"]))
    s.add(licitacion)
    s.commit()
    s.refresh(licitacion)
    return licitacion


def procesar_bases(s: Session, codigo: str, ruta_pdf: str | Path, modelo: str | None = None,
                   think: bool | None = None, al_avanzar=None, api=mercadopublico,
                   extractor=extraer) -> tuple[Extraccion, list[Hallazgo]]:
    """Guarda el PDF como data/bases/<código>.pdf, extrae los hallazgos y los guarda verificados."""
    registrar_licitacion(s, codigo, api)

    CARPETA_BASES.mkdir(parents=True, exist_ok=True)
    destino = CARPETA_BASES / f"{codigo}.pdf"
    if Path(ruta_pdf).resolve() != destino.resolve():
        shutil.copyfile(ruta_pdf, destino)

    paginas = leer_paginas(destino)
    if sum(len(p) for p in paginas) < MIN_CARACTERES_POR_PAGINA * max(1, len(paginas)):
        raise PDFSinTexto("El PDF casi no tiene texto: puede ser un documento escaneado. Súbelo en otra versión.")

    if modelo is None:  # el modelo configurado para leer bases (si no hay, el general)
        if settings.llm_model_extraccion:
            modelo, think = settings.llm_model_extraccion, settings.llm_think_extraccion
        else:
            modelo, think = settings.llm_model, settings.llm_think

    # La lectura se guarda desde el comienzo, "en curso", y cada bloque se guarda apenas sale:
    # así el panel muestra los datos a medida que aparecen.
    inicio = time.time()
    extraccion = Extraccion(licitacion_codigo=codigo, archivo=str(destino), paginas=len(paginas),
                            modelo=modelo, segundos=0, en_curso=True)
    s.add(extraccion)
    s.commit()
    s.refresh(extraccion)

    guardados: set[int] = set()

    def guardar(hallazgos: list[Hallazgo]) -> None:
        for h in hallazgos:
            guardados.add(id(h))
            s.add(HallazgoGuardado(
                extraccion_id=extraccion.id, licitacion_codigo=codigo, tipo=h.tipo.value,
                descripcion=h.descripcion, pagina=h.pagina, cita=h.cita, texto_real=h.texto_real,
                nivel=h.nivel.value, confiable=h.confiable,
            ))
        extraccion.segundos = round(time.time() - inicio, 1)
        s.add(extraccion)
        s.commit()

    try:
        hallazgos = extractor(paginas, al_avanzar=al_avanzar, modelo=modelo, think=think, al_hallar=guardar)
    except Exception:
        # Una lectura a medias no debe reemplazar a la anterior: se borra y queda la que había
        s.rollback()
        for h in s.exec(select(HallazgoGuardado).where(HallazgoGuardado.extraccion_id == extraccion.id)):
            s.delete(h)
        s.delete(extraccion)
        s.commit()
        raise

    guardar([h for h in hallazgos if id(h) not in guardados])  # por si el extractor no avisó por bloque
    extraccion.segundos = round(time.time() - inicio, 1)
    extraccion.en_curso = False
    s.add(extraccion)
    s.commit()
    s.refresh(extraccion)  # recarga los datos para poder usarla después de cerrar la sesión
    return extraccion, hallazgos


def ultima_extraccion(s: Session, codigo: str) -> Extraccion | None:
    consulta = (select(Extraccion).where(Extraccion.licitacion_codigo == codigo)
                .order_by(Extraccion.id.desc()))
    return s.exec(consulta).first()


def hallazgos_vigentes(s: Session, codigo: str) -> list[HallazgoGuardado]:
    """Los hallazgos de la última lectura de las bases de esa licitación."""
    extraccion = ultima_extraccion(s, codigo)
    if extraccion is None:
        return []
    consulta = (select(HallazgoGuardado).where(HallazgoGuardado.extraccion_id == extraccion.id)
                .order_by(HallazgoGuardado.tipo, HallazgoGuardado.pagina))
    return list(s.exec(consulta))
