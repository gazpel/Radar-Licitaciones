"""Pruebas del filtro por reglas (app/filtros.py)."""
from app.filtros import etapa_detalle, etapa_nombre
from tests.conftest import detalle


def test_nombre_con_palabra_clave_pasa_aunque_tenga_tildes_y_mayusculas(empresa):
    ev = etapa_nombre({"Nombre": "ADQUISICIÓN DE COLCHONES 1 PLAZA"}, empresa)
    assert ev.pasa
    assert "colchon" in ev.motivos[0]


def test_nombre_sin_palabra_clave_no_pasa(empresa):
    assert not etapa_nombre({"Nombre": "Materiales eléctricos"}, empresa).pasa


def test_palabra_excluida_gana_sobre_palabra_clave(empresa):
    ev = etapa_nombre({"Nombre": "Servicio de lavado de colchones"}, empresa)
    assert not ev.pasa
    assert "lavado" in ev.rechazos[0]


def test_detalle_que_cumple_todo_pasa_con_sus_motivos(empresa):
    ev = etapa_detalle(detalle("1-1-LE26", "Colchones"), empresa)
    assert ev.pasa
    assert len(ev.motivos) == 3  # rubro, región y monto


def test_rubro_por_nombre_del_producto_aunque_el_codigo_sea_otro(empresa):
    d = detalle("1-1-LE26", "Colchones", codigo_producto=42191807, producto="Colchones clínicos")
    ev = etapa_detalle(d, empresa)
    assert ev.pasa
    assert "producto pedido" in ev.motivos[0]


def test_producto_de_otro_rubro_no_pasa(empresa):
    d = detalle("1-1-LE26", "Colchones", codigo_producto=91111502, producto="Servicios de lavandería")
    assert not etapa_detalle(d, empresa).pasa


def test_region_con_apostrofe_distinto(empresa):
    """La API escribe O´Higgins (acento agudo) y el perfil O'Higgins (apóstrofo)."""
    d = detalle("1-1-LE26", "Colchones", region="Región del Libertador General Bernardo O´Higgins")
    assert etapa_detalle(d, empresa).pasa


def test_region_no_atendida_no_pasa(empresa):
    ev = etapa_detalle(detalle("1-1-LE26", "Colchones", region="Región de Arica y Parinacota"), empresa)
    assert not ev.pasa
    assert "región no atendida" in ev.rechazos[0]


def test_monto_fuera_de_rango_no_pasa(empresa):
    assert not etapa_detalle(detalle("1-1-LE26", "Colchones", monto=100_000), empresa).pasa
    assert not etapa_detalle(detalle("1-1-LE26", "Colchones", monto=90_000_000), empresa).pasa


def test_monto_no_publicado_no_descarta(empresa):
    ev = etapa_detalle(detalle("1-1-LE26", "Colchones", monto=None), empresa)
    assert ev.pasa
    assert any("no publicado" in m for m in ev.motivos)
