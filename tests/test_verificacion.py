"""Pruebas de la verificación por niveles (app/verificacion.py)."""
from app.verificacion import Nivel, es_confiable, numeros, verificar

PAGINAS = [
    "Bases administrativas. El presupuesto disponible es de $18.000.000 impuestos incluidos.",
    "Garantía de fiel cumplimiento por un monto equivalente al 5% del valor total del contrato. "
    "Se aplicará una multa de 1 UTM por cada día de atraso en la entrega.",
    "Plazo para consultas: 04/10/2026 a las 15:00 horas.",
]


def test_cita_exacta_es_textual():
    nivel, pagina, _ = verificar("equivalente al 5% del valor total del contrato",
                                 "Garantía del 5% del contrato", 2, PAGINAS, [1, 2, 3])
    assert (nivel, pagina) == (Nivel.textual, 2)


def test_tildes_y_mayusculas_no_importan():
    nivel, _, _ = verificar("GARANTIA DE FIEL CUMPLIMIENTO por un monto", "Garantía", 2, PAGINAS, [2])
    assert nivel == Nivel.textual


def test_pagina_equivocada_se_corrige():
    nivel, pagina, _ = verificar("presupuesto disponible es de $18.000.000", "Presupuesto: $18.000.000",
                                 3, PAGINAS, [1, 2, 3])
    assert (nivel, pagina) == (Nivel.textual, 1)


def test_palabra_cambiada_es_aproximada_y_muestra_el_texto_real():
    """Caso real de Granite en la Evaluación 1: escribió "retraso" donde las bases dicen "atraso"."""
    nivel, _, texto_real = verificar("multa de 1 UTM por cada día de retraso en la entrega",
                                     "Multa de 1 UTM por día", 2, PAGINAS, [2])
    assert nivel == Nivel.aproximada
    assert "atraso" in texto_real


def test_valor_calculado_por_el_modelo_es_interpretado():
    """Caso real de Granite: agregó "$900.000" (5% de $18.000.000), que no está en la cita."""
    nivel, _, _ = verificar("equivalente al 5% del valor total del contrato",
                            "Garantía de $900.000 (5% del contrato)", 2, PAGINAS, [2])
    assert nivel == Nivel.interpretado


def test_cita_inventada_es_sin_respaldo():
    nivel, _, _ = verificar("se exige experiencia mínima de diez años en el rubro",
                            "Experiencia de 10 años", 1, PAGINAS, [1, 2, 3])
    assert nivel == Nivel.sin_respaldo


def test_cita_muy_corta_no_prueba_nada():
    assert verificar("5%", "5%", 2, PAGINAS, [2])[0] == Nivel.sin_respaldo


def test_fecha_con_ceros_a_la_izquierda():
    nivel, _, _ = verificar("Plazo para consultas: 04/10/2026 a las 15:00 horas",
                            "Consultas hasta el 4 de octubre de 2026, 15:00", 3, PAGINAS, [3])
    assert nivel == Nivel.textual


def test_numeros_sin_separadores():
    assert numeros("$18.000.000 y 5% y 3,5 UTM") == {"18000000", "5", "3.5"}


def test_dato_critico_interpretado_no_es_confiable():
    assert not es_confiable("garantia", Nivel.interpretado)
    assert es_confiable("garantia", Nivel.aproximada)
    assert es_confiable("informacion_general", Nivel.interpretado)
    assert not es_confiable("requisito", Nivel.sin_respaldo)


def test_cita_resumida_quitando_palabras_es_aproximada():
    """Caso real: el modelo citó "Transcurridas 24 horas sin aceptación..." omitiendo palabras del medio."""
    pagina = ("Transcurridas 24 horas desde la emisión de la orden de compra sin que esta sea aceptada, "
              "la Municipalidad solicitará su rechazo, entendiéndose definitivamente rechazada.")
    nivel, _, texto_real = verificar("Transcurridas 24 horas desde la emisión sin que esta sea aceptada, la "
                                     "Municipalidad solicitará su rechazo", "Rechazo tras 24 horas", 1, [pagina], [1])
    assert nivel == Nivel.aproximada
    assert "orden de compra" in texto_real


def test_palabras_sueltas_lejanas_no_cuentan_como_cita():
    pagina = " ".join(["relleno"] * 200) + " garantía " + " ".join(["relleno"] * 200) + " seriedad oferta"
    nivel, _, _ = verificar("garantía de seriedad de la oferta", "Garantía", 1, [pagina], [1])
    assert nivel == Nivel.sin_respaldo


def test_cita_que_cruza_el_salto_de_pagina():
    paginas = ["Instrucciones. Los oferentes deberán enviar sus ofertas por medio del formulario",
               "electrónico disponible en dicha plataforma. Otras reglas."]
    nivel, pagina, _ = verificar("enviar sus ofertas por medio del formulario electrónico disponible",
                                 "Ofertas por formulario electrónico", 2, paginas, [1, 2])
    assert (nivel, pagina) == (Nivel.textual, 1)
