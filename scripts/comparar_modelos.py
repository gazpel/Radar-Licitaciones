"""Comparación de modelos locales sobre las mismas bases: tiempo, hallazgos y nivel de verificación.

Uso (desde la carpeta radar-licitaciones, con Ollama encendido):
    python -m scripts.comparar_modelos                      -> todos los modelos con todas las bases
    python -m scripts.comparar_modelos --modelos mistral    -> solo algunos modelos

No toca la base de datos. Deja los resultados en data/resultados/comparacion/.
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

from app.extraccion import extraer
from app.pdf import leer_paginas
from app.verificacion import ICONO, Nivel

# modelo -> think (False desactiva el razonamiento; None = el modelo no lo tiene)
MODELOS = {
    "granite4.2:8b": False,
    "mistral": None,
    "gemma4:e2b": None,
}
BASES = sorted(Path("data/bases").glob("Bases_*.pdf")) + [Path("data/bases/prueba_sintetica.pdf")]
SALIDA = Path("data/resultados/comparacion")


def correr(modelo: str, think: bool | None, pdf: Path) -> dict:
    paginas = leer_paginas(pdf)
    inicio = time.time()
    hallazgos = extraer(paginas, modelo=modelo, think=think)
    segundos = time.time() - inicio
    niveles = Counter(h.nivel.value for h in hallazgos)
    (SALIDA / f"{pdf.stem}__{modelo.replace(':', '_')}.json").write_text(
        json.dumps([h.model_dump(mode="json") for h in hallazgos], ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {
        "modelo": modelo, "bases": pdf.stem, "paginas": len(paginas), "segundos": round(segundos, 1),
        "hallazgos": len(hallazgos), **{n.value: niveles[n.value] for n in Nivel},
        "confiables": sum(h.confiable for h in hallazgos),
    }


def tabla_markdown(filas: list[dict]) -> str:
    lineas = ["| Modelo | Bases | Tiempo | Hallazgos | ✅ | 🟡 | 🟠 | 🔴 | % con cita en el PDF |",
              "|---|---|---|---|---|---|---|---|---|"]
    for f in filas:
        respaldados = f["textual"] + f["aproximada"] + f["interpretado"]
        pct = 100 * respaldados / f["hallazgos"] if f["hallazgos"] else 0
        lineas.append(f"| {f['modelo']} | {f['bases']} | {f['segundos']:.0f} s | {f['hallazgos']} | {f['textual']} | "
                      f"{f['aproximada']} | {f['interpretado']} | {f['sin_respaldo']} | {pct:.0f}% |")
    return "\n".join(lineas)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelos", nargs="*", default=list(MODELOS))
    args = parser.parse_args()
    SALIDA.mkdir(parents=True, exist_ok=True)

    archivo = SALIDA / "resumen.json"
    filas = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else []
    for modelo in args.modelos:
        for pdf in BASES:
            print(f"{modelo} · {pdf.name}...", flush=True)
            fila = correr(modelo, MODELOS.get(modelo), pdf)
            print("   " + "  ".join(f"{ICONO[n]} {fila[n.value]}" for n in Nivel) + f"  ({fila['segundos']:.0f} s)")
            filas = [f for f in filas if (f["modelo"], f["bases"]) != (modelo, pdf.stem)] + [fila]
            archivo.write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")

    (SALIDA / "resumen.md").write_text(tabla_markdown(filas) + "\n", encoding="utf-8")
    print("\n" + tabla_markdown(filas))


if __name__ == "__main__":
    main()
