"""Datos de prueba compartidos: una empresa, una base de datos temporal y una API falsa."""
import pytest
from sqlmodel import create_engine

from app import db
from app.db import Empresa


@pytest.fixture
def empresa():
    return Empresa(
        nombre="Colchonería de prueba",
        rubro="colchones",
        regiones=["Metropolitana", "O'Higgins"],
        palabras_clave=["colchon", "almohada"],
        palabras_excluidas=["lavado"],
        unspsc=["49121502"],
        monto_min=500_000,
        monto_max=60_000_000,
    )


@pytest.fixture
def sesion(tmp_path, empresa):
    """Base SQLite nueva en una carpeta temporal, con la empresa ya guardada."""
    motor = create_engine(f"sqlite:///{tmp_path / 'prueba.db'}")
    db.crear_tablas(motor)
    with db.sesion(motor) as s:
        s.add(empresa)
        s.commit()
        yield s


def detalle(codigo, nombre, region="Región Metropolitana de Santiago", monto=1_000_000,
            codigo_producto=49121502, producto="Colchones de espuma"):
    """Arma un detalle con la misma forma que el JSON real de la API."""
    return {
        "CodigoExterno": codigo,
        "Nombre": nombre,
        "Estado": "Publicada",
        "MontoEstimado": monto,
        "Comprador": {"NombreOrganismo": "Municipalidad de Prueba", "RegionUnidad": region + " "},
        "Fechas": {"FechaCierre": "2030-01-01T15:00:00", "FechaPublicacion": "2029-12-01T11:39:48.73"},
        "Items": {"Listado": [{"CodigoProducto": codigo_producto, "NombreProducto": producto, "Descripcion": ""}]},
    }


class APIFalsa:
    """Reemplaza a app.mercadopublico: devuelve datos fijos y cuenta las consultas."""

    def __init__(self, detalles: list[dict]):
        self.detalles = {d["CodigoExterno"]: d for d in detalles}
        self.consultas_detalle = 0

    def licitaciones_activas(self):
        return [{"CodigoExterno": c, "Nombre": d["Nombre"]} for c, d in self.detalles.items()]

    def detalle(self, codigo):
        self.consultas_detalle += 1
        return self.detalles.get(codigo)
