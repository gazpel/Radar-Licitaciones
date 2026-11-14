"""Filtro por reglas: decide qué licitaciones le sirven a la empresa y explica por qué.

Funciona como un embudo de dos etapas, para no gastar consultas a la API:
1. Con el listado de activas (solo trae código, nombre y cierre): ¿el nombre tiene alguna palabra clave?
   1b. Si no la tiene, ¿el nombre se parece en significado al rubro? (embeddings, ver app/ingesta.py)
2. Con el detalle (una consulta por licitación): ¿el producto es del rubro, la región y el monto calzan?

Cada regla deja un motivo escrito, así en el panel se puede mostrar por qué pasó o se descartó.
"""
from dataclasses import dataclass, field

from app.db import Empresa
from app.texto import normalizar


@dataclass
class Evaluacion:
    pasa: bool
    motivos: list[str] = field(default_factory=list)  # por qué sirve
    rechazos: list[str] = field(default_factory=list)  # por qué no sirve
    excluida: bool = False  # tiene una palabra excluida: no se rescata por similitud


def _palabras_en(texto: str, palabras: list[str]) -> list[str]:
    texto = normalizar(texto)
    return [p for p in palabras if normalizar(p) in texto]


def etapa_nombre(licitacion: dict, empresa: Empresa) -> Evaluacion:
    """Etapa 1, sobre el listado de activas."""
    nombre = licitacion.get("Nombre", "")
    excluidas = _palabras_en(nombre, empresa.palabras_excluidas)
    if excluidas:
        return Evaluacion(False, rechazos=[f"nombre con palabra excluida: {', '.join(excluidas)}"], excluida=True)
    encontradas = _palabras_en(nombre, empresa.palabras_clave)
    if encontradas:
        return Evaluacion(True, motivos=[f"nombre contiene: {', '.join(encontradas)}"])
    return Evaluacion(False, rechazos=["el nombre no tiene palabras clave"])


def _items(detalle: dict) -> list[dict]:
    return (detalle.get("Items") or {}).get("Listado") or []


def etapa_detalle(detalle: dict, empresa: Empresa) -> Evaluacion:
    """Etapa 2, sobre el detalle. Deben cumplirse las tres reglas: rubro, región y monto."""
    ev = Evaluacion(True)

    # Regla 1, rubro: código UNSPSC del perfil, o palabra clave en el producto pedido.
    # Se acepta cualquiera de las dos porque los organismos a veces eligen un código parecido
    # (p. ej. "Camas de cuidado del paciente" para comprar colchones).
    items = _items(detalle)
    codigos = {str(i.get("CodigoProducto")) for i in items}
    comunes = sorted(codigos & set(empresa.unspsc))
    texto_items = " ".join(f"{i.get('NombreProducto', '')} {i.get('Descripcion', '')}" for i in items)
    en_items = _palabras_en(texto_items, empresa.palabras_clave)
    if comunes:
        ev.motivos.append(f"código UNSPSC del rubro: {', '.join(comunes)}")
    elif en_items:
        ev.motivos.append(f"producto pedido contiene: {', '.join(en_items)}")
    else:
        ev.rechazos.append("ningún producto es del rubro")

    # Regla 2, región del comprador (lista vacía = todo Chile)
    region = (detalle.get("Comprador") or {}).get("RegionUnidad", "")
    if empresa.regiones:
        if any(normalizar(r) in normalizar(region) for r in empresa.regiones):
            ev.motivos.append(f"región atendida: {region.strip()}")
        else:
            ev.rechazos.append(f"región no atendida: {region.strip() or 'sin región'}")

    # Regla 3, monto estimado (muchos organismos no lo publican: en ese caso no se descarta)
    monto = detalle.get("MontoEstimado")
    if monto is None:
        ev.motivos.append("monto no publicado (revisar en las bases)")
    elif empresa.monto_min is not None and monto < empresa.monto_min:
        ev.rechazos.append(f"monto bajo el mínimo: ${monto:,.0f}".replace(",", "."))
    elif empresa.monto_max is not None and monto > empresa.monto_max:
        ev.rechazos.append(f"monto sobre el máximo: ${monto:,.0f}".replace(",", "."))
    else:
        ev.motivos.append(f"monto dentro del rango: ${monto:,.0f}".replace(",", "."))

    ev.pasa = not ev.rechazos
    return ev
