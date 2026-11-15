"""Pruebas de las opciones provisorias para obtener las bases: A (carpeta de descargas) y B (puntaje con la ficha)."""
import os
import zipfile
from datetime import datetime, timedelta

import pytest

from app import descargas
from app.conveniencia import EvaluacionConveniencia, puntuar_sin_puntaje
from app.db import Extraccion, Licitacion
from app.resumen import resumen_del_dia

AHORA = datetime(2026, 11, 14, 10, 0)
CODIGO = "2408-242-L126"


def leer_falso(ruta):
    """En vez de leer un PDF real, el "texto" es el contenido del archivo."""
    return ruta.read_bytes().decode()


def archivo(carpeta, nombre, contenido, minutos=0):
    ruta = carpeta / nombre
    ruta.write_bytes(contenido.encode() if isinstance(contenido, str) else contenido)
    fecha = (AHORA + timedelta(minutes=minutos)).timestamp()
    os.utime(ruta, (fecha, fecha))
    return ruta


@pytest.fixture(autouse=True)
def carpeta_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(descargas, "CARPETA_ZIP", tmp_path / "zip")


# ---------- Opción A: carpeta de descargas ----------

def test_solo_considera_pdf_descargados_despues_de_abrir_la_ficha(tmp_path):
    archivo(tmp_path, "viejo.pdf", f"Bases administrativas {CODIGO}", minutos=-10)
    archivo(tmp_path, "nuevo.pdf", f"Bases administrativas {CODIGO}", minutos=2)
    archivo(tmp_path, "a_medias.pdf.crdownload", "incompleto", minutos=3)
    cands = descargas.candidatos(CODIGO, AHORA, en=tmp_path, leer=leer_falso)
    assert [c.nombre for c in cands] == ["nuevo.pdf"]


def test_elige_solo_si_no_hay_dudas(tmp_path):
    archivo(tmp_path, "Bases.pdf", f"BASES ADMINISTRATIVAS licitación {CODIGO}", minutos=1)
    archivo(tmp_path, "Anexo 1.pdf", f"Formulario de oferta {CODIGO}", minutos=1)
    archivo(tmp_path, "otra cosa.pdf", "Boleta de la luz", minutos=1)
    cands = descargas.candidatos(CODIGO, AHORA, en=tmp_path, leer=leer_falso)
    assert cands[0].nombre == "Bases.pdf"  # primero el que menciona el código y parece bases
    assert descargas.eleccion_automatica(cands).nombre == "Bases.pdf"


def test_con_dos_posibles_bases_pregunta(tmp_path):
    archivo(tmp_path, "Bases.pdf", f"Bases administrativas {CODIGO}", minutos=1)
    archivo(tmp_path, "Bases técnicas.pdf", f"Bases técnicas {CODIGO}", minutos=1)
    cands = descargas.candidatos(CODIGO, AHORA, en=tmp_path, leer=leer_falso)
    assert len(cands) == 2 and descargas.eleccion_automatica(cands) is None


def test_pdf_de_otra_licitacion_no_se_lee_solo(tmp_path):
    archivo(tmp_path, "Bases.pdf", "Bases administrativas 9999-1-LE26", minutos=1)
    cands = descargas.candidatos(CODIGO, AHORA, en=tmp_path, leer=leer_falso)
    assert not cands[0].menciona_codigo and descargas.eleccion_automatica(cands) is None


def test_pdf_dentro_de_un_zip_sin_salirse_de_la_carpeta(tmp_path):
    ruta_zip = tmp_path / "adjuntos.zip"
    with zipfile.ZipFile(ruta_zip, "w") as z:
        z.writestr("carpeta/Bases.pdf", f"Bases administrativas {CODIGO}")
        z.writestr("../../malicioso.pdf", "intenta escribir fuera")
        z.writestr("leeme.txt", "no es PDF")
    fecha = (AHORA + timedelta(minutes=1)).timestamp()
    os.utime(ruta_zip, (fecha, fecha))
    cands = descargas.candidatos(CODIGO, AHORA, en=tmp_path, leer=leer_falso)
    assert sorted(c.nombre for c in cands) == ["adjuntos.zip › Bases.pdf", "adjuntos.zip › malicioso.pdf"]
    assert all(c.ruta.parent == descargas.CARPETA_ZIP / "adjuntos" for c in cands)
    assert not (tmp_path.parent / "malicioso.pdf").exists()


def test_la_espera_vence(monkeypatch):
    descargas.esperar("X", ahora=AHORA)
    assert descargas.esperando_desde("X", ahora=AHORA + timedelta(minutes=5)) == AHORA
    assert descargas.esperando_desde("X", ahora=AHORA + timedelta(hours=1)) is None


# ---------- Opción B: puntaje con la ficha y bases solo si conviene ----------

def evaluador_falso(licitacion, empresa, hallazgos, ahora):
    puntaje = 4 if "colchones" in licitacion.nombre.lower() else 2
    return EvaluacionConveniencia(puntaje=puntaje, a_favor=["del rubro"], en_contra=[], resumen="prueba")


def lic(codigo, nombre, dias=10, puntaje=None):
    return Licitacion(codigo=codigo, nombre=nombre, fecha_cierre=AHORA + timedelta(days=dias), puntaje=puntaje,
                      primera_vez=AHORA, motivos=["nombre contiene: colchon"])


def test_puntua_solo_abiertas_sin_puntaje_y_sin_bases(sesion):
    sesion.add_all([
        lic("1-1-LE26", "Adquisición de colchones"),
        lic("2-2-LE26", "Almohadas para hospital"),
        lic("3-3-LE26", "Colchones ya evaluados", puntaje=5),
        lic("4-4-LE26", "Colchones cerrada", dias=-1),
        lic("5-5-LE26", "Colchones con bases leídas"),
        Extraccion(licitacion_codigo="5-5-LE26", archivo="x.pdf", paginas=1, modelo="falso", segundos=1),
    ])
    sesion.commit()
    puntuadas, errores = puntuar_sin_puntaje(sesion, ahora=AHORA, evaluador=evaluador_falso)
    assert sorted(l.codigo for l in puntuadas) == ["1-1-LE26", "2-2-LE26"] and errores == []
    assert sesion.get(Licitacion, "1-1-LE26").conveniencia["con_bases"] is False


def test_un_error_no_detiene_a_las_demas(sesion):
    sesion.add_all([lic("1-1-LE26", "Colchones"), lic("2-2-LE26", "Colchones")])
    sesion.commit()

    def falla_con_la_primera(licitacion, *args):
        if licitacion.codigo == "1-1-LE26":
            raise ConnectionError("Ollama apagado")
        return evaluador_falso(licitacion, *args)

    puntuadas, errores = puntuar_sin_puntaje(sesion, ahora=AHORA, evaluador=falla_con_la_primera)
    assert [l.codigo for l in puntuadas] == ["2-2-LE26"] and "Ollama apagado" in errores[0]


def test_resumen_pide_bases_solo_con_puntaje_alto(sesion):
    sesion.add_all([lic("1-1-LE26", "A", puntaje=4), lic("2-2-LE26", "B", puntaje=2), lic("3-3-LE26", "C"),
                    lic("4-4-LE26", "D", puntaje=5),
                    Extraccion(licitacion_codigo="4-4-LE26", archivo="x.pdf", paginas=1, modelo="falso", segundos=1)])
    sesion.commit()
    r = resumen_del_dia(sesion, ahora=AHORA)
    assert [l.codigo for l in r.por_cargar] == ["1-1-LE26"]
    assert r.con_bases == {"4-4-LE26"}


def test_revision_desde_el_panel_termina_con_su_resumen(sesion, monkeypatch):
    """La revisión del botón del panel: ingesta + puntaje con la ficha, con API y modelo falsos."""
    from functools import partial

    from app import conveniencia, db, ingesta, tareas
    from tests.conftest import APIFalsa, detalle

    monkeypatch.setattr(db, "motor", sesion.get_bind())
    api = APIFalsa([detalle("1-1-LE26", "Adquisición de colchones")])
    monkeypatch.setattr(ingesta, "ejecutar", partial(ingesta.ejecutar, api=api))
    monkeypatch.setattr(conveniencia, "puntuar_sin_puntaje",
                        partial(conveniencia.puntuar_sin_puntaje, evaluador=evaluador_falso))
    tareas.iniciar(tareas.REVISION, "Empezando")
    tareas.revisar_mercado_publico()
    estado = tareas.estado(tareas.REVISION)
    tareas._estados.pop(tareas.REVISION)
    assert estado.terminada and not estado.error, estado.error
    assert "1 activas revisadas, 1 del rubro, 1 nuevas; 1 con puntaje nuevo" in estado.descripcion


def test_el_hilo_detecta_las_bases_sin_que_la_pagina_este_abierta(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(descargas.settings, "carpeta_descargas", str(tmp_path))
    monkeypatch.setattr(descargas, "_primeras_paginas", leer_falso)
    encontradas = []
    listo = threading.Event()
    desde = descargas.esperar(CODIGO)
    hilo = descargas.vigilar(CODIGO, lambda c: (encontradas.append(c.nombre), listo.set()), cada=0.05)
    ruta = tmp_path / "0A1B2C.pdf"  # llega la descarga, con un nombre cualquiera
    ruta.write_text(f"Apruébense las bases de licitación {CODIGO}", encoding="utf-8")
    fecha = (desde + timedelta(seconds=5)).timestamp()
    os.utime(ruta, (fecha, fecha))
    assert listo.wait(3) and encontradas == ["0A1B2C.pdf"]
    hilo.join(1)
    assert descargas.esperando_desde(CODIGO) is None  # dejó de esperar: no se lee dos veces
    assert not descargas.reclamar(CODIGO)


def test_volver_a_abrir_la_ficha_detiene_el_hilo_anterior(tmp_path, monkeypatch):
    monkeypatch.setattr(descargas.settings, "carpeta_descargas", str(tmp_path))
    descargas.esperar(CODIGO, ahora=datetime.now())
    viejo = descargas.vigilar(CODIGO, lambda c: None, cada=0.05)
    descargas.esperar(CODIGO, ahora=datetime.now() + timedelta(seconds=1))  # otra espera
    viejo.join(1)
    assert not viejo.is_alive()
    descargas.dejar_de_esperar(CODIGO)
