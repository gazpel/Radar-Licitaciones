"""Pruebas del resumen del día, la ficha para el modelo de conveniencia y el panel web."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app import db
from app.conveniencia import _ficha
from app.db import Ingesta, Licitacion
from app.resumen import resumen_del_dia, resumen_texto

AHORA = datetime(2026, 11, 14, 10, 0)


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
