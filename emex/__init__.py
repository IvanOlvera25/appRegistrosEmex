# emex/__init__.py
import os
import sqlite3
import click
from flask import Flask, redirect, url_for
from dotenv import load_dotenv
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from flask_compress import Compress

# ── Cargar .env ANTES de cualquier import que use os.getenv() ──
_basedir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_basedir, '.env'))

# Extensiones y blueprints (importes ABSOLUTOS)
from emex.extensions import db, login_manager, migrate
from emex.models import User
from emex.auth.routes import auth_bp
from emex.worker.routes import worker_bp
from emex.admin.routes import admin_bp
from emex.api.routes import api_bp
from emex.planning.routes import planning_bp


@event.listens_for(Engine, "connect")
def _sqlite_on_connect(dbapi_connection, connection_record):
    """
    Ajustes por conexión para SQLite. En PythonAnywhere el /home vive en un
    sistema de archivos en red: NO se activa WAL (necesita memoria compartida y
    ahí falla); en su lugar se usa un busy_timeout amplio para tolerar la
    concurrencia entre workers del servidor web.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _sqlite_uri(app):
    """URI SQLite absoluta dentro de instance/ (creando la carpeta si falta)."""
    custom = os.getenv("SQLITE_PATH")
    db_path = os.path.abspath(custom) if custom else os.path.join(app.instance_path, "emex.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return f"sqlite:///{db_path}"


def _resolve_database_uri(app):
    """
    SQLite local es el backend por defecto: la app ya no depende de un MySQL
    externo. Para volver a una base remota hay que pedirlo explícitamente con
    USE_EXTERNAL_DB=1 además de definir DATABASE_URL.
    """
    raw = (os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI") or "").strip()

    if raw.startswith("sqlite"):
        return raw
    if raw and os.getenv("USE_EXTERNAL_DB", "0") == "1":
        return raw

    uri = _sqlite_uri(app)
    if raw:
        app.logger.warning(
            "DATABASE_URL externa ignorada (USE_EXTERNAL_DB != 1). Usando SQLite local: %s",
            uri,
        )
    return uri


def _engine_options(uri):
    """Opciones de pool acordes al motor en uso."""
    if uri.startswith("sqlite"):
        return {
            "pool_pre_ping": True,
            # El servidor web atiende varias peticiones por proceso/hilo.
            "connect_args": {"check_same_thread": False, "timeout": 30},
        }

    # MySQL: evitar "server has gone away" con conexiones ociosas.
    opts = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "280")),
    }
    if os.getenv("DB_POOL_SIZE"):
        opts["pool_size"] = int(os.getenv("DB_POOL_SIZE"))
    if os.getenv("DB_MAX_OVERFLOW"):
        opts["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW"))
    return opts


def _ensure_runtime_schema(app):
    """
    Parche idempotente para despliegues donde no siempre se corre Flask-Migrate.
    Crea el esquema si la base está vacía (caso típico de un SQLite nuevo) y
    agrega columnas compatibles que falten.
    """
    if os.getenv("AUTO_SCHEMA_FIX", "1") != "1":
        return

    with app.app_context():
        try:
            inspector = inspect(db.engine)

            # Base recién creada: levantar todo el esquema de una vez.
            if not inspector.has_table("users"):
                db.create_all()
                app.logger.info("AUTO_SCHEMA_FIX: esquema creado desde cero.")
                inspector = inspect(db.engine)

            if inspector.has_table("operator_logs"):
                columns = {col["name"] for col in inspector.get_columns("operator_logs")}
                if "trip_type" not in columns:
                    db.session.execute(text("ALTER TABLE operator_logs ADD COLUMN trip_type VARCHAR(80) NULL"))
                    db.session.commit()
                    app.logger.info("AUTO_SCHEMA_FIX: columna operator_logs.trip_type creada.")

            # Tablas faltantes (p.ej. daily_plans / plan_items); no toca las existentes.
            missing = [name for name in db.metadata.tables if not inspector.has_table(name)]
            if missing:
                db.create_all()
                app.logger.info("AUTO_SCHEMA_FIX: tablas creadas -> %s", ", ".join(sorted(missing)))
        except Exception as exc:
            db.session.rollback()
            app.logger.warning("AUTO_SCHEMA_FIX no pudo validar/actualizar el esquema: %s", exc)


def _ensure_admin_user(app):
    """
    Si la base no tiene ningún usuario (SQLite recién creado), crea el admin de
    .env para poder entrar. Nunca modifica usuarios existentes.
    """
    if os.getenv("AUTO_SEED_ADMIN", "1") != "1":
        return

    with app.app_context():
        try:
            if db.session.query(User.id).first() is not None:
                return
            admin = User(
                name="Admin EMEX",
                email=os.getenv("ADMIN_EMAIL", "admin@emex.mx"),
                role="admin",
            )
            admin.set_password(os.getenv("ADMIN_PASSWORD", "admin123"))
            db.session.add(admin)
            db.session.commit()
            app.logger.info("AUTO_SEED_ADMIN: usuario admin inicial creado (%s).", admin.email)
        except Exception as exc:
            db.session.rollback()
            app.logger.warning("AUTO_SEED_ADMIN no pudo crear el usuario inicial: %s", exc)


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # ---------- Configuración base ----------
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
    # SQLite local por defecto (sin dependencias de bases externas)
    db_url = _resolve_database_uri(app)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
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

    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = _engine_options(db_url)

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
    app.register_blueprint(planning_bp)

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
        data = [
            ("EXC-001", "QRO-123-A", "Excavadora CAT 320", "excavadora"),
            ("RET-010", "QRO-987-B", "Retro JCB 3CX", "retro"),
        ]

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
        try:
            db.session.execute(text("SELECT 1"))
            db_ok, db_error = True, None
        except Exception as exc:
            db.session.rollback()
            db_ok, db_error = False, str(exc)

        engine_name = db.engine.url.get_backend_name()
        payload = {"ok": db_ok, "db": engine_name}
        if db_error:
            payload["error"] = db_error
        return payload, (200 if db_ok else 503)

    _ensure_runtime_schema(app)
    _ensure_admin_user(app)

    return app
