"""Experimento (rama exp/laya-ragas): evaluar las respuestas del RAG con RAGAS y compararlo con la verificación propia.

Se usan las 48 respuestas de Granite 4.2 8B ya guardadas (prompt 2, data/resultados/rag/evaluacion.json).
Para cada una se reconstruyen los 6 fragmentos que recibió (la búsqueda es determinista) y se calculan:
  - Faithfulness (fidelidad): ¿lo que afirma la respuesta se deduce de los fragmentos? (0 a 1)
  - Answer relevancy: ¿la respuesta contesta lo que se preguntó? (0 a 1, usa embeddings)
Juez: Qwen3 8B por Ollama (otra familia que Granite, para no autoevaluarse), sin razonamiento.
Embeddings: granite-embedding:278m (los mismos del radar).

Pregunta del experimento: ¿RAGAS detecta lo que la verificación por citas no ve? (cita real, respuesta incorrecta)

Uso (desde radar-licitaciones, con .venv-exp):  python -m experimentos.ragas_eval
"""
import asyncio
import json
import time
from pathlib import Path

from openai import AsyncOpenAI
from ragas.embeddings.base import embedding_factory
from ragas.llms import llm_factory
from ragas.metrics.collections import AnswerRelevancy, Faithfulness

from app import busqueda
from app.db import Fragmento
from app.pdf import leer_paginas
from app.rag import _a_bytes, fragmentar, recuperar

JUEZ = "qwen3:8b"
ENTRADA = Path("data/resultados/rag/evaluacion.json")
SALIDA = Path("data/resultados/experimentos")
# Respuestas que sabemos incorrectas aunque su cita es real (revisadas a mano en el S5)
CONOCIDAS = {("Bases_1057384-148-L126.pdf", "¿Cuánto se demoran en pagarme?"): "dice 30 días hábiles; las bases dicen corridos",
             ("Bases_2408-242-L126.pdf", "¿Dónde llevo los productos?"): "responde el plazo, no el lugar"}


def fragmentos_de(pdf: Path) -> list[Fragmento]:
    paginas = leer_paginas(pdf)
    trozos = fragmentar(paginas)
    vectores = busqueda.embeber([t.texto for t in trozos])
    return [Fragmento(extraccion_id=0, licitacion_codigo="", pagina=t.pagina, orden=t.orden, texto=t.texto,
                      vector=_a_bytes(v)) for t, v in zip(trozos, vectores)]


async def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    datos = json.loads(ENTRADA.read_text(encoding="utf-8"))
    respuestas = [r for r in datos["respuestas"] if not r.get("fuera_de_tema") and r["encontrado"]]
    cliente = AsyncOpenAI(api_key="ollama", base_url="http://localhost:11434/v1")
    llm = llm_factory(JUEZ, provider="openai", client=cliente, reasoning_effort="none")
    emb = embedding_factory("openai", model="granite-embedding:278m", client=cliente)
    fidelidad, relevancia = Faithfulness(llm=llm), AnswerRelevancy(llm=llm, embeddings=emb)

    cache, filas = {}, []
    for n, r in enumerate(respuestas, start=1):
        if r["bases"] not in cache:
            cache[r["bases"]] = fragmentos_de(Path("data/bases") / r["bases"])
        contextos = [f.texto for f in recuperar(r["pregunta"], cache[r["bases"]])]
        inicio = time.time()
        try:
            f = (await fidelidad.ascore(user_input=r["pregunta"], response=r["respuesta"],
                                        retrieved_contexts=contextos)).value
        except Exception as e:  # el juez a veces no cumple el formato
            f = None
            print(f"   fidelidad falló: {type(e).__name__}")
        try:
            a = (await relevancia.ascore(user_input=r["pregunta"], response=r["respuesta"])).value
        except Exception as e:
            a = None
            print(f"   relevancia falló: {type(e).__name__}")
        fila = {"bases": r["bases"], "pregunta": r["pregunta"], "respuesta": r["respuesta"], "nivel_radar": r["nivel"],
                "pagina_correcta": r["pagina_correcta"], "faithfulness": f, "answer_relevancy": a,
                "segundos": round(time.time() - inicio, 1),
                "conocida_incorrecta": CONOCIDAS.get((r["bases"], r["pregunta"]))}
        filas.append(fila)
        print(f"{n:2}/{len(respuestas)} [{r['nivel']:<12}] fid {f if f is None else round(f, 2)!s:<5} "
              f"rel {a if a is None else round(a, 2)!s:<5} {fila['segundos']:>5} s  {r['pregunta'][:60]}"
              + (f"   <- CONOCIDA: {fila['conocida_incorrecta']}" if fila["conocida_incorrecta"] else ""))

    validas = [x for x in filas if x["faithfulness"] is not None]
    rel = [x["answer_relevancy"] for x in filas if x["answer_relevancy"] is not None]
    resumen = {
        "juez": JUEZ, "respuestas": len(filas),
        "faithfulness_promedio": round(sum(x["faithfulness"] for x in validas) / len(validas), 3),
        "answer_relevancy_promedio": round(sum(rel) / len(rel), 3),
        "radar_verificada_pero_ragas_baja": [  # ✅/🟡 para nosotros, fidelidad < 0,5 para RAGAS
            (x["bases"], x["pregunta"], x["respuesta"], x["faithfulness"]) for x in validas
            if x["nivel_radar"] in ("textual", "aproximada") and x["faithfulness"] < 0.5],
        "por_nivel_radar": {n: round(sum(x["faithfulness"] for x in validas if x["nivel_radar"] == n) /
                                     max(1, sum(x["nivel_radar"] == n for x in validas)), 3)
                            for n in ("textual", "aproximada", "interpretado", "sin_respaldo")},
        "conocidas": [(x["pregunta"], x["faithfulness"], x["answer_relevancy"]) for x in filas if x["conocida_incorrecta"]],
        "segundos_promedio": round(sum(x["segundos"] for x in filas) / len(filas), 1),
        "fallas_del_juez": len(filas) - len(validas),
    }
    print("\n" + json.dumps(resumen, ensure_ascii=False, indent=2))
    (SALIDA / "ragas.json").write_text(json.dumps({"resumen": resumen, "detalle": filas}, ensure_ascii=False, indent=2),
                                       encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
