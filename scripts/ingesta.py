"""Ingesta diaria del Radar de Licitaciones.

Uso (desde la carpeta radar-licitaciones, con el entorno virtual activo):
    python -m scripts.ingesta                -> consulta la API, filtra y guarda (se puede repetir sin duplicar)
    python -m scripts.ingesta --perfil       -> (re)carga el perfil desde data/empresa_colchoneria.json
"""
import sys

from app import db
from app.ingesta import cargar_empresa, ejecutar

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
        r = ejecutar(s, al_avanzar=mostrar_avance)
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


if __name__ == "__main__":
    main()
