"""Puntaje de conveniencia (HU-05): ¿le conviene a la empresa postular a esta licitación y por qué?

El LLM recibe solo datos ya verificados: el perfil, la ficha de la licitación y los hallazgos
confiables de las bases. Los cálculos (días al cierre, monto en el rango) se hacen en código y se
le entregan hechos, porque los modelos se equivocan con fechas y aritmética.
"""
from datetime import datetime

from pydantic import BaseModel, Field

from app import llm
from app.db import Empresa, HallazgoGuardado, Licitacion


class EvaluacionConveniencia(BaseModel):
    puntaje: int = Field(ge=1, le=5, description="1 = no conviene, 5 = conviene mucho")
    a_favor: list[str]
    en_contra: list[str]
    resumen: str


SISTEMA = """Eres un asesor de licitaciones públicas para una PyME chilena.
Evalúa si a la empresa le conviene postular a la licitación, con un puntaje de 1 a 5:
5 = calza con el rubro y es abordable; 3 = conviene, pero con dudas o exigencias importantes;
1 = no calza o es muy difícil de cumplir.

Reglas:
- Usa solo los datos entregados. No supongas requisitos, montos ni fechas que no aparezcan.
- Sobre la empresa, sabes SOLO lo que dice su perfil: no afirmes que tiene inscripciones, certificados,
  experiencia ni documentos que el perfil no mencione.
- Los datos de las bases son exigencias que la empresa tendría que cumplir. Las que implican costo
  o trabajo (garantías, documentos, programas, plazos cortos) van en "en_contra".
- Nunca digas que algo "no se especifica" si aparece en los datos entregados.
- Si falta información importante (monto, garantías, plazos), menciónalo en "en_contra".
- Si la licitación ya cerró, el puntaje es 1 y el resumen lo dice.
- Considera: si el producto es del rubro, la región, el monto, el tiempo para preparar la oferta,
  las garantías exigidas, los documentos y los criterios de evaluación.
- Escribe máximo 4 razones a favor y 4 en contra, cada una de máximo 20 palabras.
- El resumen es una frase para el dueño de la PyME."""


def _ficha(licitacion: Licitacion, empresa: Empresa, ahora: datetime) -> str:
    lineas = [
        f"EMPRESA: {empresa.nombre}. Rubro: {empresa.rubro}.",
        f"Regiones que atiende: {', '.join(empresa.regiones) or 'todo Chile'}.",
        f"Montos que puede abordar: ${empresa.monto_min:,.0f} a ${empresa.monto_max:,.0f}.".replace(",", "."),
        "",
        f"LICITACIÓN {licitacion.codigo}: {licitacion.nombre}",
        f"Comprador: {licitacion.organismo} ({licitacion.region}).",
        f"Productos: {', '.join(licitacion.productos) or 'sin detalle'}.",
    ]
    if licitacion.monto is not None:
        lineas.append(f"Monto estimado: ${licitacion.monto:,.0f}.".replace(",", "."))
    else:
        lineas.append("Monto estimado: no publicado.")
    if licitacion.fecha_cierre:
        dias = (licitacion.fecha_cierre - ahora).days
        plazo = "YA CERRÓ: no se puede ofertar" if licitacion.fecha_cierre < ahora else f"quedan {dias} días para ofertar"
        lineas.append(f"Cierre: {licitacion.fecha_cierre:%d/%m/%Y %H:%M} ({plazo}).")
    lineas.append(f"Por qué pasó el filtro: {'; '.join(licitacion.motivos)}.")
    return "\n".join(lineas)


def evaluar(licitacion: Licitacion, empresa: Empresa, hallazgos: list[HallazgoGuardado],
            ahora: datetime | None = None, modelo: str | None = None,
            think: bool | None = None) -> EvaluacionConveniencia:
    texto = _ficha(licitacion, empresa, ahora or datetime.now())
    confiables = [h for h in hallazgos if h.confiable]
    if confiables:
        texto += "\n\nDATOS VERIFICADOS EN LAS BASES:\n" + "\n".join(
            f"- [{h.tipo}] {h.descripcion} (pág. {h.pagina})" for h in confiables)
    else:
        texto += "\n\nLas bases todavía no han sido leídas: evalúa solo con la ficha."
    datos = llm.generar_json(SISTEMA, texto, EvaluacionConveniencia.model_json_schema(),
                             modelo=modelo, think=think)
    return EvaluacionConveniencia.model_validate(datos)
