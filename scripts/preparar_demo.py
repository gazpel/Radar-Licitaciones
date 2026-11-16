"""Revisa que todo esté listo para la demo y deja los modelos cargados en la GPU.

Uso (desde radar-licitaciones, con el entorno virtual activo), unos minutos antes de presentar:
    python -m scripts.preparar_demo                 -> revisa todo, carga los modelos y respalda la base
    python -m scripts.preparar_demo --restaurar     -> vuelve la base de datos al respaldo (si algo se rompió)

Qué revisa: Ollama encendido, modelos instalados, base de datos con la licitación de la demo
(bases leídas, fragmentos con embeddings, conveniencia) y el panel en http://localhost:8000.
"""
import shutil
import sys
import time
from pathlib import Path

import httpx
from sqlmodel import select

from app import db
from app.config import settings
from app.db import Extraccion, Fragmento, Licitacion

LICITACION_DEMO = "3730-117-L126"  # abierta, con bases leídas (18 páginas)
BASE = Path(settings.db_url.removeprefix("sqlite:///"))
RESPALDO = BASE.with_name("radar_respaldo_demo.db")
PANEL = "http://localhost:8000"

problemas: list[str] = []


def ok(texto: str) -> None:
    print(f"  [OK]  {texto}")


def mal(texto: str, como_arreglar: str) -> None:
    print(f"  [!!]  {texto}\n        -> {como_arreglar}")
    problemas.append(texto)


def revisar_ollama() -> bool:
    print("\n1. Ollama y modelos")
    try:
        modelos = {m["name"] for m in httpx.get(f"{settings.ollama_url}/api/tags", timeout=5).json()["models"]}
    except httpx.HTTPError:
        mal("Ollama no responde", "Abre la aplicación Ollama (menú Inicio) y vuelve a correr este script")
        return False
    ok("Ollama encendido")
    necesarios = {settings.llm_model, settings.embed_model, settings.llm_model_extraccion or settings.llm_model}
    for nombre in sorted(necesarios):
        if nombre in modelos or f"{nombre}:latest" in modelos:
            ok(f"modelo {nombre} instalado")
        else:
            mal(f"falta el modelo {nombre}", f"ollama pull {nombre}")
    return True


def cargar_modelos() -> None:
    """Una llamada mínima a cada modelo con keep_alive: quedan en la GPU y la demo no paga la carga."""
    print("\n2. Cargando los modelos en la GPU (para que la primera respuesta no tarde de más)")
    segundos = settings.llm_keep_alive_minutos * 60
    for nombre, url, cuerpo in [
        (settings.llm_model, "/api/generate", {"model": settings.llm_model, "prompt": "", "keep_alive": segundos}),
        (settings.embed_model, "/api/embed", {"model": settings.embed_model, "input": "hola", "keep_alive": segundos}),
    ]:
        inicio = time.time()
        try:
            httpx.post(f"{settings.ollama_url}{url}", json=cuerpo, timeout=120).raise_for_status()
            ok(f"{nombre} cargado en {time.time() - inicio:.0f} s (queda {settings.llm_keep_alive_minutos} min)")
        except httpx.HTTPError as error:
            mal(f"no se pudo cargar {nombre}: {error}", "Revisa que Ollama esté encendido")


def revisar_datos() -> None:
    print(f"\n3. Datos de la demo ({LICITACION_DEMO})")
    if not BASE.exists():
        mal(f"no existe {BASE}", "Ejecuta python -m scripts.ingesta")
        return
    with db.sesion() as s:
        licitacion = s.get(Licitacion, LICITACION_DEMO)
        if licitacion is None:
            mal("la licitación de la demo no está en la base", "Cárgala desde el panel con sus bases")
            return
        ok(f"licitación: {licitacion.nombre[:60]}")
        extraccion = s.exec(select(Extraccion).where(Extraccion.licitacion_codigo == LICITACION_DEMO)
                            .order_by(Extraccion.id.desc())).first()
        if extraccion is None or extraccion.en_curso:
            mal("sus bases no están leídas (o quedó una lectura a medias)", "Súbelas de nuevo en el panel")
        else:
            ok(f"bases leídas con {extraccion.modelo} ({extraccion.paginas} páginas)")
            fragmentos = s.exec(select(Fragmento).where(Fragmento.extraccion_id == extraccion.id)).all()
            con_vector = sum(f.vector is not None for f in fragmentos)
            if fragmentos and con_vector == len(fragmentos):
                ok(f"{len(fragmentos)} fragmentos con embeddings listos para preguntas")
            else:
                mal(f"fragmentos: {len(fragmentos)}, con embeddings: {con_vector}",
                    "Haz una pregunta en el panel con Ollama encendido (se indexan solos)")
        if licitacion.conveniencia and licitacion.conveniencia.get("con_bases"):
            ok(f"conveniencia calculada con las bases: {licitacion.puntaje}/5")
        else:
            mal("falta la conveniencia con las bases", "Botón «Recalcular conveniencia» en el panel")


def revisar_panel() -> None:
    print("\n4. Panel web")
    try:
        httpx.get(PANEL, timeout=5).raise_for_status()
        ok(f"panel respondiendo en {PANEL}")
    except httpx.HTTPError:
        mal("el panel no responde", r"Doble clic en scripts\panel.bat (y deja esa ventana abierta)")


def main():
    if "--restaurar" in sys.argv:
        if not RESPALDO.exists():
            sys.exit(f"No hay respaldo en {RESPALDO}")
        shutil.copyfile(RESPALDO, BASE)
        print(f"Base restaurada desde {RESPALDO}. Reinicia el panel.")
        return

    print("Preparando la demo del Radar de Licitaciones")
    if revisar_ollama():
        cargar_modelos()
    revisar_datos()
    revisar_panel()
    if BASE.exists():
        shutil.copyfile(BASE, RESPALDO)
        print(f"\nRespaldo de la base en {RESPALDO} (para volver: --restaurar)")
    print("\n" + ("TODO LISTO para la demo." if not problemas else f"{len(problemas)} problema(s): revísalos arriba."))


if __name__ == "__main__":
    main()
