#!/usr/bin/env python3
"""
Sincroniza el esquema de la base configurada en la app (SQLite por defecto).

Sustituye al script anterior, que abría una conexión MySQL directa con pymysql
contra el servidor externo. Ahora reutiliza el engine de la propia aplicación,
así que funciona igual con SQLite local o con cualquier otro motor.

Uso:  python3 run_migration.py [--yes]
"""

import sys

from emex import create_app, _ensure_runtime_schema, _ensure_admin_user
from emex.extensions import db


def main():
    print("\n" + "=" * 60)
    print("  SINCRONIZACIÓN DE ESQUEMA")
    print("=" * 60 + "\n")

    app = create_app()  # create_app ya crea/parcha el esquema al arrancar
    print(f"📊 Base de datos: {app.config['SQLALCHEMY_DATABASE_URI']}")

    if "--yes" not in sys.argv:
        response = input("⚠️  Esta operación puede modificar la base. ¿Continuar? (s/N): ")
        if response.lower() not in ("s", "si", "sí", "y", "yes"):
            print("❌ Cancelado")
            return 0

    _ensure_runtime_schema(app)
    _ensure_admin_user(app)

    with app.app_context():
        from sqlalchemy import inspect

        tablas = sorted(inspect(db.engine).get_table_names())
    print(f"✅ Tablas presentes ({len(tablas)}): {', '.join(tablas)}")
    print("\n🎉 Listo. Recarga la aplicación web si está en ejecución.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
