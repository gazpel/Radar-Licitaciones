"""Panel web para la PyME (HU-07): páginas HTML hechas con plantillas Jinja2.

Las plantillas están en app/templates/: son HTML con huecos {{ ... }} que se llenan con los datos.
Las rutas de app/main.py devuelven JSON (para programas); las de aquí devuelven páginas (para personas).
"""
import tempfile
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlmodel import col, or_, select
from fastapi.templating import Jinja2Templates

from app import db, descargas, mercadopublico, rag, tareas
from app.bases import hallazgos_vigentes, ultima_extraccion
from app.db import Licitacion
from app.conveniencia import PUNTAJE_PARA_BASES
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
EJEMPLOS_DE_PREGUNTAS = [
    "¿Qué pasa si me atraso en la entrega?",
    "¿En cuántos días me pagan?",
    "¿Piden garantía de fiel cumplimiento? ¿De cuánto?",
    "¿Cómo se evalúan las ofertas?",
]
NIVELES = {
    "textual": (ICONO[Nivel.textual], "Está tal cual en las bases"),
    "aproximada": (ICONO[Nivel.aproximada], "La cita del modelo difiere un poco: se muestra el texto real del PDF"),
    "interpretado": (ICONO[Nivel.interpretado], "Revisar: la descripción tiene datos que no están en la cita"),
    "sin_respaldo": (ICONO[Nivel.sin_respaldo], "Sin respaldo en el PDF: no se muestra como dato"),
}


def _pesos(monto: float | None) -> str:
    return "No publicado" if monto is None else f"${monto:,.0f}".replace(",", ".")


def _tamano(bytes_: int) -> str:
    return f"{bytes_ / 1024:.0f} KB" if bytes_ < 1024 * 1024 else f"{bytes_ / 1024 / 1024:.1f} MB".replace(".", ",")


PALABRAS_MENORES = {"a", "al", "con", "de", "del", "e", "el", "en", "la", "las", "los", "o", "para", "por", "u", "y"}


def _titulo(texto: str) -> str:
    """Mercado Público entrega muchos nombres EN MAYÚSCULAS: se muestran como título, más fáciles de leer.

    "ADQUISICIÓN DE COLCHONES 1 PLAZA" -> "Adquisición de Colchones 1 Plaza". Si el texto ya viene
    con minúsculas, se deja tal cual (lo escribió así el organismo).
    """
    letras = [c for c in texto if c.isalpha()]
    if not letras or sum(c.isupper() for c in letras) / len(letras) < 0.7:
        return texto
    palabras = []
    for i, palabra in enumerate(texto.split()):
        minuscula = palabra.lower()
        if i > 0 and minuscula in PALABRAS_MENORES:
            palabras.append(minuscula)
        elif palabra in ("I", "II", "III") or any(c.isdigit() for c in palabra):
            palabras.append(palabra)  # "I Municipalidad", "N°138", "1 PLAZA"
        else:  # mayúscula en la primera letra, aunque la palabra empiece con comillas o paréntesis
            i_letra = next((j for j, c in enumerate(minuscula) if c.isalpha()), 0)
            palabras.append(minuscula[:i_letra] + minuscula[i_letra:i_letra + 1].upper() + minuscula[i_letra + 1:])
    return " ".join(palabras)


plantillas.env.filters["pesos"] = _pesos
plantillas.env.filters["titulo"] = _titulo
plantillas.env.filters["tamano"] = _tamano


@router.get("/", include_in_schema=False)
def inicio(request: Request, q: str = ""):
    q = " ".join(q.split())[:100]
    with db.sesion() as s:
        r = resumen_del_dia(s)
        if q:
            exacta = s.get(Licitacion, q.upper())
            if exacta is not None:  # se escribió un código: directo a la licitación
                return RedirectResponse(f"/licitacion/{exacta.codigo}", status_code=303)
            patron = f"%{q}%"
            resultados = list(s.exec(select(Licitacion).where(or_(
                col(Licitacion.codigo).ilike(patron), col(Licitacion.nombre).ilike(patron),
                col(Licitacion.organismo).ilike(patron))).order_by(col(Licitacion.fecha_cierre).desc()).limit(50)))
        else:
            resultados = []
        abiertas = {l.codigo for l in r.abiertas}
        anteriores = [l for l in s.exec(select(Licitacion).order_by(col(Licitacion.fecha_cierre).desc()))
                      if l.codigo not in abiertas]
    return plantillas.TemplateResponse(request, "inicio.html", {
        "r": r, "dias": lambda l: dias_para_cierre(l, r.fecha), "dias_alerta": DIAS_ALERTA,
        "puntaje_para_bases": PUNTAJE_PARA_BASES, "q": q, "resultados": resultados, "anteriores": anteriores,
        "revision": tareas.estado(tareas.REVISION), "revisando": tareas.en_curso(tareas.REVISION),
    })


@router.post("/revisar", include_in_schema=False)
def revisar_ahora():
    """Botón "Revisar Mercado Público ahora": la misma ingesta diaria, en segundo plano."""
    if not tareas.en_curso(tareas.REVISION):
        tareas.iniciar(tareas.REVISION, "Empezando la revisión de Mercado Público", "Revisando Mercado Público")
        threading.Thread(target=tareas.revisar_mercado_publico, daemon=True).start()
    return RedirectResponse("/", status_code=303)


@router.get("/tarea/{clave}/estado", include_in_schema=False)
def estado_tarea(clave: str) -> dict:
    """Lo consulta la página cada 2 segundos mientras hay una tarea en curso (ver base.html)."""
    e = tareas.estado(clave)
    if e is None:
        return {"en_curso": False}
    return {"en_curso": not e.terminada, "titulo": e.titulo, "descripcion": e.descripcion}


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
def ficha(request: Request, codigo: str, listo: str = ""):
    with db.sesion() as s:
        licitacion = s.get(Licitacion, codigo)
        if licitacion is None:
            raise HTTPException(status_code=404, detail="Licitación no encontrada")
        extraccion = ultima_extraccion(s, codigo)
        hallazgos = hallazgos_vigentes(s, codigo)
        preguntas = rag.historial(s, codigo)
    grupos = defaultdict(list)
    ocultos = []
    for h in hallazgos:
        (ocultos if h.nivel == Nivel.sin_respaldo.value else grupos[h.tipo]).append(h)
    conteo = {n: sum(h.nivel == n for h in hallazgos) for n in NIVELES}

    # Opción A: si se abrió la ficha desde el panel, buscar las bases en la carpeta de descargas
    esperando = None if tareas.en_curso(codigo) else descargas.esperando_desde(codigo)
    encontrados = descargas.candidatos(codigo, esperando) if esperando else []
    elegido = descargas.eleccion_automatica(encontrados)
    if elegido and descargas.reclamar(codigo, esperando):  # sin dudas: se lee solo
        _leer_en_segundo_plano(codigo, elegido.ruta, f"Encontré «{elegido.nombre}» en Descargas")
        esperando, encontrados = None, []

    return plantillas.TemplateResponse(request, "licitacion.html", {
        "l": licitacion, "extraccion": extraccion, "grupos": grupos, "ocultos": ocultos, "conteo": conteo,
        "tipos": TIPOS, "niveles": NIVELES, "estado": tareas.estado(codigo), "en_curso": tareas.en_curso(codigo),
        "dias": dias_para_cierre(licitacion, datetime.now()), "dias_alerta": DIAS_ALERTA,
        "esperando": esperando, "encontrados": encontrados, "carpeta_descargas": descargas.carpeta(),
        "puntaje_para_bases": PUNTAJE_PARA_BASES, "preguntas": preguntas, "ejemplos": EJEMPLOS_DE_PREGUNTAS,
        "largo_pregunta": rag.LARGO_MAXIMO_PREGUNTA, "recien_terminada": bool(listo),
    })


@router.post("/licitacion/{codigo}/preguntar", include_in_schema=False)
def preguntar(codigo: str, segundo_plano: BackgroundTasks, pregunta: str = Form(...)):
    """Pregunta a las bases (RAG). Se responde en segundo plano: toma unos segundos con el modelo local."""
    if tareas.en_curso(codigo):
        raise HTTPException(status_code=409, detail="Espera a que termine la tarea en curso")
    pregunta = " ".join(pregunta.split())
    if not 5 <= len(pregunta) <= rag.LARGO_MAXIMO_PREGUNTA:
        raise HTTPException(status_code=422, detail=f"La pregunta debe tener entre 5 y {rag.LARGO_MAXIMO_PREGUNTA} caracteres")
    with db.sesion() as s:
        if ultima_extraccion(s, codigo) is None:
            raise HTTPException(status_code=409, detail="Primero hay que leer las bases de esta licitación")
    tareas.iniciar(codigo, f"Pregunta: «{pregunta}». Se buscan los fragmentos más relevantes de las bases y el "
                           "modelo local redacta la respuesta con su cita (unos 20 a 30 segundos)",
                   "Buscando respuesta", ancla="ultima-respuesta")
    segundo_plano.add_task(tareas.responder_pregunta, codigo, pregunta)
    return RedirectResponse(f"/licitacion/{codigo}#preguntas", status_code=303)


def _leer_en_segundo_plano(codigo: str, ruta: Path, descripcion: str) -> None:
    """Como BackgroundTasks solo existe en un POST, aquí se usa un hilo (el panel es de una sola persona)."""
    descargas.dejar_de_esperar(codigo)
    tareas.iniciar(codigo, descripcion, "Leyendo las bases")
    threading.Thread(target=tareas.leer_bases, args=(codigo, str(ruta)), daemon=True).start()


@router.get("/licitacion/{codigo}/ficha-mp", include_in_schema=False)
def abrir_ficha_mp(codigo: str):
    """Abre la ficha en Mercado Público y empieza a esperar las bases en la carpeta de descargas (opción A)."""
    with db.sesion() as s:
        licitacion = s.get(Licitacion, codigo)
    if licitacion is None:
        raise HTTPException(status_code=404, detail="Licitación no encontrada")
    descargas.esperar(codigo)
    descargas.vigilar(codigo, lambda c: _leer_si_esta_libre(codigo, c))
    return RedirectResponse(licitacion.url_ficha or mercadopublico.url_ficha(codigo), status_code=303)


def _leer_si_esta_libre(codigo: str, candidato) -> None:
    """Lo llama el hilo que vigila Descargas al encontrar las bases."""
    if not tareas.en_curso(codigo):
        _leer_en_segundo_plano(codigo, candidato.ruta, f"Encontré «{candidato.nombre}» en Descargas")


@router.post("/licitacion/{codigo}/bases-descargadas", include_in_schema=False)
def leer_bases_descargadas(codigo: str, nombre: str = Form(...)):
    """La persona eligió cuál de los PDF descargados son las bases."""
    if tareas.en_curso(codigo):
        raise HTTPException(status_code=409, detail="Ya se están procesando las bases de esta licitación")
    desde = descargas.esperando_desde(codigo)
    # Solo se aceptan archivos de la lista de candidatos, nunca una ruta enviada por el formulario
    elegido = next((c for c in descargas.candidatos(codigo, desde) if c.nombre == nombre), None) if desde else None
    if elegido is None:
        raise HTTPException(status_code=404, detail="Ese archivo ya no está en la carpeta de descargas")
    _leer_en_segundo_plano(codigo, elegido.ruta, f"Leyendo «{elegido.nombre}»")
    return RedirectResponse(f"/licitacion/{codigo}", status_code=303)


@router.post("/licitacion/{codigo}/dejar-de-buscar", include_in_schema=False)
def dejar_de_buscar(codigo: str):
    descargas.dejar_de_esperar(codigo)
    return RedirectResponse(f"/licitacion/{codigo}", status_code=303)


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
    descargas.dejar_de_esperar(codigo)
    tareas.iniciar(codigo, "En cola para leer las bases", "Leyendo las bases")
    segundo_plano.add_task(tareas.leer_bases, codigo, temporal.name)
    return RedirectResponse(f"/licitacion/{codigo}", status_code=303)


@router.post("/licitacion/{codigo}/conveniencia", include_in_schema=False)
def recalcular_conveniencia(codigo: str, segundo_plano: BackgroundTasks):
    if not tareas.en_curso(codigo):
        tareas.iniciar(codigo, "El modelo local evalúa la ficha y los datos verificados de las bases "
                               "(unos 10 a 30 segundos)", "Calculando la conveniencia")
        segundo_plano.add_task(tareas.calcular_conveniencia, codigo)
    return RedirectResponse(f"/licitacion/{codigo}", status_code=303)
