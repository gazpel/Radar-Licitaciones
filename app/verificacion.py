"""Verificación por niveles: ¿lo que dice el LLM está realmente en las bases?

Cada hallazgo trae una cita textual y una página. En código (sin LLM) se comprueba:

    textual       ✅ la cita aparece tal cual en el PDF (sin contar tildes, mayúsculas ni signos)
    aproximada    🟡 ≥ 90% de las palabras de la cita están en orden en un tramo del PDF (el modelo
                     cambió o quitó alguna palabra): se muestra el texto REAL del PDF, no el del modelo
    interpretado  🟠 la cita está, pero la descripción tiene números que no aparecen en la cita
                     (el modelo calculó o agregó algo): hay que revisarlo
    sin_respaldo  🔴 la cita no aparece en el PDF: no se muestra como dato

Los datos críticos (plazos, garantías, documentos) solo se consideran confiables con ✅ o 🟡.
"""
import re
from difflib import SequenceMatcher
from enum import Enum

from app.texto import normalizar

UMBRAL_APROXIMADA = 0.90
LARGO_MINIMO_CITA = 10  # caracteres; una cita más corta no prueba nada


class Nivel(str, Enum):
    textual = "textual"
    aproximada = "aproximada"
    interpretado = "interpretado"
    sin_respaldo = "sin_respaldo"


ICONO = {Nivel.textual: "✅", Nivel.aproximada: "🟡", Nivel.interpretado: "🟠", Nivel.sin_respaldo: "🔴"}
TIPOS_CRITICOS = {"plazo", "garantia", "documento"}


def numeros(texto: str) -> set[str]:
    """Números de un texto, sin separadores de miles: "$18.000.000 y 5%" -> {"18000000", "5"}."""
    encontrados = re.findall(r"\d[\d.,]*", texto)
    limpios = {re.sub(r"[.,](?=\d{3}\b)", "", n).rstrip(".,") for n in encontrados}
    # "04/10" y "4 de octubre" deben coincidir: se quitan los ceros a la izquierda
    return {n.replace(",", ".").lstrip("0") or "0" for n in limpios}


def _palabras(texto: str) -> tuple[list[str], list[int], list[str]]:
    """Separa un texto en palabras normalizadas, recordando de qué palabra original sale cada una."""
    originales = texto.split()
    tokens, origen = [], []
    for i, palabra in enumerate(originales):
        for token in normalizar(palabra).split():
            tokens.append(token)
            origen.append(i)
    return tokens, origen, originales


def _mejor_parecido(cita: str, pagina: str) -> tuple[float, str]:
    """Busca el tramo de la página que mejor contiene las palabras de la cita, en el mismo orden.

    Devuelve (cobertura 0-1, texto original del tramo). La cobertura es la fracción de palabras
    de la cita que aparecen en orden dentro del tramo. Así se reconocen dos casos:
    - el modelo cambió alguna palabra ("PRECISO" en vez de "PRECIO", "retraso" en vez de "atraso");
    - el modelo resumió la cita quitando palabras del medio.
    El tramo no puede ser mucho más largo que la cita, para no unir palabras sueltas de la página.
    """
    cita_tokens = normalizar(cita).split()
    n = len(cita_tokens)
    tokens, origen, originales = _palabras(pagina)
    if n == 0 or not tokens:
        return 0.0, ""
    # Solo se prueban tramos que empiezan en alguna de las primeras palabras "con contenido" de la cita
    anclas = {t for t in cita_tokens[:6] if len(t) > 3} or set(cita_tokens[:3])
    comparador = SequenceMatcher(autojunk=False)
    comparador.set_seq2(cita_tokens)
    mejor, texto = 0.0, ""
    for inicio, token in enumerate(tokens):
        if token not in anclas:
            continue
        comparador.set_seq1(tokens[inicio:inicio + 2 * n + 5])
        bloques = [b for b in comparador.get_matching_blocks() if b.size]
        cobertura = sum(b.size for b in bloques) / n
        if cobertura > mejor:
            primero = inicio + bloques[0].a
            ultimo = inicio + bloques[-1].a + bloques[-1].size - 1
            mejor = cobertura
            texto = " ".join(originales[origen[primero]:origen[ultimo] + 1])
    return mejor, texto


def verificar(cita: str, descripcion: str, pagina: int, paginas: list[str],
              candidatas: list[int]) -> tuple[Nivel, int, str]:
    """Clasifica un hallazgo. Devuelve (nivel, página corregida, texto real del PDF).

    `candidatas` son las páginas donde buscar si la cita no está en la página indicada
    (normalmente, las del bloque que leyó el modelo).
    """
    cita_norm = normalizar(cita)
    if len(cita_norm) < LARGO_MINIMO_CITA:
        return Nivel.sin_respaldo, pagina, ""

    orden = [pagina] + [p for p in candidatas if p != pagina]
    validas = [p for p in orden if 1 <= p <= len(paginas)]

    def texto(numero: int, con_siguiente: bool) -> str:
        """Texto de una página; con_siguiente=True le agrega la página que sigue (citas que cruzan el salto)."""
        if con_siguiente and numero < len(paginas):
            return paginas[numero - 1] + "\n" + paginas[numero]
        return paginas[numero - 1]

    nivel, pagina_real, texto_real = Nivel.sin_respaldo, pagina, ""
    # Primero en cada página sola; si no aparece, en cada página unida a la siguiente
    for con_siguiente in (False, True):
        exacta = next((n for n in validas if cita_norm in normalizar(texto(n, con_siguiente))), None)
        if exacta is not None:
            nivel, pagina_real, texto_real = Nivel.textual, exacta, cita
            break
        mejor = (0.0, pagina, "")
        for numero in validas:
            parecido, trozo = _mejor_parecido(cita, texto(numero, con_siguiente))
            if parecido > mejor[0]:
                mejor = (parecido, numero, trozo)
        if mejor[0] >= UMBRAL_APROXIMADA:
            nivel, pagina_real, texto_real = Nivel.aproximada, mejor[1], mejor[2]
            break

    # Números de la descripción que no están en el texto del PDF → el modelo los calculó o inventó
    if nivel in (Nivel.textual, Nivel.aproximada) and not numeros(descripcion) <= numeros(texto_real):
        nivel = Nivel.interpretado
    return nivel, pagina_real, texto_real


def es_confiable(tipo: str, nivel: Nivel) -> bool:
    """Un dato crítico solo es confiable si su cita está en el PDF (✅ o 🟡)."""
    if tipo in TIPOS_CRITICOS:
        return nivel in (Nivel.textual, Nivel.aproximada)
    return nivel != Nivel.sin_respaldo
