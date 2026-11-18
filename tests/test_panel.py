"""Pruebas del resumen del día, la ficha para el modelo de conveniencia y el panel web."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app import db
from app.conveniencia import _ficha
from app.db import Ingesta, Licitacion
from app.resumen import resumen_del_dia, resumen_texto

AHORA = datetime.now().replace(second=0, microsecond=0)  # relativo a hoy: el panel compara con la hora real


def licitacion(codigo, dias_cierre, puntaje=None, horas_desde_ingreso=1, monto=1_000_000):
    return Licitacion(codigo=codigo, nombre=f"Colchones {codigo}", organismo="Municipalidad", region="Biobío",
                      monto=monto, fecha_cierre=AHORA + timedelta(days=dias_cierre), puntaje=puntaje,
                      primera_vez=AHORA - timedelta(hours=horas_desde_ingreso), motivos=["nombre contiene: colchon"])


@pytest.fixture
def con_datos(sesion):
    sesion.add(Ingesta(inicio=AHORA, fin=AHORA, activas=100))
    sesion.add(licitacion("1-1-LE26", dias_cierre=10, puntaje=3))
    sesion.add(licitacion("2-2-LE26", dias_cierre=2, puntaje=5, horas_desde_ingreso=72))
    sesion.add(licitacion("3-3-LE26", dias_cierre=20))
    sesion.add(licitacion("4-4-LE26", dias_cierre=-1, puntaje=5))  # ya cerró
    sesion.commit()
    return sesion


def test_resumen_ordena_por_puntaje_y_deja_sin_puntaje_al_final(con_datos):
    r = resumen_del_dia(con_datos, ahora=AHORA)
    assert [l.codigo for l in r.abiertas] == ["2-2-LE26", "1-1-LE26", "3-3-LE26"]


def test_resumen_separa_nuevas_y_urgentes(con_datos):
    r = resumen_del_dia(con_datos, ahora=AHORA)
    assert {l.codigo for l in r.nuevas} == {"1-1-LE26", "3-3-LE26"}  # la 2-2 entró hace 3 días
    assert [l.codigo for l in r.cierran_pronto] == ["2-2-LE26"]


def test_resumen_en_texto(con_datos):
    texto = resumen_texto(resumen_del_dia(con_datos, ahora=AHORA))
    assert "2 nuevas" in texto and "CIERRAN PRONTO" in texto and "5/5" in texto


def test_ficha_para_el_modelo_entrega_los_dias_calculados(empresa):
    texto = _ficha(licitacion("1-1-LE26", dias_cierre=7, monto=None), empresa, AHORA)
    assert "quedan 7 días" in texto
    assert "Monto estimado: no publicado" in texto


@pytest.fixture
def cliente(tmp_path, monkeypatch, con_datos):
    """Panel apuntando a la base temporal de la prueba."""
    motor = con_datos.get_bind()
    monkeypatch.setattr(db, "motor", motor)
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_paginas_del_panel(cliente):
    inicio = cliente.get("/")
    assert inicio.status_code == 200 and "Colchones 2-2-LE26" in inicio.text
    assert cliente.get("/licitacion/1-1-LE26").status_code == 200
    assert cliente.get("/licitacion/NO-EXISTE").status_code == 404


def test_subir_algo_que_no_es_pdf_se_rechaza(cliente):
    r = cliente.post("/licitacion/1-1-LE26/bases", files={"archivo": ("bases.pdf", b"MZ ejecutable", "application/pdf")})
    assert r.status_code == 415


def test_ficha_avisa_si_la_licitacion_ya_cerro(empresa):
    texto = _ficha(licitacion("1-1-LE26", dias_cierre=-3), empresa, AHORA)
    assert "YA CERRÓ" in texto


def test_abrir_ficha_desde_el_panel_empieza_a_buscar_en_descargas(cliente, tmp_path, monkeypatch):
    from app import descargas
    monkeypatch.setattr(descargas.settings, "carpeta_descargas", str(tmp_path / "descargas_vacia"))
    r = cliente.get("/licitacion/1-1-LE26/ficha-mp", follow_redirects=False)
    assert r.status_code == 303 and "mercadopublico.cl" in r.headers["location"]
    assert "Esperando las bases en Descargas" in cliente.get("/licitacion/1-1-LE26").text
    descargas.dejar_de_esperar("1-1-LE26")


def test_solo_se_leen_archivos_de_la_lista_de_candidatos(cliente):
    r = cliente.post("/licitacion/1-1-LE26/bases-descargadas", data={"nombre": "../../.env"})
    assert r.status_code == 404


def test_preguntar_sin_bases_leidas_avisa(cliente):
    r = cliente.post("/licitacion/1-1-LE26/preguntar", data={"pregunta": "¿Qué pasa si me atraso?"})
    assert r.status_code == 409


def test_pregunta_vacia_o_demasiado_larga_se_rechaza(cliente):
    assert cliente.post("/licitacion/1-1-LE26/preguntar", data={"pregunta": "   ¿?  "}).status_code == 422
    assert cliente.post("/licitacion/1-1-LE26/preguntar", data={"pregunta": "a" * 400}).status_code == 422


def test_titulos_en_mayusculas_se_muestran_legibles():
    from app.panel import _titulo
    assert _titulo("ADQUISICIÓN DE COLCHONES 1 PLAZA") == "Adquisición de Colchones 1 PLAZA" or \
        _titulo("ADQUISICIÓN DE COLCHONES 1 PLAZA") == "Adquisición de Colchones 1 Plaza"
    assert _titulo("I MUNICIPALIDAD DE CHIMBARONGO") == "I Municipalidad de Chimbarongo"
    assert _titulo("LICITACIÓN “ADQUISICIÓN DE COLCHONES”") == "Licitación “Adquisición de Colchones”"
    assert _titulo("Compra de colchones para el CESFAM") == "Compra de colchones para el CESFAM"  # ya legible


def test_buscar_por_codigo_lleva_a_la_licitacion(cliente):
    r = cliente.get("/?q=1-1-le26", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/licitacion/1-1-LE26"


def test_buscar_por_nombre_y_ver_las_cerradas(cliente):
    assert "Colchones 3-3-LE26" in cliente.get("/?q=colchones").text
    inicio = cliente.get("/").text
    assert "Cerradas o anteriores (1)" in inicio and "Colchones 4-4-LE26" in inicio


def test_boton_revisar_lanza_una_sola_revision(cliente, monkeypatch):
    from app import tareas
    llamadas = []
    monkeypatch.setattr(tareas, "revisar_mercado_publico", lambda: llamadas.append(1))  # no termina nunca
    cliente.post("/revisar")
    cliente.post("/revisar")  # la segunda vez ya hay una en curso: no se lanza otra
    assert tareas.en_curso(tareas.REVISION)
    assert "Revisando…" in cliente.get("/").text
    tareas._estados.pop(tareas.REVISION)
    assert len(llamadas) == 1


def test_estado_de_una_tarea_para_que_la_pagina_sepa_cuando_recargar(cliente):
    from app import tareas
    assert cliente.get("/tarea/1-1-LE26/estado").json() == {"en_curso": False}
    tareas.iniciar("1-1-LE26", "Pregunta: «x»", "Buscando respuesta", ancla="ultima-respuesta")
    pagina = cliente.get("/licitacion/1-1-LE26").text
    assert 'data-estado="/tarea/1-1-LE26/estado"' in pagina and "#ultima-respuesta" in pagina
    assert cliente.get("/tarea/1-1-LE26/estado").json()["en_curso"] is True
    tareas._actualizar("1-1-LE26", terminada=True)
    assert cliente.get("/tarea/1-1-LE26/estado").json()["en_curso"] is False
    tareas._estados.pop("1-1-LE26")
