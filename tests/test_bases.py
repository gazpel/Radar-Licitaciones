"""Pruebas de la carga asistida de bases (app/bases.py), con un extractor falso (sin LLM)."""
import pytest
from pypdf import PdfWriter

from app import bases
from app.bases import PDFSinTexto, hallazgos_vigentes, procesar_bases
from app.extraccion import Hallazgo, Tipo
from app.verificacion import Nivel
from tests.conftest import APIFalsa, detalle

PDF_SINTETICO = "data/bases/prueba_sintetica.pdf"


def extractor_falso(paginas, al_avanzar=None, modelo=None, think=None):
    return [
        Hallazgo(tipo=Tipo.plazo, descripcion="Cierre", pagina=1, cita="x" * 20, nivel=Nivel.textual, confiable=True),
        Hallazgo(tipo=Tipo.garantia, descripcion="Garantía", pagina=2, cita="y" * 20, nivel=Nivel.sin_respaldo),
    ]


@pytest.fixture(autouse=True)
def carpeta_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(bases, "CARPETA_BASES", tmp_path / "bases")


def test_guarda_extraccion_y_hallazgos(sesion):
    api = APIFalsa([detalle("1-1-LE26", "Colchones")])
    extraccion, _ = procesar_bases(sesion, "1-1-LE26", PDF_SINTETICO, modelo="falso", api=api,
                                   extractor=extractor_falso)
    guardados = hallazgos_vigentes(sesion, "1-1-LE26")
    assert extraccion.paginas == 4
    assert extraccion.archivo.endswith("1-1-LE26.pdf")
    assert {h.nivel for h in guardados} == {"textual", "sin_respaldo"}


def test_licitacion_que_no_estaba_se_agrega_desde_la_api(sesion):
    api = APIFalsa([detalle("2-2-LE26", "Colchones")])
    procesar_bases(sesion, "2-2-LE26", PDF_SINTETICO, modelo="falso", api=api, extractor=extractor_falso)
    from app.db import Licitacion
    assert "agregada a mano" in sesion.get(Licitacion, "2-2-LE26").motivos[0]


def test_vigentes_son_los_de_la_ultima_lectura(sesion):
    api = APIFalsa([detalle("1-1-LE26", "Colchones")])
    procesar_bases(sesion, "1-1-LE26", PDF_SINTETICO, modelo="a", api=api, extractor=extractor_falso)
    procesar_bases(sesion, "1-1-LE26", PDF_SINTETICO, modelo="b", api=api,
                   extractor=lambda *a, **k: extractor_falso(*a)[:1])
    assert len(hallazgos_vigentes(sesion, "1-1-LE26")) == 1


def test_pdf_sin_texto_se_rechaza(sesion, tmp_path):
    vacio = tmp_path / "escaneado.pdf"
    escritor = PdfWriter()
    escritor.add_blank_page(width=600, height=800)
    escritor.write(vacio)
    api = APIFalsa([detalle("1-1-LE26", "Colchones")])
    with pytest.raises(PDFSinTexto):
        procesar_bases(sesion, "1-1-LE26", vacio, modelo="falso", api=api, extractor=extractor_falso)
