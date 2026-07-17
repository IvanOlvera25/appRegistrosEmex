"""
Siembra una base SQLite de DEMO para probar el módulo de Planeación en local.
NO toca tu base real (MySQL de PythonAnywhere): usa un archivo SQLite aparte.

Uso:
    .venv/bin/python seed_planning_demo.py

Luego corre la app apuntando a esa misma BD (ver instrucciones que imprime al final).
"""
import os

# --- Forzar SQLite de demo ANTES de importar la app (load_dotenv no sobreescribe) ---
_BASE = os.path.dirname(os.path.abspath(__file__))
_DB = os.path.join(_BASE, "instance", "emex_demo.db")
os.makedirs(os.path.join(_BASE, "instance"), exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["AUTO_SCHEMA_FIX"] = "0"

from datetime import timedelta

from emex import create_app
from emex.extensions import db
from emex.models import User, Unit, Route, DailyPlan, PlanItem
from emex.timeutils import today_local

try:
    from emex.models import Project
except Exception:
    Project = None

# --- Credenciales de demo ---
ADMIN = {"name": "Administrador EMEX", "email": "admin@emex.mx", "password": "Admin2026!"}
WORKERS = [
    {"name": "Juan Pérez",     "job_title": "operador",      "phone": "5214640000001", "password": "Juan2026!"},
    {"name": "Carlos Ramírez", "job_title": "chofer",        "phone": "5214640000002", "password": "Carlos2026!"},
    {"name": "Miguel Santos",  "job_title": "mantenimiento", "phone": "5214640000003", "password": "Miguel2026!"},
]

app = create_app()

with app.app_context():
    # BD de demo limpia
    db.drop_all()
    db.create_all()

    # Admin
    admin = User(name=ADMIN["name"], email=ADMIN["email"], role="admin")
    admin.set_password(ADMIN["password"])
    db.session.add(admin)

    # Trabajadores
    workers = {}
    for w in WORKERS:
        u = User(name=w["name"], phone=w["phone"], job_title=w["job_title"], role="worker")
        u.set_password(w["password"])
        db.session.add(u)
        workers[w["job_title"]] = u

    # Catálogos
    u1 = Unit(code="EXC-001", plate="QRO-123-A", description="Excavadora CAT 320", type="excavadora")
    u2 = Unit(code="CAM-010", plate="QRO-987-B", description="Camión de volteo", type="camion")
    u3 = Unit(code="RET-005", plate="QRO-555-C", description="Retroexcavadora JCB", type="retro")
    db.session.add_all([u1, u2, u3])

    projects = []
    if Project:
        p1 = Project(name="Obra Norte - Nave A", code="OBR-001", active=True)
        p2 = Project(name="Fraccionamiento Sur", code="OBR-002", active=True)
        db.session.add_all([p1, p2])
        projects = [p1, p2]

    r1 = Route(origin="Querétaro", destination="Obra Norte", active=True)
    r2 = Route(origin="Planta", destination="Fraccionamiento Sur", active=True)
    db.session.add_all([r1, r2])

    db.session.flush()  # asignar IDs

    tomorrow = today_local() + timedelta(days=1)

    # --- Plan 1: Operador (Juan) ---
    plan_op = DailyPlan(
        plan_date=tomorrow, plan_type="operador",
        worker_id=workers["operador"].id, worker_name=workers["operador"].name,
        notes="Prioridad: terminar excavación de zapatas.",
        created_by_id=admin.id,
    )
    plan_op.items.append(PlanItem(description="Excavar zapatas eje norte",
                                  unit_id=u1.id, project_id=(projects[0].id if projects else None),
                                  quantity="8 hrs", status="pendiente"))
    plan_op.items.append(PlanItem(description="Nivelar terreno acceso",
                                  unit_id=u3.id, project_id=(projects[0].id if projects else None),
                                  quantity="3 hrs", status="pendiente"))

    # --- Plan 2: Chofer (Carlos) ---
    plan_ch = DailyPlan(
        plan_date=tomorrow, plan_type="chofer",
        worker_id=workers["chofer"].id, worker_name=workers["chofer"].name,
        notes="Cargar temprano, evitar hora pico.",
        created_by_id=admin.id,
    )
    plan_ch.items.append(PlanItem(description="Acarreo de material a Obra Norte",
                                  unit_id=u2.id, route_id=r1.id, trip_type="acarreo",
                                  quantity="4 viajes", status="pendiente"))
    plan_ch.items.append(PlanItem(description="Retiro de escombro Fraccionamiento Sur",
                                  unit_id=u2.id, route_id=r2.id, trip_type="retiro de escombro",
                                  quantity="2 viajes", status="pendiente"))

    # --- Plan 3: Mantenimiento (Miguel) ---
    plan_mt = DailyPlan(
        plan_date=tomorrow, plan_type="mantenimiento",
        worker_id=workers["mantenimiento"].id, worker_name=workers["mantenimiento"].name,
        notes="Revisar niveles antes de arrancar.",
        created_by_id=admin.id,
    )
    plan_mt.items.append(PlanItem(description="Cambio de aceite y filtros",
                                  unit_id=u1.id, quantity="1 servicio", status="pendiente"))
    plan_mt.items.append(PlanItem(description="Revisión de frenos y llantas",
                                  unit_id=u2.id, quantity="1 revisión", status="pendiente"))

    db.session.add_all([plan_op, plan_ch, plan_mt])
    db.session.commit()

    print("\n" + "=" * 60)
    print("  BASE DE DEMO SEMBRADA ✅")
    print("=" * 60)
    print(f"  Archivo: {_DB}")
    print(f"  Planeaciones creadas para: {tomorrow.strftime('%A %d/%m/%Y')}")
    print(f"    · {plan_op.worker_name} (operador)      - {len(plan_op.items)} tareas")
    print(f"    · {plan_ch.worker_name} (chofer)        - {len(plan_ch.items)} tareas")
    print(f"    · {plan_mt.worker_name} (mantenimiento) - {len(plan_mt.items)} tareas")
    print("-" * 60)
    print("  CREDENCIALES")
    print(f"    ADMIN  ->  correo: {ADMIN['email']}   contraseña: {ADMIN['password']}")
    for w in WORKERS:
        print(f"    WORKER ->  nombre: {w['name']:<16}  contraseña: {w['password']}")
    print("=" * 60)
    print("  Para correr la app con esta BD de demo:")
    print(f'    DATABASE_URL="sqlite:///{_DB}" .venv/bin/python run.py')
    print("  Luego abre http://127.0.0.1:5000")
    print("  · Admin: inicia sesión con correo/contraseña.")
    print("  · Trabajador: en login elige 'Empleado', selecciona el nombre y pon su contraseña.")
    print("=" * 60 + "\n")
