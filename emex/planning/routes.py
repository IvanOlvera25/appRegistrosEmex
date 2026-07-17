# emex/planning/routes.py
from datetime import datetime, date, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort
)
from flask_login import login_required, current_user

from ..extensions import db
from ..decorators import roles_required
from ..models import DailyPlan, PlanItem, User, Unit, Route
from ..timeutils import today_local

# Soporte a Project (si existe)
try:
    from ..models import Project  # type: ignore
except Exception:  # pragma: no cover
    Project = None  # type: ignore

planning_bp = Blueprint(
    "planning", __name__,
    url_prefix="/admin/planning",
    template_folder="../templates/planning",
)

PLAN_TYPES = ["operador", "chofer", "mantenimiento", "compras"]
VALID_ITEM_STATUS = {"pendiente", "cumplido", "no_cumplido"}

# Mapa cargo (job_title) -> tipo de planeación (sugerencia; el admin puede cambiarlo)
_JOB_TO_TYPE = {
    "operador": "operador",
    "chofer": "chofer",
    "mantenimiento": "mantenimiento",
    "mecanico": "mantenimiento",
    "mecánico": "mantenimiento",
    "logistica": "compras",
    "logística": "compras",
    "gestor": "compras",
    "gestor de compras": "compras",
    "compras": "compras",
}


# ------------------------- Helpers -------------------------
def _parse_date(value, default=None):
    """Convierte 'YYYY-MM-DD' a date; si falla, regresa default."""
    if value:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except Exception:
            pass
    return default


def _workers():
    return User.query.filter_by(role="worker").order_by(User.name.asc()).all()


def _units():
    return Unit.query.order_by(Unit.code.asc()).all()


def _projects():
    if not Project:
        return []
    q = db.session.query(Project)
    if hasattr(Project, "active"):
        q = q.filter(Project.active.is_(True))
    return q.order_by(getattr(Project, "name")).all()


def _routes():
    q = db.session.query(Route)
    if hasattr(Route, "active"):
        q = q.filter(Route.active.is_(True))
    return q.order_by(Route.origin.asc()).all()


def _worker_type_map():
    """{user_id: tipo_sugerido} a partir del job_title, para autollenar en el form."""
    out = {}
    for w in _workers():
        jt = (w.job_title or "").strip().lower()
        out[w.id] = _JOB_TO_TYPE.get(jt, "operador")
    return out


def _int_or_none(value):
    try:
        v = int(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _clean_type(value):
    v = (value or "").strip().lower()
    return v if v in PLAN_TYPES else "operador"


# ------------------------- Vistas -------------------------
@planning_bp.get("/", endpoint="index")
@login_required
@roles_required("admin")
def index():
    # Fecha por defecto: mañana
    default_day = today_local() + timedelta(days=1)
    day = _parse_date(request.args.get("date"), default_day)

    worker_id = _int_or_none(request.args.get("worker_id"))
    ptype = request.args.get("type") or ""

    q = DailyPlan.query.filter(DailyPlan.plan_date == day)
    if worker_id:
        q = q.filter(DailyPlan.plan_date == day, DailyPlan.worker_id == worker_id)
    if ptype in PLAN_TYPES:
        q = q.filter(DailyPlan.plan_type == ptype)

    plans = q.order_by(DailyPlan.plan_type.asc(), DailyPlan.worker_name.asc()).all()

    return render_template(
        "planning/index.html",
        plans=plans,
        day=day,
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        today=today_local(),
        workers=_workers(),
        plan_types=PLAN_TYPES,
        sel_worker_id=worker_id,
        sel_type=ptype,
    )


@planning_bp.route("/new", methods=["GET", "POST"], endpoint="new")
@login_required
@roles_required("admin")
def new():
    if request.method == "POST":
        plan_date = _parse_date(request.form.get("plan_date"))
        worker_id = _int_or_none(request.form.get("worker_id"))
        plan_type = _clean_type(request.form.get("plan_type"))
        notes = (request.form.get("notes") or "").strip() or None

        if not plan_date:
            flash("Selecciona una fecha válida para la planeación.", "danger")
            return redirect(url_for("planning.new"))

        worker = db.session.get(User, worker_id) if worker_id else None
        if not worker:
            flash("Selecciona un trabajador del catálogo.", "danger")
            return redirect(url_for("planning.new"))

        # Ítems: campos paralelos item_description[], item_unit_id[], ...
        descriptions = request.form.getlist("item_description[]")
        unit_ids = request.form.getlist("item_unit_id[]")
        project_ids = request.form.getlist("item_project_id[]")
        route_ids = request.form.getlist("item_route_id[]")
        trip_types = request.form.getlist("item_trip_type[]")
        quantities = request.form.getlist("item_quantity[]")

        plan = DailyPlan(
            plan_date=plan_date,
            plan_type=plan_type,
            worker_id=worker.id,
            worker_name=worker.name,
            notes=notes,
            created_by_id=getattr(current_user, "id", None),
        )

        n_items = 0
        for i, desc in enumerate(descriptions):
            desc = (desc or "").strip()
            if not desc:
                continue  # ignora filas vacías
            item = PlanItem(
                description=desc,
                unit_id=_int_or_none(unit_ids[i] if i < len(unit_ids) else None),
                project_id=_int_or_none(project_ids[i] if i < len(project_ids) else None),
                route_id=_int_or_none(route_ids[i] if i < len(route_ids) else None),
                trip_type=((trip_types[i].strip() or None) if i < len(trip_types) else None),
                quantity=((quantities[i].strip() or None) if i < len(quantities) else None),
                status="pendiente",
                is_extra=False,
            )
            plan.items.append(item)
            n_items += 1

        if n_items == 0:
            flash("Agrega al menos una tarea a la planeación.", "danger")
            return redirect(url_for("planning.new"))

        db.session.add(plan)
        db.session.commit()
        flash(f"Planeación creada para {worker.name} ({n_items} tarea(s)).", "success")
        return redirect(url_for("planning.detail", plan_id=plan.id))

    # GET
    default_day = _parse_date(request.args.get("date"), today_local() + timedelta(days=1))
    return render_template(
        "planning/new.html",
        default_day=default_day,
        workers=_workers(),
        units=_units(),
        projects=_projects(),
        routes=_routes(),
        plan_types=PLAN_TYPES,
        worker_type_map=_worker_type_map(),
    )


@planning_bp.get("/<int:plan_id>", endpoint="detail")
@login_required
@roles_required("admin")
def detail(plan_id):
    plan = db.session.get(DailyPlan, plan_id)
    if not plan:
        flash("Planeación no encontrada.", "danger")
        return redirect(url_for("planning.index"))
    return render_template(
        "planning/detail.html",
        plan=plan,
        units=_units(),
        projects=_projects(),
        routes=_routes(),
    )


@planning_bp.post("/<int:plan_id>/item/<int:item_id>/status", endpoint="item_status")
@login_required
@roles_required("admin")
def item_status(plan_id, item_id):
    item = db.session.get(PlanItem, item_id)
    if not item or item.plan_id != plan_id:
        abort(404)

    new_status = (request.form.get("status") or "").strip().lower()
    if new_status not in VALID_ITEM_STATUS:
        flash("Estado no válido.", "danger")
        return redirect(url_for("planning.detail", plan_id=plan_id))

    item.status = new_status
    justification = (request.form.get("justification") or "").strip()
    # La justificación aplica sobre todo a 'no_cumplido', pero se guarda si viene.
    item.justification = justification or None
    db.session.commit()
    flash("Tarea actualizada.", "success")
    return redirect(url_for("planning.detail", plan_id=plan_id))


@planning_bp.post("/<int:plan_id>/add-item", endpoint="add_item")
@login_required
@roles_required("admin")
def add_item(plan_id):
    plan = db.session.get(DailyPlan, plan_id)
    if not plan:
        abort(404)

    desc = (request.form.get("description") or "").strip()
    if not desc:
        flash("La descripción del extra es obligatoria.", "danger")
        return redirect(url_for("planning.detail", plan_id=plan_id))

    item = PlanItem(
        plan_id=plan.id,
        description=desc,
        unit_id=_int_or_none(request.form.get("unit_id")),
        project_id=_int_or_none(request.form.get("project_id")),
        route_id=_int_or_none(request.form.get("route_id")),
        trip_type=(request.form.get("trip_type") or "").strip() or None,
        quantity=(request.form.get("quantity") or "").strip() or None,
        is_extra=True,
        status="cumplido",  # un extra que salió normalmente ya se hizo; el admin puede cambiarlo
    )
    db.session.add(item)
    db.session.commit()
    flash("Extra agregado a la planeación.", "success")
    return redirect(url_for("planning.detail", plan_id=plan_id))


@planning_bp.post("/<int:plan_id>/validate", endpoint="validate")
@login_required
@roles_required("admin")
def validate(plan_id):
    plan = db.session.get(DailyPlan, plan_id)
    if not plan:
        abort(404)
    plan.validated_at = datetime.utcnow()
    plan.validated_by_id = getattr(current_user, "id", None)
    db.session.commit()
    flash("Planeación validada.", "success")
    return redirect(url_for("planning.detail", plan_id=plan_id))


@planning_bp.post("/item/<int:item_id>/delete", endpoint="item_delete")
@login_required
@roles_required("admin")
def item_delete(item_id):
    item = db.session.get(PlanItem, item_id)
    if not item:
        abort(404)
    plan_id = item.plan_id
    db.session.delete(item)
    db.session.commit()
    flash("Tarea eliminada.", "success")
    return redirect(url_for("planning.detail", plan_id=plan_id))


@planning_bp.post("/<int:plan_id>/delete", endpoint="delete")
@login_required
@roles_required("admin")
def delete(plan_id):
    plan = db.session.get(DailyPlan, plan_id)
    if not plan:
        abort(404)
    plan_date = plan.plan_date
    db.session.delete(plan)
    db.session.commit()
    flash("Planeación eliminada.", "success")
    return redirect(url_for("planning.index", date=plan_date.isoformat()))
