"""Panel web para la PyME (HU-07): páginas HTML hechas con plantillas Jinja2.

Las plantillas están en app/templates/: son HTML con huecos {{ ... }} que se llenan con los datos.
Las rutas de app/main.py devuelven JSON (para programas); las de aquí devuelven páginas (para personas).
"""
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import db, tareas
from app.bases import hallazgos_vigentes, ultima_extraccion
from app.db import Licitacion
from app.resumen import DIAS_ALERTA, dias_para_cierre, resumen_del_dia, resumen_texto
from app.verificacion import ICONO, Nivel

router = APIRouter()
plantillas = Jinja2Templates(directory=Path(__file__).parent / "templates")

TAMANO_MAXIMO_PDF = 20 * 1024 * 1024  # 20 MB

TIPOS = {  # en el orden en que se muestran
    "informacion_general": "Información general",
    "plazo": "Plazos y fechas",
    "requisito": "Requisitos para postular",
    "documento": "Documentos a presentar",
    "garantia": "Garantías",
    "criterio_evaluacion": "Criterios de evaluación",
    "multa": "Multas",
}
NIVELES = {
    "textual": (ICONO[Nivel.textual], "Está tal cual en las bases"),
    "aproximada": (ICONO[Nivel.aproximada], "La cita del modelo difiere un poco: se muestra el texto real del PDF"),
    "interpretado": (ICONO[Nivel.interpretado], "Revisar: la descripción tiene datos que no están en la cita"),
    "sin_respaldo": (ICONO[Nivel.sin_respaldo], "Sin respaldo en el PDF: no se muestra como dato"),
}


def _pesos(monto: float | None) -> str:
    return "No publicado" if monto is None else f"${monto:,.0f}".replace(",", ".")


plantillas.env.filters["pesos"] = _pesos


@router.get("/", include_in_schema=False)
def inicio(request: Request):
    with db.sesion() as s:
        r = resumen_del_dia(s)
        con_bases = {l.codigo for l in r.abiertas if ultima_extraccion(s, l.codigo)}
    return plantillas.TemplateResponse(request, "inicio.html", {
        "r": r, "con_bases": con_bases, "dias": lambda l: dias_para_cierre(l, r.fecha),
        "dias_alerta": DIAS_ALERTA,
    })


@router.get("/resumen.txt", include_in_schema=False, response_class=PlainTextResponse)
def resumen_plano():
    with db.sesion() as s:
        return resumen_texto(resumen_del_dia(s))


@router.get("/perfil", include_in_schema=False)
def perfil(request: Request):
    with db.sesion() as s:
        empresa = db.empresa_actual(s)
    return plantillas.TemplateResponse(request, "perfil.html", {"empresa": empresa})


@router.get("/licitacion/{codigo}", include_in_schema=False)
def ficha(request: Request, codigo: str):
    with db.sesion() as s:
        licitacion = s.get(Licitacion, codigo)
        if licitacion is None:
            raise HTTPException(status_code=404, detail="Licitación no encontrada")
        extraccion = ultima_extraccion(s, codigo)
        hallazgos = hallazgos_vigentes(s, codigo)
    grupos = defaultdict(list)
    ocultos = []
    for h in hallazgos:
        (ocultos if h.nivel == Nivel.sin_respaldo.value else grupos[h.tipo]).append(h)
    conteo = {n: sum(h.nivel == n for h in hallazgos) for n in NIVELES}
    return plantillas.TemplateResponse(request, "licitacion.html", {
        "l": licitacion, "extraccion": extraccion, "grupos": grupos, "ocultos": ocultos, "conteo": conteo,
        "tipos": TIPOS, "niveles": NIVELES, "estado": tareas.estado(codigo), "en_curso": tareas.en_curso(codigo),
        "dias": dias_para_cierre(licitacion, datetime.now()), "dias_alerta": DIAS_ALERTA,
    })


@router.post("/licitacion/{codigo}/bases", include_in_schema=False)
def subir_bases(codigo: str, archivo: UploadFile, segundo_plano: BackgroundTasks):
    """Carga asistida desde el panel: valida el archivo y lo procesa en segundo plano."""
    if tareas.en_curso(codigo):
        raise HTTPException(status_code=409, detail="Ya se están procesando las bases de esta licitación")
    contenido = archivo.file.read(TAMANO_MAXIMO_PDF + 1)
    if len(contenido) > TAMANO_MAXIMO_PDF:
        raise HTTPException(status_code=413, detail="El PDF supera los 20 MB")
    if not contenido.startswith(b"%PDF"):  # se revisa el contenido, no solo la extensión del nombre
        raise HTTPException(status_code=415, detail="El archivo no es un PDF")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporal:
        temporal.write(contenido)
    tareas.iniciar(codigo, "En cola para leer las bases")
    segundo_plano.add_task(tareas.leer_bases, codigo, temporal.name)
    return RedirectResponse(f"/licitacion/{codigo}", status_code=303)


@router.post("/licitacion/{codigo}/conveniencia", include_in_schema=False)
def recalcular_conveniencia(codigo: str, segundo_plano: BackgroundTasks):
    if not tareas.en_curso(codigo):
        tareas.iniciar(codigo, "Calculando la conveniencia")
        segundo_plano.add_task(tareas.calcular_conveniencia, codigo)
    return RedirectResponse(f"/licitacion/{codigo}", status_code=303)
