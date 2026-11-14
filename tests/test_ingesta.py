"""Pruebas de la ingesta (app/ingesta.py) con una API falsa: sin internet ni consultas reales."""
from sqlmodel import select

from functools import partial

from app.db import Ingesta, Licitacion
from app import ingesta
from tests.conftest import APIFalsa, detalle

# Sin búsqueda semántica (no depende de Ollama); las pruebas de la etapa 1b la reemplazan por una falsa
ejecutar = partial(ingesta.ejecutar, similitud=None)


def api_de_prueba():
    return APIFalsa([
        detalle("1-1-LE26", "Adquisición de colchones"),
        detalle("2-2-LE26", "Almohadas para hospital", codigo_producto=52121505, producto="Almohadas"),
        detalle("3-3-LE26", "Colchones para Arica", region="Región de Arica y Parinacota"),
        detalle("4-4-LE26", "Materiales de construcción"),
    ])


def test_guarda_solo_las_relevantes(sesion):
    r = ejecutar(sesion, api=api_de_prueba())
    assert [l.codigo for l in r.nuevas] == ["1-1-LE26", "2-2-LE26"]
    assert [d.codigo for d in r.descartadas] == ["3-3-LE26"]
    assert r.ingesta.activas == 4
    assert r.ingesta.candidatas == 3


def test_solo_pide_detalle_de_las_candidatas(sesion):
    api = api_de_prueba()
    ejecutar(sesion, api=api)
    assert api.consultas_detalle == 3  # la de "materiales" se descarta sin consultar su detalle


def test_ejecutar_dos_veces_no_duplica(sesion):
    api = api_de_prueba()
    primera = ejecutar(sesion, api=api)
    segunda = ejecutar(sesion, api=api)

    assert primera.ingesta.nuevas == 2
    assert segunda.ingesta.nuevas == 0
    assert len(segunda.actualizadas) == 2
    assert len(sesion.exec(select(Licitacion)).all()) == 2
    assert len(sesion.exec(select(Ingesta)).all()) == 2


def test_guarda_los_motivos_y_la_ingesta_de_origen(sesion):
    r = ejecutar(sesion, api=api_de_prueba())
    guardada = sesion.get(Licitacion, "1-1-LE26")
    assert guardada.ingesta_id == r.ingesta.id
    assert any("UNSPSC" in m for m in guardada.motivos)
    assert guardada.region == "Región Metropolitana de Santiago"  # sin el espacio final de la API


def test_detalle_que_no_llega_se_registra_como_error(sesion):
    """Una licitación aparece en el listado de activas, pero la API no entrega su detalle."""
    api = APIFalsa([])
    api.licitaciones_activas = lambda: [{"CodigoExterno": "9-9-LE26", "Nombre": "Colchones"}]
    r = ejecutar(sesion, api=api)
    assert r.ingesta.errores == 1
    assert r.nuevas == []


def similitud_falsa(perfil, textos):
    """Simula embeddings: los textos con "cama" se parecen al rubro."""
    return [0.9 if "cama" in t.lower() else 0.1 for t in textos]


def test_etapa_1b_rescata_nombres_parecidos_sin_palabras_clave(sesion):
    api = APIFalsa([detalle("5-5-LE26", "Equipamiento de camas para albergue", producto="Colchones de espuma")])
    r = ingesta.ejecutar(sesion, api=api, similitud=similitud_falsa)
    assert [l.codigo for l in r.nuevas] == ["5-5-LE26"]
    assert "nombre parecido al rubro" in r.nuevas[0].motivos[0]
    assert r.nuevas[0].similitud == 0.9


def test_palabra_excluida_no_se_rescata_por_similitud(sesion):
    api = APIFalsa([detalle("6-6-LE26", "Lavado de ropa de cama")])
    r = ingesta.ejecutar(sesion, api=api, similitud=similitud_falsa)
    assert r.ingesta.candidatas == 0


def test_si_los_embeddings_fallan_la_ingesta_sigue(sesion):
    def similitud_rota(perfil, textos):
        raise ConnectionError("Ollama apagado")

    r = ingesta.ejecutar(sesion, api=api_de_prueba(), similitud=similitud_rota)
    assert len(r.nuevas) == 2
    assert any("Búsqueda semántica no disponible" in e for e in r.errores)
