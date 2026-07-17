"""
Siembra planeaciones de EJEMPLO para MAÑANA usando los empleados, unidades,
obras y rutas REALES de tu base (la de .env / MySQL).

- Idempotente: si un trabajador ya tiene planeación para esa fecha, la respeta.
- Cada plan lleva una nota que dice que es de ejemplo; puedes editarlo o
  eliminarlo desde Planeación → Abrir / validar → Eliminar planeación.

Uso:
    .venv/bin/python seed_planning_real.py
"""
from datetime import timedelta

from emex import create_app
from emex.extensions import db
from emex.models import User, Unit, Route, DailyPlan, PlanItem
from emex.timeutils import today_local

try:
    from emex.models import Project
except Exception:
    Project = None

NOTE = "Planeación de ejemplo (generada para prueba). Puedes editarla o eliminarla."

app = create_app()

with app.app_context():
    tomorrow = today_local() + timedelta(days=1)

    def first_worker(*job_titles):
        q = User.query.filter(User.role == "worker")
        for jt in job_titles:
            u = q.filter(User.job_title.ilike(f"%{jt}%")).order_by(User.name).first()
            if u:
                return u
        return None

    units = Unit.query.order_by(Unit.code).limit(4).all()
    projects = []
    if Project:
        pq = db.session.query(Project)
        if hasattr(Project, "active"):
            pq = pq.filter(Project.active.is_(True))
        projects = pq.limit(2).all()
    routes = Route.query.limit(2).all()

    def unit_id(i):
        return units[i].id if i < len(units) else None

    def proj_id(i):
        return projects[i].id if i < len(projects) else None

    def route_id(i):
        return routes[i].id if i < len(routes) else None

    # (trabajador, tipo, [items]) — items: dict con description y refs opcionales
    chofer = first_worker("chofer")
    operador = first_worker("operador")
    mant = first_worker("mantenimiento", "mecanic")

    blueprint = []
    if chofer:
        blueprint.append((chofer, "chofer", [
            dict(description="Acarreo de material", unit_id=unit_id(0), route_id=route_id(0),
                 trip_type="acarreo", quantity="4 viajes"),
            dict(description="Traslado a planta", unit_id=unit_id(1), route_id=route_id(1),
                 trip_type="traslado", quantity="2 viajes"),
        ]))
    if operador:
        blueprint.append((operador, "operador", [
            dict(description="Jornada en obra", unit_id=unit_id(2), project_id=proj_id(0),
                 quantity="8 hrs"),
            dict(description="Apoyo en maniobras", project_id=proj_id(1), quantity="3 hrs"),
        ]))
    if mant:
        blueprint.append((mant, "mantenimiento", [
            dict(description="Cambio de aceite y filtros", unit_id=unit_id(0), quantity="1 servicio"),
            dict(description="Revisión de frenos y llantas", unit_id=unit_id(1), quantity="1 revisión"),
        ]))

    created, skipped = [], []
    for worker, ptype, items in blueprint:
        exists = DailyPlan.query.filter_by(worker_id=worker.id, plan_date=tomorrow).first()
        if exists:
            skipped.append(worker.name)
            continue
        plan = DailyPlan(
            plan_date=tomorrow, plan_type=ptype,
            worker_id=worker.id, worker_name=worker.name, notes=NOTE,
        )
        for it in items:
            plan.items.append(PlanItem(status="pendiente", **it))
        db.session.add(plan)
        created.append(f"{worker.name} ({ptype}, {len(items)} tareas)")

    db.session.commit()

    print("\n" + "=" * 60)
    print(f"  PLANEACIONES DE EJEMPLO — fecha: {tomorrow.strftime('%A %d/%m/%Y')}")
    print("=" * 60)
    for c in created:
        print("  + creada:", c)
    for s in skipped:
        print("  = ya tenía plan (respetado):", s)
    if not created and not skipped:
        print("  (no se encontraron trabajadores/catálogos para sembrar)")
    total = DailyPlan.query.filter_by(plan_date=tomorrow).count()
    print("-" * 60)
    print(f"  Total de planeaciones para esa fecha en la BD: {total}")
    print("  Míralas en:  Planeación  (abre por defecto en 'mañana')")
    print("=" * 60 + "\n")
