#!/usr/bin/env python3
"""
Copia los datos de una base de origen (p.ej. el MySQL de Hostinger, una vez
desbloqueada la cuenta) hacia el SQLite local que ahora usa la aplicación.

Uso:
    python3 tools/import_to_sqlite.py "mysql+pymysql://usuario:PASS@host:3306/basedatos?charset=utf8mb4"
    python3 tools/import_to_sqlite.py --force <URL>   # sobrescribe tablas que ya tengan datos

La contraseña debe ir url-encoded si trae caracteres como @ : / = > (usar
urllib.parse.quote_plus). Sólo se copian las tablas del modelo de la app y las
columnas que existen en ambos lados; el orden respeta las claves foráneas.
"""

import os
import sys

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emex import create_app  # noqa: E402
from emex.extensions import db  # noqa: E402

CHUNK = 500


def main():
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    source_url = args[0] if args else os.getenv("SOURCE_DATABASE_URL", "")

    if not source_url:
        print("❌ Falta la URL de origen (argumento o SOURCE_DATABASE_URL).")
        return 1

    app = create_app()
    dest_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if not dest_url.startswith("sqlite"):
        print(f"❌ El destino no es SQLite ({dest_url}). Abortado por seguridad.")
        return 1

    print(f"📥 Origen : {source_url.split('@')[-1]}")
    print(f"📤 Destino: {dest_url}\n")

    source_engine = create_engine(source_url)
    try:
        source_tables = set(inspect(source_engine).get_table_names())
    except Exception as exc:
        print(f"❌ No se pudo leer la base de origen: {exc}")
        return 1

    copiadas, omitidas = 0, []
    with app.app_context():
        dest_engine = db.engine

        if force:
            # Vaciar en orden inverso al de las FK (hijas antes que padres).
            with dest_engine.connect() as dest_conn:
                for table in reversed(db.metadata.sorted_tables):
                    if table.name in source_tables:
                        dest_conn.execute(table.delete())
                dest_conn.commit()
            print("🧹 Tablas destino vaciadas (--force)\n")

        # sorted_tables ordena por dependencias de FK: primero padres, luego hijas.
        for table in db.metadata.sorted_tables:
            if table.name not in source_tables:
                omitidas.append(f"{table.name} (no existe en origen)")
                continue

            src_table = Table(table.name, MetaData(), autoload_with=source_engine)
            columns = [c.name for c in table.columns if c.name in src_table.columns]
            if not columns:
                omitidas.append(f"{table.name} (sin columnas en común)")
                continue

            with dest_engine.connect() as dest_conn:
                existentes = dest_conn.execute(select(func.count()).select_from(table)).scalar_one()
                if existentes and not force:
                    omitidas.append(f"{table.name} ({existentes} filas ya presentes, usa --force)")
                    continue

                with source_engine.connect() as src_conn:
                    rows = src_conn.execute(
                        select(*[src_table.c[name] for name in columns])
                    ).mappings().all()

                for i in range(0, len(rows), CHUNK):
                    dest_conn.execute(table.insert(), [dict(r) for r in rows[i:i + CHUNK]])
                dest_conn.commit()

            print(f"✅ {table.name}: {len(rows)} filas")
            copiadas += 1

    if omitidas:
        print("\nℹ️  Tablas omitidas:")
        for item in omitidas:
            print(f"   - {item}")

    print(f"\n🎉 Listo: {copiadas} tablas copiadas. Recarga la aplicación web.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
