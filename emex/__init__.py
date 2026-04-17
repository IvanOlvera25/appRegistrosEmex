# emex/__init__.py
import os
import click
from flask import Flask, redirect, url_for
from dotenv import load_dotenv
from sqlalchemy import text
from flask_compress import Compress

# Extensiones y blueprints (importes ABSOLUTOS)
from emex.extensions import db, login_manager, migrate
from emex.models import User
from emex.auth.routes import auth_bp
from emex.worker.routes import worker_bp
from emex.admin.routes import admin_bp
from emex.api.routes import api_bp


def create_app():
    # Cargar .env desde la raíz del proyecto (un nivel arriba de emex/)
    basedir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(basedir, '.env'))

    app = Flask(__name__, static_folder="static", template_folder="templates")

    # ---------- Configuración base ----------
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///emex.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_AS_ASCII"] = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["TEMPLATES_AUTO_RELOAD"] = os.getenv("TEMPLATES_AUTO_RELOAD", "0") == "1"

    # Configuración de compresión para mejorar velocidad
    app.config["COMPRESS_MIMETYPES"] = [
        'text/html', 'text/css', 'text/xml', 'application/json',
        'application/javascript', 'text/javascript'
    ]
    app.config["COMPRESS_LEVEL"] = 6
    app.config["COMPRESS_MIN_SIZE"] = 500

    # Evitar "MySQL server has gone away" en entornos como PythonAnywhere
    engine_opts = {
        "pool_pre_ping": True,
        # PythonAnywhere suele cerrar conexiones ociosas ~300s: reciclar antes
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "280")),
    }
    if os.getenv("DB_POOL_SIZE"):
        engine_opts["pool_size"] = int(os.getenv("DB_POOL_SIZE"))
    if os.getenv("DB_MAX_OVERFLOW"):
        engine_opts["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW"))
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts

    # ---------- Inicializar extensiones ----------
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    Compress(app)  # Habilitar compresión gzip

    # Jinja helpers disponibles en plantillas (por si los usas)
    app.jinja_env.globals.update(
        hasattr=hasattr,
        getattr=getattr,
        isinstance=isinstance,
        len=len,
    )

    # ---------- Blueprints ----------
    app.register_blueprint(auth_bp)
    app.register_blueprint(worker_bp, url_prefix="/worker")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp)

    # ---------- CLI: seed general ----------
    @app.cli.command("seed")
    def seed():
        from emex.seed import seed_data
        seed_data(app)
        print("Seed completado.")

    # ---------- CLI: seed de unidades ----------
    @app.cli.command("seed-units")
    @click.option("--reset", is_flag=True, help="Borra unidades existentes antes de sembrar.")
    @click.option("--hard", is_flag=True, help="También borra operator_logs (destructivo).")
    def seed_units(reset, hard):
        """Crea un set de unidades de ejemplo (evita duplicados por code)."""
        from emex.models import Unit

        if reset:
            if hard:
                # BORRADO DURO: elimina los logs que referencien unidades
                db.session.execute(text("DELETE FROM operator_logs"))
                db.session.commit()
            else:
                # BORRADO SUAVE: nulifica las referencias a units
                db.session.execute(
                    text("UPDATE operator_logs SET fuel_unit_id = NULL, si_unit_id = NULL")
                )
                db.session.commit()

            # Ahora sí se pueden borrar las unidades sin violar FKs
            Unit.query.delete()
            db.session.commit()


        created = 0
        for code, plate, desc, typ in data:
            if not Unit.query.filter_by(code=code).first():
                db.session.add(Unit(code=code, plate=plate, description=desc, type=typ))
                created += 1

        db.session.commit()
        total = Unit.query.count()
        print(f"Unidades nuevas: {created} | Total en BD: {total}")

    # ---------- Flask-Login ----------
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id: str):
        # Evita deprecations de .query.get y reduce problemas de conexión
        try:
            return db.session.get(User, int(user_id))
        except Exception:
            # Si la conexión se reseteó, devuelve None para forzar relogueo limpio
            return None

    @login_manager.unauthorized_handler
    def unauthorized():
        return redirect(url_for("auth.login"))

    # (Opcional) healthcheck simple
    @app.get("/healthz")
    def healthz():
        return {"ok": True}, 200

    return app
