"""Pregunta a las bases de una licitación desde la consola (RAG).

Uso (desde radar-licitaciones, con las bases ya cargadas):
    python -m scripts.preguntar 2408-242-L126 "¿Qué pasa si me atraso en la entrega?"
    python -m scripts.preguntar 2408-242-L126 "¿..." --ver-fragmentos
"""
import argparse

from app import db
from app.rag import preguntar


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("codigo")
    parser.add_argument("pregunta")
    parser.add_argument("--ver-fragmentos", action="store_true", help="muestra los fragmentos recuperados")
    args = parser.parse_args()

    db.crear_tablas()
    with db.sesion() as s:
        r = preguntar(s, args.codigo, args.pregunta)
    if args.ver_fragmentos:
        print("Fragmentos recuperados:")
        for f in r.fragmentos:
            print(f"  [pág. {f.pagina}] {f.texto[:150]}…")
        print()
    print(f"{r.icono if r.encontrado else 'ℹ️'} {r.respuesta}  ({r.segundos:.0f} s)")
    for c in r.citas:
        print(f"   {c.nivel.value:<13} pág. {c.pagina}: «{c.texto_real or c.cita}»")


if __name__ == "__main__":
    main()
