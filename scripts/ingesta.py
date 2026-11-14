"""Ingesta diaria del Radar de Licitaciones.

Uso (desde la carpeta radar-licitaciones, con el entorno virtual activo):
    python -m scripts.ingesta                -> consulta la API, filtra y guarda (se puede repetir sin duplicar)
    python -m scripts.ingesta --perfil       -> (re)carga el perfil desde data/empresa_colchoneria.json
    python -m scripts.ingesta --sin-puntaje  -> no calcula el puntaje con la ficha (no usa el LLM)

Al final da un primer puntaje de conveniencia, solo con la ficha, a las abiertas que no tienen:
así el resumen dice a cuáles conviene descargarles las bases (opción B, provisoria).
"""
import sys

from app import db
from app.conveniencia import PUNTAJE_PARA_BASES, puntuar_sin_puntaje
from app.ingesta import cargar_empresa, ejecutar, similitud_configurada

PERFIL = "data/empresa_colchoneria.json"


def mostrar_avance(i, total, codigo):
    print(f"  Detalle {i}/{total}: {codigo}", flush=True)


def main():
    db.crear_tablas()
    with db.sesion() as s:
        if "--perfil" in sys.argv or db.empresa_actual(s) is None:
            empresa = cargar_empresa(s, PERFIL)
            print(f"Perfil cargado: {empresa.nombre}\n")

        print("Consultando licitaciones activas en Mercado Público...")
        r = ejecutar(s, al_avanzar=mostrar_avance, similitud=similitud_configurada())
        g = r.ingesta

        print(f"\nIngesta #{g.id} lista en {(g.fin - g.inicio).total_seconds():.0f} s")
        print(f"  {g.activas} activas -> {g.candidatas} candidatas por nombre -> {g.relevantes} relevantes ({g.nuevas} nuevas)\n")
        for lic in r.nuevas:
            cierre = f"{lic.fecha_cierre:%d/%m %H:%M}" if lic.fecha_cierre else "sin fecha"
            print(f"  [NUEVA]  {lic.codigo:<16} cierra {cierre}  {lic.nombre[:70]}")
            for motivo in lic.motivos:
                print(f"           + {motivo}")
        for lic in r.actualizadas:
            print(f"  [YA ESTABA] {lic.codigo:<16} {lic.nombre[:70]}")
        if r.descartadas:
            print("\n  Descartadas en la etapa 2:")
            for d in r.descartadas:
                print(f"  [NO] {d.codigo:<16} {d.nombre[:60]}")
                for rechazo in d.rechazos:
                    print(f"           - {rechazo}")
        for error in r.errores:
            print(f"  [ERROR] {error}")

        if "--sin-puntaje" not in sys.argv:
            print("
Puntaje de conveniencia con la ficha (sin bases)...")
            puntuadas, errores = puntuar_sin_puntaje(
                s, al_avanzar=lambda i, total, codigo: print(f"  Evaluando {i}/{total}: {codigo}", flush=True))
            for lic in puntuadas:
                marca = "LEER BASES" if lic.puntaje >= PUNTAJE_PARA_BASES else "opcional  "
                print(f"  {lic.puntaje}/5 [{marca}] {lic.codigo:<16} {lic.nombre[:60]}")
            for error in errores:
                print(f"  [ERROR] {error}")


if __name__ == "__main__":
    main()
