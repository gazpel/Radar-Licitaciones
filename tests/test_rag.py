"""Pruebas del RAG (app/rag.py) sin Ollama: embeddings y modelo falsos."""
import numpy as np
import pytest

from app import bases, rag
from app.db import Extraccion, Fragmento, Licitacion, Pregunta
from app.rag import (CitaVerificada, fragmentar, intercalar, nivel_respuesta, preguntar, ranking_bm25,
                     recuperar, responder)
from app.verificacion import Nivel

PAGINAS = [
    "Bases de licitación para la adquisición de colchones. Plazo para realizar consultas: 04/10/2026.",
    "Multas. El proveedor adjudicado deberá pagar multas por cada día hábil de atraso en la entrega.",
    "Pago. Se pagará dentro de los 30 días corridos siguientes a la recepción de la factura.",
]


def embeber_falso(textos):
    """Vector según temas: así "me castigan si llego tarde" queda cerca de "multas por atraso"."""
    temas = [("multa", "atraso", "tarde", "castig"), ("pago", "pagar", "factura", "demoran"), ("consulta", "pregunt")]
    vectores = []
    for t in textos:
        t = t.lower()
        v = np.array([sum(p in t for p in tema) for tema in temas] + [0.1], dtype=np.float32)
        vectores.append(v / np.linalg.norm(v))
    return np.array(vectores)


def fragmentos_de(paginas):
    vectores = embeber_falso([t.texto for t in fragmentar(paginas)])
    return [Fragmento(extraccion_id=1, licitacion_codigo="X", pagina=t.pagina, orden=t.orden, texto=t.texto,
                      vector=rag._a_bytes(v)) for t, v in zip(fragmentar(paginas), vectores)]


def test_fragmentar_conserva_pagina_y_no_corta_palabras():
    texto = " ".join(f"palabra{i}" for i in range(400))
    trozos = fragmentar([texto, "corta pero suficiente para un fragmento"], largo=200, solape=40)
    assert all(t.texto.split()[-1].startswith("palabra") for t in trozos if t.pagina == 1)
    assert all(len(t.texto) <= 200 for t in trozos)
    assert trozos[-1].pagina == 2
    # con solape, el comienzo de un fragmento repite el final del anterior
    assert trozos[1].texto.split()[0] in trozos[0].texto


def test_bm25_encuentra_las_palabras_de_la_pregunta():
    orden = ranking_bm25("¿Cuándo pagan la factura?", PAGINAS)
    assert orden[0] == 2


def test_intercalar_toma_lo_mejor_de_cada_ranking():
    assert intercalar([3, 1, 2], [0, 3, 1]) == [3, 0, 1, 2]


def test_hibrido_encuentra_preguntas_dichas_con_otras_palabras():
    fragmentos = fragmentos_de(PAGINAS)
    elegidos = recuperar("¿Me castigan si llego tarde?", fragmentos, k=1, embeber=embeber_falso)
    assert elegidos[0].pagina == 2


def test_sin_embeddings_funciona_solo_con_palabras():
    def falla(_):
        raise ConnectionError("Ollama apagado")
    fragmentos = fragmentos_de(PAGINAS)
    assert recuperar("multas por atraso", fragmentos, k=1, embeber=falla)[0].pagina == 2


def generar_falso(respuesta):
    return lambda sistema, usuario, esquema, modelo=None, think=None: respuesta


def test_respuesta_con_cita_textual():
    r = responder("¿Qué pasa si me atraso?", fragmentos_de(PAGINAS), PAGINAS, generar=generar_falso({
        "encontrado": True, "respuesta": "Te cobran multas por cada día hábil de atraso.",
        "citas": [{"pagina": 2, "cita": "deberá pagar multas por cada día hábil de atraso"}]}))
    assert r.nivel == Nivel.textual and r.citas[0].pagina == 2


def test_cita_inventada_queda_sin_respaldo():
    r = responder("¿Qué pasa si me atraso?", fragmentos_de(PAGINAS), PAGINAS, generar=generar_falso({
        "encontrado": True, "respuesta": "Te quitan la licitación.",
        "citas": [{"pagina": 2, "cita": "el contrato se termina de inmediato al primer atraso"}]}))
    assert r.nivel == Nivel.sin_respaldo


def test_numero_que_no_esta_en_la_cita_se_marca_para_revisar():
    citas = [CitaVerificada(3, "dentro de los 30 días corridos", Nivel.textual, "dentro de los 30 días corridos")]
    assert nivel_respuesta("Te pagan en 30 días.", citas) == Nivel.textual
    assert nivel_respuesta("Te pagan en 45 días.", citas) == Nivel.interpretado


def test_pregunta_fuera_de_las_bases():
    r = responder("¿Capital de Francia?", fragmentos_de(PAGINAS), PAGINAS, generar=generar_falso({
        "encontrado": False, "respuesta": "No lo encontré en las bases", "citas": []}))
    assert not r.encontrado and r.nivel == Nivel.sin_respaldo


@pytest.fixture
def con_bases(sesion, tmp_path, monkeypatch):
    sesion.add(Licitacion(codigo="1-1-LE26", nombre="Colchones"))
    sesion.add(Extraccion(licitacion_codigo="1-1-LE26", archivo="x.pdf", paginas=3, modelo="falso", segundos=1))
    sesion.commit()
    monkeypatch.setattr(rag, "leer_paginas", lambda ruta: PAGINAS)
    return sesion


def test_preguntar_indexa_una_vez_y_guarda_el_historial(con_bases):
    respuesta = generar_falso({"encontrado": True, "respuesta": "Dentro de 30 días corridos.",
                               "citas": [{"pagina": 3, "cita": "dentro de los 30 días corridos siguientes"}]})
    preguntar(con_bases, "1-1-LE26", "¿En cuánto me pagan?", modelo="falso", embeber=embeber_falso, generar=respuesta)
    preguntar(con_bases, "1-1-LE26", "¿Y la factura?", modelo="falso", embeber=embeber_falso, generar=respuesta)
    assert len(rag.historial(con_bases, "1-1-LE26")) == 2
    indexados = con_bases.exec(rag.select(Fragmento)).all()
    assert len(indexados) == 3  # se indexó una sola vez
    assert rag.historial(con_bases, "1-1-LE26")[0].nivel == "textual"


def test_pregunta_muy_corta_se_rechaza(con_bases):
    with pytest.raises(ValueError):
        preguntar(con_bases, "1-1-LE26", "¿?", embeber=embeber_falso, generar=generar_falso({}))
