"""Carga asistida de bases: lee el PDF de una licitación, verifica y guarda los hallazgos.

Uso (desde la carpeta radar-licitaciones, con el entorno virtual activo):
    python -m scripts.extraer CODIGO ruta/a/las_bases.pdf
    python -m scripts.extraer CODIGO ruta.pdf --modelo granite4.2:8b --sin-think

Las bases se descargan a mano desde la ficha (la ficha web las protege con reCAPTCHA).
El enlace a la ficha aparece en /licitaciones/{codigo} (campo url_ficha).
"""
import argparse
import time
from collections import Counter

from app import db
from app.bases import PDFSinTexto, procesar_bases
from app.verificacion import ICONO, Nivel


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("codigo")
    parser.add_argument("pdf")
    parser.add_argument("--modelo", help="modelo de Ollama (por defecto, LLM_MODEL del .env)")
    parser.add_argument("--sin-think", action="store_true", help="desactiva el razonamiento (Granite 4.2)")
    args = parser.parse_args()

    db.crear_tablas()
    inicio = time.time()

    def avance(i, total, bloque):
        print(f"  Bloque {i}/{total} (páginas {bloque[0]}-{bloque[-1]}) · {time.time() - inicio:.0f} s", flush=True)

    with db.sesion() as s:
        try:
            extraccion, hallazgos = procesar_bases(
                s, args.codigo, args.pdf, modelo=args.modelo,
                think=False if args.sin_think else None, al_avanzar=avance)
        except PDFSinTexto as error:
            print(f"No se pudo leer: {error}")
            return

    niveles = Counter(h.nivel for h in hallazgos)
    print(f"\n{extraccion.paginas} páginas leídas con {extraccion.modelo} en {extraccion.segundos:.0f} s. "
          f"{len(hallazgos)} hallazgos: " + "  ".join(f"{ICONO[n]} {niveles[n]}" for n in Nivel) + "\n")
    for tipo in sorted({h.tipo.value for h in hallazgos}):
        print(f"[{tipo.upper()}]")
        for h in (h for h in hallazgos if h.tipo.value == tipo):
            aviso = "" if h.confiable else "  ← revisar"
            print(f"  {ICONO[h.nivel]} {h.descripcion} (pág. {h.pagina}){aviso}")
            if h.nivel == Nivel.aproximada:
                print(f"       Texto real: «{h.texto_real}»")
        print()


if __name__ == "__main__":
    main()
