"""Mini-demo para la Evaluación 1.

Uso (desde la carpeta radar-licitaciones, con el entorno virtual activo):
    python -m scripts.demo buscar               -> licitaciones activas de colchones (requiere MP_TICKET)
    python -m scripts.demo extraer data/bases/archivo.pdf   -> requisitos de unas bases con el LLM local
"""
import json
import sys
import time
from pathlib import Path

from app import mercadopublico
from app.extraccion import extraer
from app.pdf import leer_paginas
from app.verificacion import ICONO

PALABRAS_RUBRO = ["colchon", "colchones", "colchoneta"]


def buscar():
    licitaciones = mercadopublico.buscar_por_palabras(PALABRAS_RUBRO)
    print(f"{len(licitaciones)} licitaciones activas de colchonería:\n")
    for lic in licitaciones:
        print(f"  {lic['CodigoExterno']:<18} cierra {lic.get('FechaCierre', '?')[:10]}  {lic['Nombre']}")


def mostrar_avance(i, total, bloque):
    print(f"  Analizando bloque {i}/{total} (páginas {bloque[0]}-{bloque[-1]})...", flush=True)


def extraer_pdf(ruta: str):
    paginas = leer_paginas(ruta)
    print(f"{Path(ruta).name}: {len(paginas)} páginas\n")
    inicio = time.time()
    hallazgos = extraer(paginas, al_avanzar=mostrar_avance)
    print(f"\nListo en {time.time() - inicio:.0f} s. {len(hallazgos)} hallazgos:\n")

    for tipo in sorted({h.tipo.value for h in hallazgos}):
        print(f"[{tipo.upper()}]")
        for h in (h for h in hallazgos if h.tipo.value == tipo):
            print(f"  {ICONO[h.nivel]} {h.descripcion}  (pág. {h.pagina})")
        print()

    salida = Path("data/resultados") / f"{Path(ruta).stem}.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps([h.model_dump(mode="json") for h in hallazgos], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    verificados = sum(h.verificado for h in hallazgos)
    print(f"Citas encontradas en el PDF (✅ o 🟡): {verificados}/{len(hallazgos)}. Resultado guardado en {salida}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "buscar":
        buscar()
    elif len(sys.argv) >= 3 and sys.argv[1] == "extraer":
        extraer_pdf(sys.argv[2])
    else:
        print(__doc__)
