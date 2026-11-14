"""Opción A de la carga de bases: tomar el PDF desde la carpeta de descargas del navegador.

PROVISORIO: BUSCAR UNA MEJOR SOLUCIÓN. La persona igual tiene que abrir la ficha y descargar el
archivo, porque Mercado Público protege los adjuntos con reCAPTCHA y no se debe saltar. Esto solo
le ahorra subir el archivo a mano. Una solución de fondo sería un acceso autorizado por ChileCompra
a los adjuntos (opción C, a conversar con ellos).

Cómo funciona:
1. El panel abre la ficha con /licitacion/<código>/ficha-mp y anota la hora: desde ahí "espera"
   las bases de esa licitación (máximo ESPERA_MAXIMA).
2. Mientras espera, revisa la carpeta de descargas y busca PDF nuevos (o PDF dentro de un ZIP).
3. Si un solo PDF menciona el código de la licitación y parece ser las bases, se lee solo.
   Si hay dudas (varios archivos, anexos, sin código), el panel los muestra y la persona elige.
"""
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pypdf import PdfReader

from app.config import settings
from app.texto import normalizar

ESPERA_MAXIMA = timedelta(minutes=30)
TAMANO_MAXIMO = 20 * 1024 * 1024  # el mismo límite que la carga manual
CARPETA_ZIP = Path("data/descargas")  # donde se extraen los PDF que vienen dentro de un ZIP
PAGINAS_A_REVISAR = 3  # para ver si menciona el código y si son las bases basta con el comienzo
# Frases que indican que el PDF son las bases (sin tildes ni mayúsculas). Muchas bases son la resolución
# que las aprueba: "apruébense las bases de licitación". Los anexos también pueden nombrarlas; por eso,
# si más de un PDF calza, se le pregunta a la persona.
FRASES_DE_BASES = ("bases administrativas", "bases de licitacion", "bases tecnicas", "bases generales",
                   "bases especiales", "aprueba bases", "apruebense las bases", "apruebanse las bases")


@dataclass
class Candidato:
    ruta: Path
    nombre: str  # como se muestra: "archivo.pdf" o "comprimido.zip › archivo.pdf"
    fecha: datetime
    tamano: int
    menciona_codigo: bool
    parece_bases: bool


_esperando: dict[str, datetime] = {}  # código -> desde cuándo se esperan sus bases (en memoria)


def esperar(codigo: str, ahora: datetime | None = None) -> None:
    _esperando[codigo] = ahora or datetime.now()


def dejar_de_esperar(codigo: str) -> None:
    _esperando.pop(codigo, None)


def esperando_desde(codigo: str, ahora: datetime | None = None) -> datetime | None:
    desde = _esperando.get(codigo)
    if desde is not None and (ahora or datetime.now()) - desde > ESPERA_MAXIMA:
        dejar_de_esperar(codigo)
        return None
    return desde


def carpeta() -> Path:
    return Path(settings.carpeta_descargas) if settings.carpeta_descargas else Path.home() / "Downloads"


def _primeras_paginas(ruta: Path) -> str:
    lector = PdfReader(str(ruta))
    return "\n".join((p.extract_text() or "") for p in lector.pages[:PAGINAS_A_REVISAR])


def _extraer_zip(ruta: Path) -> list[tuple[Path, str]]:
    """Copia los PDF del ZIP a data/descargas/<nombre del zip>/ (solo el nombre, sin carpetas internas)."""
    destino = CARPETA_ZIP / ruta.stem
    salida = []
    with zipfile.ZipFile(ruta) as comprimido:
        for miembro in comprimido.infolist():
            nombre = Path(miembro.filename).name  # descarta rutas como ../../ (ataque "zip slip")
            if not nombre.lower().endswith(".pdf") or miembro.file_size > TAMANO_MAXIMO:
                continue
            destino.mkdir(parents=True, exist_ok=True)
            archivo = destino / nombre
            if not archivo.exists() or archivo.stat().st_size != miembro.file_size:  # el panel revisa seguido
                archivo.write_bytes(comprimido.read(miembro))
            salida.append((archivo, f"{ruta.name} › {nombre}"))
    return salida


def candidatos(codigo: str, desde: datetime, en: Path | None = None, leer=_primeras_paginas) -> list[Candidato]:
    """PDF descargados desde `desde`, ordenados: primero los que mencionan el código y parecen bases."""
    en = en or carpeta()
    if not en.is_dir():
        return []
    encontrados: list[tuple[Path, str, datetime]] = []
    for archivo in en.iterdir():
        sufijo = archivo.suffix.lower()
        if not archivo.is_file() or sufijo not in (".pdf", ".zip"):
            continue  # los .crdownload / .part son descargas que aún no terminan
        fecha = datetime.fromtimestamp(archivo.stat().st_mtime)
        if fecha < desde:
            continue
        if sufijo == ".zip":
            try:
                encontrados += [(r, n, fecha) for r, n in _extraer_zip(archivo)]
            except zipfile.BadZipFile:
                continue
        else:
            encontrados.append((archivo, archivo.name, fecha))

    resultado = []
    for ruta, nombre, fecha in encontrados:
        tamano = ruta.stat().st_size
        if tamano == 0 or tamano > TAMANO_MAXIMO:
            continue
        try:
            texto = leer(ruta)
        except Exception:  # PDF dañado o protegido: no es candidato
            continue
        resultado.append(Candidato(
            ruta=ruta, nombre=nombre, fecha=fecha, tamano=tamano,
            menciona_codigo=codigo.upper() in texto.upper().replace(" ", ""),
            parece_bases="bases" in normalizar(nombre) or any(f in normalizar(texto) for f in FRASES_DE_BASES),
        ))
    resultado.sort(key=lambda c: (not c.menciona_codigo, not c.parece_bases, -c.fecha.timestamp()))
    return resultado


def eleccion_automatica(cands: list[Candidato]) -> Candidato | None:
    """Solo elige si no hay dudas: un único PDF que menciona el código y parece ser las bases."""
    seguros = [c for c in cands if c.menciona_codigo and c.parece_bases]
    return seguros[0] if len(seguros) == 1 else None
