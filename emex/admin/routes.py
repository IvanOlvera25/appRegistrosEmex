# emex/admin/routes.py
from types import SimpleNamespace
from datetime import datetime, timedelta, date
import random
from decimal import Decimal

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, and_, or_, case
from sqlalchemy.orm import joinedload

from ..decorators import roles_required
from ..extensions import db
from ..models import OperatorLog, Unit, Route, User, Client, Warning, Accessory, FuelPurchase
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

# (Opcional) Soporte a Project si existe en tu models.py
try:
    from ..models import Project  # type: ignore
except Exception:  # pragma: no cover
    Project = None  # type: ignore

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin")

# ------------------------- Helpers -------------------------
def _ensure_admin():
    if not getattr(current_user, "role", None) == "admin":
        abort(403)

def _kpis():
    """Calcula métricas completas para los KPIs del dashboard."""
    total = db.session.query(func.count(OperatorLog.id)).scalar() or 0
    si_count = (
        db.session.query(func.count(OperatorLog.id))
        .filter(OperatorLog.has_service_incident.is_(True))
        .scalar()
        or 0
    )
    fuel_liters = float(
        db.session.query(func.coalesce(func.sum(OperatorLog.fuel_liters), 0)).scalar()
        or 0
    )
    overtime_hours = float(
        db.session.query(func.coalesce(func.sum(OperatorLog.overtime_hours), 0)).scalar()
        or 0
    )
    time_total = float(
        db.session.query(func.coalesce(func.sum(OperatorLog.time_total), 0)).scalar()
        or 0
    )
    time_productive = float(
        db.session.query(func.coalesce(func.sum(OperatorLog.time_productive), 0)).scalar()
        or 0
    )

    # --- Nuevas métricas ---
    # Viajes (registros con ruta)
    trips_count = int(
        db.session.query(func.count(OperatorLog.id))
        .filter(or_(
            OperatorLog.route_id.isnot(None),
            OperatorLog.route_other_origin.isnot(None),
            OperatorLog.route_other_destination.isnot(None),
        ))
        .scalar() or 0
    )

    # Operadores activos (nombres únicos sin ruta — no chofer ni gestor)
    operators_active = int(
        db.session.query(func.count(func.distinct(OperatorLog.worker_name)))
        .filter(
            OperatorLog.route_id.is_(None),
            OperatorLog.route_other_origin.is_(None),
            or_(OperatorLog.si_subtype.is_(None), OperatorLog.si_subtype != "compras"),
        )
        .scalar() or 0
    )

    # Choferes activos (nombres únicos con ruta)
    drivers_active = int(
        db.session.query(func.count(func.distinct(OperatorLog.worker_name)))
        .filter(or_(
            OperatorLog.route_id.isnot(None),
            OperatorLog.route_other_origin.isnot(None),
        ))
        .scalar() or 0
    )

    # Compras / dispersiones
    purchases_count = int(
        db.session.query(func.count(OperatorLog.id))
        .filter(OperatorLog.si_subtype == "compras")
        .scalar() or 0
    )
    purchases_total = float(
        db.session.query(func.coalesce(func.sum(OperatorLog.si_amount), 0))
        .filter(OperatorLog.si_subtype == "compras")
        .scalar() or 0
    )

    # Promedio diesel por viaje
    avg_diesel = round(fuel_liters / trips_count, 1) if trips_count > 0 else 0.0

    return SimpleNamespace(
        total=total,
        si_count=si_count,
        fuel_liters=fuel_liters,
        overtime_hours=overtime_hours,
        time_total=time_total,
        time_productive=time_productive,
        trips_count=trips_count,
        operators_active=operators_active,
        drivers_active=drivers_active,
        purchases_count=purchases_count,
        purchases_total=purchases_total,
        avg_diesel=avg_diesel,
    )


def _dashboard_charts():
    """Datos para gráficas y rankings del dashboard."""
    today = date.today()

    # --- Registros por día (últimos 14 días) ---
    daily_labels = []
    daily_operators = []
    daily_drivers = []
    daily_gestores = []
    for i in range(14):
        d = today - timedelta(days=13 - i)
        daily_labels.append(d.strftime("%d/%m"))
        day_logs = (
            db.session.query(OperatorLog)
            .filter(func.date(OperatorLog.created_at) == d)
            .all()
        )
        ops = drv = ges = 0
        for log in day_logs:
            if log.si_subtype == "compras":
                ges += 1
            elif log.route_id or log.route_other_origin or log.route_other_destination:
                drv += 1
            else:
                ops += 1
        daily_operators.append(ops)
        daily_drivers.append(drv)
        daily_gestores.append(ges)

    # --- Distribución por rol (total) ---
    all_logs = db.session.query(OperatorLog).all()
    role_ops = role_drv = role_ges = 0
    for log in all_logs:
        if log.si_subtype == "compras":
            role_ges += 1
        elif log.route_id or log.route_other_origin or log.route_other_destination:
            role_drv += 1
        else:
            role_ops += 1

    # --- Top 5 trabajadores ---
    top_workers_q = (
        db.session.query(
            OperatorLog.worker_name,
            func.count(OperatorLog.id).label("cnt"),
        )
        .filter(OperatorLog.worker_name.isnot(None))
        .group_by(OperatorLog.worker_name)
        .order_by(func.count(OperatorLog.id).desc())
        .limit(5)
        .all()
    )
    top_workers = [{"name": w, "count": int(c)} for w, c in top_workers_q]

    # --- Top 5 rutas ---
    top_routes = []
    routes_q = (
        db.session.query(OperatorLog)
        .filter(or_(
            OperatorLog.route_id.isnot(None),
            OperatorLog.route_other_origin.isnot(None),
        ))
        .all()
    )
    route_counter = {}
    for log in routes_q:
        if log.route:
            lbl = log.route.label
        elif log.route_other_origin:
            dest = log.route_other_destination or ""
            lbl = f"{log.route_other_origin} ➝ {dest}" if dest else log.route_other_origin
        else:
            lbl = "Sin ruta"
        route_counter[lbl] = route_counter.get(lbl, 0) + 1
    sorted_routes = sorted(route_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    top_routes = [{"route": r, "count": c} for r, c in sorted_routes]

    return SimpleNamespace(
        daily_labels=daily_labels,
        daily_operators=daily_operators,
        daily_drivers=daily_drivers,
        daily_gestores=daily_gestores,
        role_ops=role_ops,
        role_drv=role_drv,
        role_ges=role_ges,
        top_workers=top_workers,
        top_routes=top_routes,
    )


def _catalogs_for_filters():
    """Catálogos que la plantilla usa en los filtros."""
    workers = [
        w[0]
        for w in (
            db.session.query(OperatorLog.worker_name)
            .filter(OperatorLog.worker_name.isnot(None))
            .distinct()
            .order_by(OperatorLog.worker_name.asc())
            .all()
        )
        if w and w[0]
    ]
    try:
        routes = Route.query.filter_by(active=True).order_by(Route.origin, Route.destination).all()
    except Exception:
        routes = Route.query.order_by(Route.origin, Route.destination).all()
    units = Unit.query.order_by(Unit.code).all()
    projects = []
    if Project:
        try:
            projects = (
                db.session.query(Project)
                .order_by(getattr(Project, "name", "id"))
                .all()
            )
            try:
                projects = [p for p in projects if getattr(p, "active", True)]
            except Exception:
                pass
        except Exception:
            projects = []
    return workers, routes, units, projects

# ------------------------- Dashboard -------------------------
@admin_bp.route("/dashboard")
@login_required
@roles_required("admin")
def dashboard():
    last_ops = (
        OperatorLog.query.order_by(OperatorLog.created_at.desc())
        .limit(200)
        .all()
    )
    stats = _kpis()
    charts = _dashboard_charts()
    workers, routes, units, projects = _catalogs_for_filters()
    filters = SimpleNamespace(start_date=None, end_date=None)
    return render_template(
        "admin/dashboard.html",
        last_ops=last_ops,
        stats=stats,
        charts=charts,
        workers=workers,
        routes=routes,
        units=units,
        projects=projects,
        filters=filters,
    )


# ------------------------- Dispersiones de Diesel -------------------------
@admin_bp.route("/dispersions")
@login_required
@roles_required("admin")
def dispersions():
    _ensure_admin()
    today = date.today()

    # Registros de dispersión (gestor de compras)
    disp_logs = (
        OperatorLog.query
        .filter(OperatorLog.si_subtype == "compras")
        .order_by(OperatorLog.created_at.desc())
        .all()
    )

    # También incluir registros con project_name == "Dispersión de Diesel"
    disp_logs_wa = (
        OperatorLog.query
        .filter(OperatorLog.project_name == "Dispersión de Diesel")
        .order_by(OperatorLog.created_at.desc())
        .all()
    )
    # Merge unique
    seen_ids = {d.id for d in disp_logs}
    for d in disp_logs_wa:
        if d.id not in seen_ids:
            disp_logs.append(d)
            seen_ids.add(d.id)
    disp_logs.sort(key=lambda x: x.created_at, reverse=True)

    total_dispersions = len(disp_logs)
    total_liters = sum(float(d.fuel_liters or 0) for d in disp_logs)

    # Unidades únicas servidas
    unit_ids = set()
    for d in disp_logs:
        if d.main_unit_id:
            unit_ids.add(d.main_unit_id)
    units_served = len(unit_ids)

    avg_per_disp = round(total_liters / total_dispersions, 1) if total_dispersions > 0 else 0

    # Top 5 unidades por litros
    unit_liters = {}
    for d in disp_logs:
        unit_label = d.main_unit.code if d.main_unit else "Sin unidad"
        unit_liters[unit_label] = unit_liters.get(unit_label, 0) + float(d.fuel_liters or 0)
    top_units = sorted(unit_liters.items(), key=lambda x: x[1], reverse=True)[:5]

    # Serie diaria (14 días)
    disp_labels = []
    disp_series = []
    for i in range(14):
        d = today - timedelta(days=13 - i)
        disp_labels.append(d.strftime("%d/%m"))
        day_sum = sum(
            float(log.fuel_liters or 0) for log in disp_logs
            if log.created_at and log.created_at.date() == d
        )
        disp_series.append(round(day_sum, 1))

    return render_template(
        "admin/dispersions.html",
        disp_logs=disp_logs,
        total_dispersions=total_dispersions,
        total_liters=round(total_liters, 1),
        units_served=units_served,
        avg_per_disp=avg_per_disp,
        top_units=top_units,
        disp_labels=disp_labels,
        disp_series=disp_series,
    )


# --- API: eliminar OperatorLog (single y bulk) ---
@admin_bp.delete("/api/logs/<int:log_id>", endpoint="api_logs_delete")
@login_required
@roles_required("admin")
def api_logs_delete(log_id: int):
    _ensure_admin()
    row = db.session.get(OperatorLog, log_id)
    if not row:
        return jsonify(success=False, error="Registro no encontrado."), 404
    try:
        db.session.delete(row)
        db.session.commit()
        return jsonify(success=True, deleted=1)
    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, error="No se pudo eliminar por referencias."), 409
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error="Error inesperado."), 500


@admin_bp.post("/api/logs/bulk-delete", endpoint="api_logs_bulk_delete")
@login_required
@roles_required("admin")
def api_logs_bulk_delete():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids") or []
    try:
        ids = [int(x) for x in ids if str(x).isdigit()]
    except Exception:
        return jsonify(success=False, error="IDs inválidos."), 400

    if not ids:
        return jsonify(success=False, error="No hay IDs que eliminar."), 400

    try:
        # Borrado en lote
        deleted = (
            db.session.query(OperatorLog)
            .filter(OperatorLog.id.in_(ids))
            .delete(synchronize_session=False)
        )
        db.session.commit()
        not_found = [x for x in ids if deleted == 0]  # mejor devolver vacío para simplicidad
        return jsonify(success=True, deleted=deleted, not_found=[])
    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, error="No se pudo eliminar por referencias."), 409
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, error="Error inesperado."), 500

# =================================================================
#                      PROYECTOS / OBRAS
# =================================================================
_PROJECTS_FALLBACK = []
def _next_id():
    return (max([p["id"] for p in _PROJECTS_FALLBACK], default=0) + 1)

@admin_bp.route("/projects", methods=["GET", "POST"], endpoint="projects")
@login_required
@roles_required("admin")
def projects():
    _ensure_admin()

    # Si tienes el modelo Project en BD:
    if Project:
        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            code = (request.form.get("code") or "").strip()
            location = (request.form.get("location") or "").strip()
            active = bool(request.form.get("active"))
            client_id_raw = request.form.get("client_id") or None
            client_id = int(client_id_raw) if client_id_raw and client_id_raw.isdigit() else None

            if not name:
                flash("El nombre de la obra es obligatorio.", "danger")
            else:
                exists = db.session.query(Project).filter_by(name=name).first()
                if exists:
                    flash("Ya existe una obra con ese nombre.", "danger")
                else:
                    p = Project(
                        name=name,
                        code=code,
                        location=location,
                        active=active,
                        client_id=client_id,
                    )
                    db.session.add(p)
                    db.session.commit()
                    flash("Obra registrada correctamente.", "success")
                    return redirect(url_for("admin.projects"))

        projects = db.session.query(Project).order_by(Project.name.asc()).all()
        clients  = db.session.query(Client).order_by(Client.name.asc()).all()
        return render_template("admin/projects.html", projects=projects, clients=clients)

    # Fallback en memoria si NO existe Project (por compatibilidad)
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        code = (request.form.get("code") or "").strip()
        location = (request.form.get("location") or "").strip()
        active = bool(request.form.get("active"))
        if not name:
            flash("El nombre de la obra es obligatorio.", "danger")
        else:
            if any(p["name"].lower() == name.lower() for p in _PROJECTS_FALLBACK):
                flash("Ya existe una obra con ese nombre.", "danger")
            else:
                _PROJECTS_FALLBACK.append(
                    {
                        "id": _next_id(),
                        "name": name,
                        "code": code,
                        "location": location,
                        "active": active,
                    }
                )
                flash("Obra registrada correctamente (memoria).", "success")
                return redirect(url_for("admin.projects"))

    class P: ...
    projects = []
    for p in _PROJECTS_FALLBACK:
        o = P(); o.__dict__.update(p); projects.append(o)

    flash(
        "Estás usando un catálogo de obras en memoria. "
        "Cuando exista el modelo Project en BD, esta sección usará datos reales.",
        "info",
    )
    # En modo memoria no hay clientes reales:
    return render_template("admin/projects.html", projects=projects, clients=[])

@admin_bp.post("/projects/<int:pid>/toggle")
@login_required
def project_toggle(pid: int):
    _ensure_admin()
    if Project:
        obj = db.session.get(Project, pid)
        if not obj:
            flash("Obra no encontrada.", "danger")
            return redirect(url_for("admin.projects"))
        if hasattr(obj, "active"):
            setattr(obj, "active", not bool(getattr(obj, "active")))
            db.session.commit()
            flash("Estado actualizado.", "success")
        else:
            flash("El modelo Project no tiene el campo 'active'.", "danger")
        return redirect(url_for("admin.projects"))

    for p in _PROJECTS_FALLBACK:
        if p["id"] == pid:
            p["active"] = not p.get("active", True)
            flash("Estado actualizado (memoria).", "success")
            break
    else:
        flash("Obra no encontrada.", "danger")
    return redirect(url_for("admin.projects"))

@admin_bp.post("/projects/<int:pid>/delete")
@login_required
def project_delete(pid: int):
    _ensure_admin()
    if Project:
        obj = db.session.get(Project, pid)
        if not obj:
            flash("Obra no encontrada.", "danger")
            return redirect(url_for("admin.projects"))
        db.session.delete(obj)
        db.session.commit()
        flash("Obra eliminada.", "success")
        return redirect(url_for("admin.projects"))

    global _PROJECTS_FALLBACK
    before = len(_PROJECTS_FALLBACK)
    _PROJECTS_FALLBACK = [p for p in _PROJECTS_FALLBACK if p["id"] != pid]
    if len(_PROJECTS_FALLBACK) < before:
        flash("Obra eliminada (memoria).", "success")
    else:
        flash("Obra no encontrada.", "danger")
    return redirect(url_for("admin.projects"))


# =================================================================
#                          UNIDADES (ANÁLISIS) — SIN DUMMY
# =================================================================
from datetime import date, timedelta


@admin_bp.route("/units")
@login_required
@roles_required("admin")
def units():
    _ensure_admin()

    # Catálogo real
    all_units = Unit.query.order_by(Unit.code.asc()).all()

    # Ventana: últimos 30 días
    today = date.today()
    start = today - timedelta(days=30)

    # KPIs (reales)
    liters_month = float(
        db.session.query(func.coalesce(func.sum(OperatorLog.fuel_liters), 0.0))
        .filter(OperatorLog.created_at >= start)
        .scalar() or 0.0
    )
    si_inc_month = int(
        db.session.query(
            func.coalesce(
                func.sum(
                    case((OperatorLog.has_service_incident == True, 1), else_=0)
                ),
                0,
            )
        )
        .filter(OperatorLog.created_at >= start)
        .scalar() or 0
    )
    kpis = SimpleNamespace(
        units=len(all_units),
        liters_month=liters_month,
        diesel_cost_month=liters_month * 28.5,
        si_inc_month=si_inc_month,
    )

    # Top 5 consumo y Top 5 servicios+incidencias (reales)
    # Nota: el filtro de fecha va en el ON del OUTER JOIN para no convertirlo en INNER JOIN
    top_fuel_rows = (
        db.session.query(
            Unit,
            func.coalesce(func.sum(OperatorLog.fuel_liters), 0.0).label("liters"),
        )
        .outerjoin(
            OperatorLog,
            and_(
                OperatorLog.main_unit_id == Unit.id,
                OperatorLog.created_at >= start,
            ),
        )
        .group_by(Unit.id)
        .order_by(func.coalesce(func.sum(OperatorLog.fuel_liters), 0.0).desc())
        .limit(5)
        .all()
    )
    top_siinc_rows = (
        db.session.query(
            Unit,
            func.coalesce(
                func.sum(
                    case((OperatorLog.has_service_incident == True, 1), else_=0)
                ),
                0,
            ).label("count"),
        )
        .outerjoin(
            OperatorLog,
            and_(
                OperatorLog.main_unit_id == Unit.id,
                OperatorLog.created_at >= start,
            ),
        )
        .group_by(Unit.id)
        .order_by(
            func.coalesce(
                func.sum(
                    case((OperatorLog.has_service_incident == True, 1), else_=0)
                ),
                0,
            ).desc()
        )
        .limit(5)
        .all()
    )

    # Adaptar al formato que espera tu plantilla
    top_fuel = [{"unit": u, "liters": float(l)} for (u, l) in top_fuel_rows if u]
    top_siinc = [{"unit": u, "count": int(c)} for (u, c) in top_siinc_rows if u]

    # Tu template acepta este campo aunque no lo use en el listado
    rows_general = []

    return render_template(
        "admin/units.html",
        view="list",
        all_units=all_units,
        kpis=kpis,
        top_fuel=top_fuel,
        top_siinc=top_siinc,
        rows_general=rows_general,
        unit=None,
        fuel_series=[],
        fuel_labels=[],
        detail=None,
        recent_events=[],
    )


@admin_bp.route("/units/<int:unit_id>")
@login_required
@roles_required("admin")
def unit_detail(unit_id: int):
    _ensure_admin()

    all_units = Unit.query.order_by(Unit.code.asc()).all()
    unit = db.session.get(Unit, unit_id)
    if not unit:
        return redirect(url_for("admin.units"))

    period = request.args.get('period', 'week')
    today = date.today()
    start_date = today - timedelta(days=(7 if period == 'week' else 30))

    # Registros reales de esta unidad en el periodo
    records = (
        OperatorLog.query
        .filter(
            or_(
                OperatorLog.main_unit_id == unit_id,
                OperatorLog.fuel_unit_id == unit_id,
                OperatorLog.si_unit_id == unit_id
            ),
            OperatorLog.created_at >= start_date
        )
        .order_by(OperatorLog.created_at.desc())
        .all()
    )

    # Serie diaria (últimos 14 días) para gráfico
    fuel_series, fuel_labels = [], []
    for i in range(14):
        d = today - timedelta(days=13 - i)
        day_sum = float(
            db.session.query(func.coalesce(func.sum(OperatorLog.fuel_liters), 0.0))
            .filter(
                OperatorLog.main_unit_id == unit_id,
                func.date(OperatorLog.created_at) == d
            )
            .scalar() or 0.0
        )
        fuel_series.append(day_sum)
        fuel_labels.append(d.strftime("%m-%d"))

    # Métricas del periodo
    total_fuel = float(sum(r.fuel_liters or 0 for r in records))
    fuel_cost = total_fuel * 28.5
    services_count = sum(1 for r in records if r.has_service_incident and (r.si_kind or "").lower() == "servicio")
    incidents_count = sum(1 for r in records if r.has_service_incident and (r.si_kind or "").lower() == "incidencia")

    # Registros detallados con utilidad
    detailed_records = []
    for r in records:
        fuel_cost_record = r.fuel_cost # Usar propiedad del modelo
        service_cost = float(r.si_amount or 0) if r.has_service_incident else 0.0
        total_costs = fuel_cost_record + service_cost
        sale_amount = float(r.sale_amount or 0) if r.sale_amount else None
        utility = (sale_amount - total_costs) if sale_amount is not None else None

        detailed_records.append({
            'id': r.id,
            'date': r.created_at.strftime('%Y-%m-%d'),
            'employee': r.worker_name or 'Sin asignar',
            'project': r.project.name if getattr(r, "project", None) else (r.project_name or 'Sin proyecto'),
            'route': (f"{r.route.origin}-{r.route.destination}" if r.route else r.route_label or 'Local'),
            'fuel': float(r.fuel_liters or 0),
            'fuel_purchase_id': r.fuel_purchase_id, # Agregar ID de compra
            'has_service': r.has_service_incident and (r.si_kind or "").lower() == "servicio",
            'has_incident': r.has_service_incident and (r.si_kind or "").lower() == "incidencia",
            'service_cost': service_cost,
            'sale_amount': sale_amount,
            'utility': utility
        })

    total_sales = sum(x['sale_amount'] or 0 for x in detailed_records)
    total_costs = sum(x['service_cost'] + (x['fuel'] * 28.5 if not x.get('fuel_purchase_id') else 0) for x in detailed_records) # Ajuste temporal, idealmente sumar fuel_cost_record

    # Recalcular total_costs correctamente usando los valores ya calculados
    total_costs = 0
    for r in records:
        total_costs += r.fuel_cost
        if r.has_service_incident:
            total_costs += float(r.si_amount or 0)
    total_utility = total_sales - total_costs
    pending_records = sum(1 for x in detailed_records if not x['sale_amount'])

    # KPIs “globales” (para cabecera — no dummies)
    kpis = SimpleNamespace(
        units=len(all_units),
        liters_month=float(
            db.session.query(func.coalesce(func.sum(OperatorLog.fuel_liters), 0.0))
            .filter(OperatorLog.created_at >= (today - timedelta(days=30))).scalar() or 0.0
        ),
        diesel_cost_month=0,
        si_inc_month=0,
    )

    # Resumen detalle para el panel derecho
    detail = SimpleNamespace(
        liters_today=fuel_series[-1] if fuel_series else 0,
        liters_week=sum(fuel_series[-7:]) if len(fuel_series) >= 7 else sum(fuel_series),
        liters_month=total_fuel,
        diesel_cost=fuel_cost,
        servicios=services_count,
        incidencias=incidents_count,
        projects=", ".join(list(dict.fromkeys([x['project'] for x in detailed_records]))[:2]),
        operators=", ".join(list(dict.fromkeys([x['employee'] for x in detailed_records]))[:3]),
        total_sales=total_sales,
        total_costs=total_costs,
        total_utility=total_utility,
        margin=((total_utility / total_sales * 100) if total_sales > 0 else 0.0),
        pending_records=pending_records,
        efficiency=((len(detailed_records) - pending_records) / len(detailed_records) * 100 if detailed_records else 0.0),
    )

    # Para la vista detalle no necesitamos “top” si no quieres; los dejamos vacíos
    top_fuel, top_siinc, rows_general = [], [], []

    return render_template(
        "admin/units.html",
        view="detail",
        all_units=all_units,
        kpis=kpis,
        top_fuel=top_fuel,
        top_siinc=top_siinc,
        rows_general=rows_general,
        unit=unit,
        fuel_series=fuel_series,
        fuel_labels=fuel_labels,
        detail=detail,
        recent_events=detailed_records,
        period=period,
    )

# =================================================================
#                      ENDPOINTS AJAX (UNITS)
# =================================================================
@admin_bp.route("/api/units/<int:unit_id>/save-sale", methods=["POST"])
@login_required
@roles_required("admin")
def save_sale(unit_id):
    """Guarda la venta de un registro real y devuelve utilidad recalculada."""
    _ensure_admin()

    data = request.get_json() or {}
    record_id = data.get('record_id')
    sale_amount = data.get('sale_amount')

    try:
        sale_amount = float(sale_amount)
    except Exception:
        return jsonify(success=False, error="Monto de venta inválido."), 400

    rec = db.session.get(OperatorLog, record_id)
    if not rec or rec.main_unit_id != unit_id:
        return jsonify(success=False, error="Registro no encontrado para esta unidad."), 404

    rec.sale_amount = sale_amount
    if hasattr(rec, "sale_registered_by_id"):
        rec.sale_registered_by_id = getattr(current_user, "id", None)
    if hasattr(rec, "sale_registered_at"):
        rec.sale_registered_at = datetime.utcnow()
    db.session.commit()

    fuel_cost = float(rec.fuel_liters or 0) * 28.5
    service_cost = float(rec.si_amount or 0)
    utility = sale_amount - (fuel_cost + service_cost)

    return jsonify(success=True, utility=utility, formatted_utility=f"${utility:,.2f}")


@admin_bp.route("/api/units/<int:unit_id>/period-data", methods=["GET"])
@login_required
@roles_required("admin")
def get_period_data(unit_id):
    """Datos reales del periodo para tarjetas (total fuel, costos, servicios, incidencias)."""
    _ensure_admin()

    period = (request.args.get('period') or 'week').lower()
    today = date.today()
    start = today - timedelta(days=(7 if period == 'week' else 30))

    total_fuel = float(
        db.session.query(func.coalesce(func.sum(OperatorLog.fuel_liters), 0.0))
        .filter(OperatorLog.main_unit_id == unit_id, OperatorLog.created_at >= start)
        .scalar() or 0.0
    )
    fuel_cost = total_fuel * 28.5
    services = int(
        db.session.query(func.count(OperatorLog.id))
        .filter(
            OperatorLog.main_unit_id == unit_id,
            OperatorLog.created_at >= start,
            OperatorLog.has_service_incident.is_(True),
            func.lower(func.coalesce(OperatorLog.si_kind, "")) == "servicio",
        ).scalar() or 0
    )
    incidents = int(
        db.session.query(func.count(OperatorLog.id))
        .filter(
            OperatorLog.main_unit_id == unit_id,
            OperatorLog.created_at >= start,
            OperatorLog.has_service_incident.is_(True),
            func.lower(func.coalesce(OperatorLog.si_kind, "")) == "incidencia",
        ).scalar() or 0
    )

    return jsonify({
        'total_fuel': round(total_fuel, 2),
        'fuel_cost': round(fuel_cost, 2),
        'services': services,
        'incidents': incidents,
    })


# =========================
# API Unidades (CRUD + Accesorios por unidad) — DELETE SIN BLOQUEO
# =========================
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, or_

# (opcional) modelo por-unidad
try:
    from ..models import UnitAccessory  # campos: id, unit_id, name, kind ('driver'|'operator')
except Exception:
    UnitAccessory = None


@admin_bp.post("/api/units", endpoint="api_units_create")
@login_required
@roles_required("admin")
def api_units_create():
    _ensure_admin()
    data = request.get_json() or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify(success=False, error="El código es obligatorio."), 400

    exists = Unit.query.filter_by(code=code).first()
    if exists:
        return jsonify(success=False, error="Ya existe una unidad con ese código."), 409

    u = Unit(
        code=code,
        plate=(data.get("plate") or "").strip() or None,
        description=(data.get("description") or "").strip() or None,
        type=(data.get("type") or "").strip() or None,
        status=(data.get("status") or "activa").strip() or "activa",
    )
    db.session.add(u)
    db.session.commit()
    return jsonify(success=True, unit={
        "id": u.id, "code": u.code, "plate": u.plate, "description": u.description,
        "type": u.type, "status": u.status,
    }), 201


@admin_bp.get("/api/units/<int:unit_id>", endpoint="api_units_get")
@login_required
@roles_required("admin")
def api_units_get(unit_id):
    _ensure_admin()
    u = db.session.get(Unit, unit_id)
    if not u:
        return jsonify(success=False, error="Unidad no encontrada."), 404
    return jsonify(success=True, unit={
        "id": u.id, "code": u.code, "plate": u.plate, "description": u.description,
        "type": u.type, "status": u.status,
    })


@admin_bp.put("/api/units/<int:unit_id>", endpoint="api_units_update")
@login_required
@roles_required("admin")
def api_units_update(unit_id):
    _ensure_admin()
    u = db.session.get(Unit, unit_id)
    if not u:
        return jsonify(success=False, error="Unidad no encontrada."), 404

    data = request.get_json() or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify(success=False, error="El código es obligatorio."), 400

    exists = Unit.query.filter_by(code=code).first()
    if exists and exists.id != u.id:
        return jsonify(success=False, error="Ya existe otra unidad con ese código."), 409

    u.code = code
    u.plate = (data.get("plate") or "").strip() or None
    u.description = (data.get("description") or "").strip() or None
    u.type = (data.get("type") or "").strip() or None
    u.status = (data.get("status") or "activa").strip() or "activa"

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, error="Error de integridad al actualizar."), 400

    return jsonify(success=True, unit={
        "id": u.id, "code": u.code, "plate": u.plate, "description": u.description,
        "type": u.type, "status": u.status,
    })


@admin_bp.delete("/api/units/<int:unit_id>", endpoint="api_units_delete")
@login_required
@roles_required("admin")
def api_units_delete(unit_id):
    """
    Elimina la unidad aunque tenga referencias:
      - Desliga OperatorLog.main_unit_id / fuel_unit_id / si_unit_id
      - Borra UnitAccessory (si existe el modelo)
    Soporta soft=?soft=1 para inactivar.
    """
    _ensure_admin()
    u = db.session.get(Unit, unit_id)
    if not u:
        return jsonify(success=False, error="Unidad no encontrada."), 404

    # Soft delete
    if (request.args.get("soft") or "").lower() in ("1", "true", "yes", "y"):
        u.status = "inactiva"
        db.session.commit()
        return jsonify(success=True, message="Unidad inactivada."), 200

    # Desligar referencias en OperatorLog
    db.session.query(OperatorLog).filter(OperatorLog.main_unit_id == unit_id)\
        .update({OperatorLog.main_unit_id: None}, synchronize_session=False)
    db.session.query(OperatorLog).filter(OperatorLog.fuel_unit_id == unit_id)\
        .update({OperatorLog.fuel_unit_id: None}, synchronize_session=False)
    db.session.query(OperatorLog).filter(OperatorLog.si_unit_id == unit_id)\
        .update({OperatorLog.si_unit_id: None}, synchronize_session=False)

    # Eliminar accesorios por unidad (si aplica)
    if UnitAccessory:
        UnitAccessory.query.filter_by(unit_id=unit_id).delete(synchronize_session=False)

    db.session.flush()
    db.session.delete(u)
    db.session.commit()
    return jsonify(success=True, message="Unidad eliminada definitivamente (referencias desligadas)."), 200



# =========================
# Páginas: crear / editar unidad
# =========================
@admin_bp.get("/units/new", endpoint="units_new")
@login_required
@roles_required("admin")
def units_new():
    _ensure_admin()
    # Renderiza formulario de alta
    return render_template("admin/unit_create.html")


@admin_bp.get("/units/<int:unit_id>/edit", endpoint="units_edit")
@login_required
@roles_required("admin")
def units_edit(unit_id: int):
    _ensure_admin()
    u = db.session.get(Unit, unit_id)
    if not u:
        abort(404)
    # Renderiza formulario de edición
    return render_template("admin/unit_edit.html", unit=u)


# =========================
# API Accesorios por unidad (si usas UnitAccessory o CSV en Unit)
# =========================
def _norm_kind(kind: str):
    k = (kind or "").strip().lower()
    return "driver" if k in ("driver", "chofer", "choferes") else ("operator" if k in ("operator", "operador", "operadores") else None)

def _csv_to_list(csv_text):
    return [x.strip() for x in (csv_text or "").split(",") if x and x.strip()]

def _list_to_csv(items):
    seen, out = set(), []
    for it in items or []:
        key = (it or "").strip()
        if not key: continue
        low = key.lower()
        if low in seen: continue
        seen.add(low); out.append(key)
    return ", ".join(out)

def _acc_json(a):
    if isinstance(a, dict):  # fallback CSV
        return a
    return {"id": a.id, "name": a.name, "kind": a.kind}


@admin_bp.get("/api/units/<int:unit_id>/accessories", endpoint="api_unit_accessories_list")
@login_required
@roles_required("admin")
def api_unit_accessories_list(unit_id: int):
    _ensure_admin()
    u = db.session.get(Unit, unit_id)
    if not u:
        return jsonify(success=False, error="Unidad no encontrada."), 404

    kind = _norm_kind(request.args.get("kind"))
    if UnitAccessory:  # tabla
        q = UnitAccessory.query.filter_by(unit_id=unit_id)
        if kind:
            q = q.filter_by(kind=kind)
            items = [{"id": a.id, "name": a.name, "kind": a.kind} for a in q.order_by(UnitAccessory.name.asc()).all()]
            return jsonify(success=True, items=items)
        else:
            drv = UnitAccessory.query.filter_by(unit_id=unit_id, kind="driver").order_by(UnitAccessory.name.asc()).all()
            opr = UnitAccessory.query.filter_by(unit_id=unit_id, kind="operator").order_by(UnitAccessory.name.asc()).all()
            return jsonify(success=True,
                           driver=[_acc_json(a) for a in drv],
                           operator=[_acc_json(a) for a in opr])
    else:  # CSV en Unit (si existe)
        if not hasattr(u, "driver_accessories") or not hasattr(u, "operator_accessories"):
            return jsonify(success=False, error="La unidad no soporta accesorios (faltan campos o modelo)."), 400
        if kind:
            items = [{"id": i+1, "name": n, "kind": kind} for i, n in enumerate(_csv_to_list(getattr(u, f"{kind}_accessories", "")))]
            return jsonify(success=True, items=items)
        return jsonify(
            success=True,
            driver=[{"id": i+1, "name": n, "kind": "driver"} for i, n in enumerate(_csv_to_list(getattr(u, "driver_accessories", "")))],
            operator=[{"id": i+1, "name": n, "kind": "operator"} for i, n in enumerate(_csv_to_list(getattr(u, "operator_accessories", "")))]
        )


@admin_bp.post("/api/units/<int:unit_id>/accessories", endpoint="api_unit_accessories_create")
@login_required
@roles_required("admin")
def api_unit_accessories_create(unit_id: int):
    _ensure_admin()
    u = db.session.get(Unit, unit_id)
    if not u:
        return jsonify(success=False, error="Unidad no encontrada."), 404

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    kind = _norm_kind(data.get("kind"))
    if not name:
        return jsonify(success=False, error="El nombre del accesorio es obligatorio."), 400
    if not kind:
        return jsonify(success=False, error="Tipo inválido. Usa 'driver' o 'operator'."), 400

    if UnitAccessory:
        dup = UnitAccessory.query.filter(
            UnitAccessory.unit_id == unit_id,
            UnitAccessory.kind == kind,
            func.lower(UnitAccessory.name) == name.lower(),
        ).first()
        if dup:
            return jsonify(success=False, error="Ya existe un accesorio con ese nombre."), 409

        a = UnitAccessory(unit_id=unit_id, name=name, kind=kind)
        db.session.add(a)
        db.session.commit()
        return jsonify(success=True, item=_acc_json(a)), 201
    else:
        if not hasattr(u, "driver_accessories") or not hasattr(u, "operator_accessories"):
            return jsonify(success=False, error="La unidad no soporta accesorios (faltan campos o modelo)."), 400
        field = "driver_accessories" if kind == "driver" else "operator_accessories"
        items = _csv_to_list(getattr(u, field, ""))
        if name.lower() in [x.lower() for x in items]:
            return jsonify(success=False, error="Ya existe un accesorio con ese nombre."), 409
        items.append(name)
        setattr(u, field, _list_to_csv(items))
        db.session.commit()
        return jsonify(success=True, item={"id": len(items), "name": name, "kind": kind}), 201


@admin_bp.put("/api/units/<int:unit_id>/accessories/<int:acc_id>", endpoint="api_unit_accessories_update")
@login_required
@roles_required("admin")
def api_unit_accessories_update(unit_id: int, acc_id: int):
    _ensure_admin()
    u = db.session.get(Unit, unit_id)
    if not u:
        return jsonify(success=False, error="Unidad no encontrada."), 404

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(success=False, error="El nombre es obligatorio."), 400

    if UnitAccessory:
        a = db.session.get(UnitAccessory, acc_id)
        if not a or a.unit_id != unit_id:
            return jsonify(success=False, error="Accesorio no encontrado."), 404
        dup = UnitAccessory.query.filter(
            UnitAccessory.unit_id == unit_id,
            UnitAccessory.kind == a.kind,
            func.lower(UnitAccessory.name) == name.lower(),
            UnitAccessory.id != a.id,
        ).first()
        if dup:
            return jsonify(success=False, error="Ya existe un accesorio con ese nombre."), 409
        a.name = name
        db.session.commit()
        return jsonify(success=True, item=_acc_json(a))
    else:
        kind = _norm_kind(request.args.get("kind"))
        if not kind:
            return jsonify(success=False, error="Especifica ?kind=driver|operator"), 400
        field = "driver_accessories" if kind == "driver" else "operator_accessories"
        items = _csv_to_list(getattr(u, field, ""))
        idx = acc_id - 1
        if idx < 0 or idx >= len(items):
            return jsonify(success=False, error="Accesorio no encontrado."), 404
        if name.lower() in [x.lower() for i, x in enumerate(items) if i != idx]:
            return jsonify(success=False, error="Ya existe un accesorio con ese nombre."), 409
        items[idx] = name
        setattr(u, field, _list_to_csv(items))
        db.session.commit()
        return jsonify(success=True, item={"id": acc_id, "name": name, "kind": kind})


@admin_bp.delete("/api/units/<int:unit_id>/accessories/<int:acc_id>", endpoint="api_unit_accessories_delete")
@login_required
@roles_required("admin")
def api_unit_accessories_delete(unit_id: int, acc_id: int):
    _ensure_admin()
    u = db.session.get(Unit, unit_id)
    if not u:
        return jsonify(success=False, error="Unidad no encontrada."), 404

    if UnitAccessory:
        a = db.session.get(UnitAccessory, acc_id)
        if not a or a.unit_id != unit_id:
            return jsonify(success=False, error="Accesorio no encontrado."), 404
        db.session.delete(a)
        db.session.commit()
        return jsonify(success=True, message="Accesorio eliminado.")
    else:
        kind = _norm_kind(request.args.get("kind"))
        if not kind:
            return jsonify(success=False, error="Especifica ?kind=driver|operator"), 400
        field = "driver_accessories" if kind == "driver" else "operator_accessories"
        items = _csv_to_list(getattr(u, field, ""))
        idx = acc_id - 1
        if idx < 0 or idx >= len(items):
            return jsonify(success=False, error="Accesorio no encontrado."), 404
        items.pop(idx)
        setattr(u, field, _list_to_csv(items))
        db.session.commit()
        return jsonify(success=True, message="Accesorio eliminado.")


# =========================
# Helpers de periodo
# =========================
from datetime import datetime, timedelta, date

def _parse_period():
    """Lee parámetros ?period=week|month|quarter|custom&start=YYYY-MM-DD&end=YYYY-MM-DD
       y devuelve (start_date, end_date_exclusive)"""
    period = (request.args.get("period") or "month").lower()
    today = date.today()
    if period == "week":
        start = today - timedelta(days=6)
    elif period == "quarter":
        start = today - timedelta(days=89)
    elif period == "custom":
        try:
            start = datetime.strptime(request.args.get("start"), "%Y-%m-%d").date()
            end = datetime.strptime(request.args.get("end"), "%Y-%m-%d").date()
            return start, (end + timedelta(days=1))
        except Exception:
            start = today - timedelta(days=29)
    else:  # month (30 días)
        start = today - timedelta(days=29)
    return start, (today + timedelta(days=1))

def _employee_aggregates(start_date, end_date):
    """Agrega métricas por empleado en el rango."""
    q = (
        db.session.query(
            OperatorLog.worker_id.label("id"),
            OperatorLog.worker_name.label("name"),
            func.count(OperatorLog.id).label("logs"),
            func.coalesce(func.sum(OperatorLog.time_total), 0).label("hours"),
            func.coalesce(func.sum(OperatorLog.time_productive), 0).label("prod_hours"),
            func.coalesce(func.sum(OperatorLog.overtime_hours), 0).label("overtime"),
            func.coalesce(func.sum(case((OperatorLog.has_service_incident == True, 1), else_=0)), 0).label("incidents"),
            func.coalesce(func.sum(OperatorLog.fuel_liters), 0).label("fuel"),
            func.coalesce(func.sum(OperatorLog.sale_amount), 0).label("sales"),
            func.coalesce(func.sum(OperatorLog.si_amount), 0).label("service_cost"),
        )
        .filter(OperatorLog.created_at >= start_date, OperatorLog.created_at < end_date)
        .group_by(OperatorLog.worker_id, OperatorLog.worker_name)
    )

    rows = []
    for r in q.all():
        hours = float(r.hours or 0)
        prod = float(r.prod_hours or 0)
        fuel = float(r.fuel or 0)
        sales = float(r.sales or 0)
        scost = float(r.service_cost or 0)
        utility = sales - (fuel * 28.5 + scost)
        perf = (prod / hours * 100) if hours > 0 else 0.0
        rows.append(
            {
                "id": r.id,
                "name": r.name or "Sin nombre",
                "logs": int(r.logs or 0),
                "hours": hours,
                "prod_hours": prod,
                "performance": perf,
                "overtime": float(r.overtime or 0),
                "incidents": int(r.incidents or 0),
                "fuel": fuel,
                "sales": sales,
                "service_cost": scost,
                "utility": utility,
            }
        )
    return rows

# =========================
# Empleados: Dashboard general
# =========================
@admin_bp.get("/employees", endpoint="employees")
@login_required
@roles_required("admin")
def employees():
    _ensure_admin()
    start, end = _parse_period()
    agg = _employee_aggregates(start, end)

    # KPIs globales
    total_workers = len(agg)
    total_logs = sum(a["logs"] for a in agg)
    total_hours = sum(a["hours"] for a in agg)
    total_prod = sum(a["prod_hours"] for a in agg)
    total_ot = sum(a["overtime"] for a in agg)
    total_sales = sum(a["sales"] for a in agg)
    total_costs = sum((a["fuel"] * 28.5 + a["service_cost"]) for a in agg)
    total_utility = total_sales - total_costs
    avg_perf = (total_prod / total_hours * 100) if total_hours > 0 else 0.0

    # Rankings
    top_perf = sorted([a for a in agg if a["hours"] >= 5], key=lambda x: x["performance"], reverse=True)[:5]
    top_ot = sorted(agg, key=lambda x: x["overtime"], reverse=True)[:5]
    low_ot = sorted([a for a in agg if a["overtime"] > 0], key=lambda x: x["overtime"])[:5]
    top_sales = sorted(agg, key=lambda x: x["sales"], reverse=True)[:5]
    top_incidents = sorted(agg, key=lambda x: x["incidents"], reverse=True)[:5]

    kpis = SimpleNamespace(
        workers=total_workers,
        logs=total_logs,
        hours=total_hours,
        prod=total_prod,
        avg_perf=avg_perf,
        overtime=total_ot,
        sales=total_sales,
        utility=total_utility,
    )

    # Para el listado, orden por utilidad desc
    table_rows = sorted(agg, key=lambda x: x["utility"], reverse=True)

    return render_template(
        "admin/employees.html",
        kpis=kpis,
        table_rows=table_rows,
        start=start,
        end=(end - timedelta(days=1)),
        top_perf=top_perf,
        top_ot=top_ot,
        low_ot=low_ot,
        top_sales=top_sales,
        top_incidents=top_incidents,
        period=(request.args.get("period") or "month"),
    )

# =========================
# Empleado: Detalle individual
# =========================
@admin_bp.get("/employees/<int:user_id>", endpoint="employee_detail")
@login_required
@roles_required("admin")
def employee_detail(user_id: int):
    _ensure_admin()
    start, end = _parse_period()

    u = db.session.get(User, user_id)
    if not u:
        flash("Empleado no encontrado.", "danger")
        return redirect(url_for("admin.employees"))

    # registros del empleado en el periodo
    logs = (
        OperatorLog.query
        .filter(
            OperatorLog.worker_id == user_id,
            OperatorLog.created_at >= start,
            OperatorLog.created_at < end,
        )
        .order_by(OperatorLog.created_at.desc())
        .limit(300)
        .all()
    )

    hours = sum(float(l.time_total or 0) for l in logs)
    prod = sum(float(l.time_productive or 0) for l in logs)
    overtime = sum(float(l.overtime_hours or 0) for l in logs)
    incidents = sum(1 for l in logs if l.has_service_incident)
    fuel = sum(float(l.fuel_liters or 0) for l in logs)
    sales = sum(float(l.sale_amount or 0) for l in logs)
    scost = sum(float(l.si_amount or 0) for l in logs)
    costs = fuel * 28.5 + scost
    utility = sales - costs
    perf = (prod / hours * 100) if hours > 0 else 0.0

    # Serie diaria
    series = (
        db.session.query(
            func.date(OperatorLog.created_at).label("d"),
            func.coalesce(func.sum(OperatorLog.time_productive), 0).label("prod"),
            func.coalesce(func.sum(OperatorLog.overtime_hours), 0).label("ot"),
        )
        .filter(
            OperatorLog.worker_id == user_id,
            OperatorLog.created_at >= start,
            OperatorLog.created_at < end,
        )
        .group_by(func.date(OperatorLog.created_at))
        .order_by(func.date(OperatorLog.created_at))
        .all()
    )
    labels = [str(s.d) for s in series]
    prod_data = [float(s.prod or 0) for s in series]
    ot_data = [float(s.ot or 0) for s in series]

    detail = SimpleNamespace(
        name=u.name, email=u.email, role=u.role,
        hours=hours, prod=prod, perf=perf, overtime=overtime, incidents=incidents,
        fuel=fuel, sales=sales, costs=costs, utility=utility,
    )

    # tabla simple de últimos eventos
    last_rows = []
    for l in logs[:30]:
        last_rows.append({
            "date": l.created_at.strftime("%Y-%m-%d"),
            "project": (l.project.name if l.project else (l.project_name or "—")),
            "route": (l.route.origin + "–" + l.route.destination) if l.route else "—",
            "hours": float(l.time_total or 0),
            "prod": float(l.time_productive or 0),
            "ot": float(l.overtime_hours or 0),
            "fuel": float(l.fuel_liters or 0),
            "service": float(l.si_amount or 0),
            "sale": float(l.sale_amount or 0) if l.sale_amount else 0.0,
        })

    return render_template(
        "admin/employee_detail.html",
        user=u,
        detail=detail,
        labels=labels,
        prod_data=prod_data,
        ot_data=ot_data,
        last_rows=last_rows,
        start=start,
        end=(end - timedelta(days=1)),
        period=(request.args.get("period") or "month"),
    )

# =========================
# API: series generales por periodo (para dashboard)
# =========================
@admin_bp.get("/api/employees/summary", endpoint="api_employees_summary")
@login_required
@roles_required("admin")
def api_employees_summary():
    _ensure_admin()
    start, end = _parse_period()
    series = (
        db.session.query(
            func.date(OperatorLog.created_at).label("d"),
            func.coalesce(func.sum(OperatorLog.time_productive), 0).label("prod"),
            func.coalesce(func.sum(OperatorLog.overtime_hours), 0).label("ot"),
            func.coalesce(func.sum(case((OperatorLog.has_service_incident == True, 1), else_=0)), 0).label("inc"),
        )
        .filter(OperatorLog.created_at >= start, OperatorLog.created_at < end)
        .group_by(func.date(OperatorLog.created_at))
        .order_by(func.date(OperatorLog.created_at))
        .all()
    )
    return jsonify({
        "labels": [str(s.d) for s in series],
        "prod": [float(s.prod or 0) for s in series],
        "ot": [float(s.ot or 0) for s in series],
        "inc": [int(s.inc or 0) for s in series],
    })

@admin_bp.get("/employees/catalog", endpoint="employees_catalog")
@login_required
@roles_required("admin")
def employees_catalog():
    _ensure_admin()
    q = (request.args.get("q") or "").strip().lower()
    users = (
        db.session.query(User)
        .order_by(User.name.asc())
        .all()
    )
    if q:
        users = [u for u in users if q in (u.name or "").lower() or q in (u.email or "").lower() or q in (u.job_title or "").lower()]
    return render_template("admin/employees_catalog.html", users=users, q=q)


@admin_bp.get("/employees/new", endpoint="employees_new")
@login_required
@roles_required("admin")
def employees_new():
    _ensure_admin()
    return render_template("admin/employee_create.html")


@admin_bp.get("/employees/<int:user_id>/edit", endpoint="employees_edit")
@login_required
@roles_required("admin")
def employees_edit(user_id: int):
    _ensure_admin()
    u = db.session.get(User, user_id)
    if not u:
        flash("Empleado no encontrado.", "danger")
        return redirect(url_for("admin.employees_catalog"))
    return render_template("admin/employee_edit.html", emp=u)


# =========================
# API Empleados (CRUD JSON)
# =========================
# CREATE
@admin_bp.post("/api/employees", endpoint="api_employees_create")
@login_required
@roles_required("admin")
def api_employees_create():
    _ensure_admin()
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    # email puede venir vacío
    email = (data.get("email") or "").strip().lower()
    job_title = (data.get("job_title") or "").strip()

    if not name:
        return jsonify(success=False, error="El nombre es obligatorio."), 400

    if email:
        if db.session.query(User).filter_by(email=email).first():
            return jsonify(success=False, error="Ya existe un usuario con ese correo."), 409

    import secrets
    temp_pw = "Emex-" + secrets.token_urlsafe(10)
    u = User(name=name, email=(email or None), job_title=(job_title or None), role="worker")
    u.set_password(temp_pw)
    db.session.add(u)
    db.session.commit()
    return jsonify(success=True, user={"id": u.id, "name": u.name, "email": u.email, "job_title": u.job_title})

@admin_bp.get("/api/employees/<int:user_id>", endpoint="api_employees_get")
@login_required
@roles_required("admin")
def api_employees_get(user_id: int):
    _ensure_admin()
    u = db.session.get(User, user_id)
    if not u:
        return jsonify(success=False, error="Empleado no encontrado."), 404
    return jsonify(success=True, user={"id": u.id, "name": u.name, "email": u.email, "job_title": u.job_title})

# UPDATE
@admin_bp.put("/api/employees/<int:user_id>", endpoint="api_employees_update")
@login_required
@roles_required("admin")
def api_employees_update(user_id: int):
    _ensure_admin()
    u = db.session.get(User, user_id)
    if not u:
        return jsonify(success=False, error="Empleado no encontrado."), 404

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    job_title = (data.get("job_title") or "").strip()

    if not name:
        return jsonify(success=False, error="El nombre es obligatorio."), 400

    if email:
        other = db.session.query(User).filter(User.email == email, User.id != u.id).first()
        if other:
            return jsonify(success=False, error="Ese correo ya está en uso por otro usuario."), 409

    u.name = name
    u.email = (email or None)
    u.job_title = (job_title or None)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, error="Error de integridad."), 400

    return jsonify(success=True, user={"id": u.id, "name": u.name, "email": u.email, "job_title": u.job_title})


@admin_bp.delete("/api/employees/<int:user_id>", endpoint="api_employees_delete")
@login_required
@roles_required("admin")
def api_employees_delete(user_id: int):
    _ensure_admin()
    u = db.session.get(User, user_id)
    if not u:
        return jsonify(success=False, error="Empleado no encontrado."), 404

    if u.id == current_user.id:
        return jsonify(success=False, error="No puedes eliminar tu propia cuenta."), 400
    if u.role == "admin":
        return jsonify(success=False, error="No se permite eliminar usuarios administradores."), 400

    # ¿Tiene registros en OperatorLog?
    refs = db.session.query(func.count(OperatorLog.id)).filter(OperatorLog.worker_id == user_id).scalar() or 0
    if refs > 0:
        return jsonify(success=False, code="REFERENCED",
                       message=f"No se puede eliminar: tiene {refs} bitácoras asociadas."), 409

    db.session.delete(u)
    db.session.commit()
    return jsonify(success=True, message="Empleado eliminado.")

# =================================================================
#                          CLIENTES (CRUD)
# =================================================================

@admin_bp.route("/clients", methods=["GET", "POST"], endpoint="clients")
@login_required
@roles_required("admin")
def clients():
    _ensure_admin()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        tax_id = (request.form.get("tax_id") or "").strip()
        contact_name = (request.form.get("contact_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        if not name:
            flash("El nombre del cliente es obligatorio.", "danger")
        else:
            exists = db.session.query(Client).filter(func.lower(Client.name) == name.lower()).first()
            if exists:
                flash("Ya existe un cliente con ese nombre.", "danger")
            else:
                c = Client(
                    name=name,
                    tax_id=(tax_id or None),
                    contact_name=(contact_name or None),
                    email=(email or None),
                    phone=(phone or None),
                    notes=(notes or None),
                )
                db.session.add(c)
                db.session.commit()
                flash("Cliente registrado correctamente.", "success")
                return redirect(url_for("admin.clients"))

    q = (request.args.get("q") or "").strip().lower()
    clients = db.session.query(Client).order_by(Client.name.asc()).all()
    if q:
        def _has(s):
            return q in (s or "").lower()
        clients = [
            c for c in clients
            if _has(c.name) or _has(c.tax_id) or _has(c.contact_name) or _has(c.email) or _has(c.phone)
        ]
    # Para mostrar # de proyectos ligados
    proj_counts = {}
    if Project:
        rows = (
            db.session.query(Project.client_id, func.count(Project.id))
            .group_by(Project.client_id).all()
        )
        proj_counts = {cid: cnt for cid, cnt in rows if cid}

    return render_template("admin/clients.html", clients=clients, proj_counts=proj_counts, q=q)


@admin_bp.get("/clients/<int:cid>/edit", endpoint="clients_edit")
@login_required
@roles_required("admin")
def clients_edit(cid: int):
    _ensure_admin()
    c = db.session.get(Client, cid)
    if not c:
        flash("Cliente no encontrado.", "danger")
        return redirect(url_for("admin.clients"))
    return render_template("admin/client_edit.html", client=c)


@admin_bp.post("/clients/<int:cid>/edit", endpoint="clients_update_form")
@login_required
@roles_required("admin")
def clients_update_form(cid: int):
    _ensure_admin()
    c = db.session.get(Client, cid)
    if not c:
        flash("Cliente no encontrado.", "danger")
        return redirect(url_for("admin.clients"))

    name = (request.form.get("name") or "").strip()
    tax_id = (request.form.get("tax_id") or "").strip()
    contact_name = (request.form.get("contact_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    if not name:
        flash("El nombre del cliente es obligatorio.", "danger")
        return redirect(url_for("admin.clients_edit", cid=cid))

    # Evitar duplicado de nombre
    other = (
        db.session.query(Client)
        .filter(func.lower(Client.name) == name.lower(), Client.id != cid)
        .first()
    )
    if other:
        flash("Ya existe otro cliente con ese nombre.", "danger")
        return redirect(url_for("admin.clients_edit", cid=cid))

    c.name = name
    c.tax_id = (tax_id or None)
    c.contact_name = (contact_name or None)
    c.email = (email or None)
    c.phone = (phone or None)
    c.notes = (notes or None)
    try:
        db.session.commit()
        flash("Cliente actualizado.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Error de integridad al actualizar.", "danger")

    return redirect(url_for("admin.clients"))


@admin_bp.post("/clients/<int:cid>/delete", endpoint="clients_delete")
@login_required
@roles_required("admin")
def clients_delete(cid: int):
    _ensure_admin()
    c = db.session.get(Client, cid)
    if not c:
        flash("Cliente no encontrado.", "danger")
        return redirect(url_for("admin.clients"))

    # Verificar referencias en Project
    if Project:
        ref_count = (
            db.session.query(func.count(Project.id))
            .filter(Project.client_id == cid)
            .scalar()
            or 0
        )
        detach = (request.form.get("detach") or "").lower() in ("1", "true", "yes", "y", "on")
        if ref_count > 0 and not detach:
            flash(
                f"No se puede eliminar: el cliente tiene {ref_count} proyecto(s) asociado(s). "
                f"Selecciona 'Desligar proyectos' para continuar.",
                "warning",
            )
            return redirect(url_for("admin.clients"))

        if ref_count > 0 and detach:
            # Desliga proyectos (deja client_id en NULL)
            db.session.query(Project).filter(Project.client_id == cid).update({Project.client_id: None})
            db.session.commit()

    db.session.delete(c)
    db.session.commit()
    flash("Cliente eliminado.", "success")
    return redirect(url_for("admin.clients"))

# =========================
# API Clientes (JSON)
# =========================

@admin_bp.post("/api/clients", endpoint="api_clients_create")
@login_required
@roles_required("admin")
def api_clients_create():
    _ensure_admin()
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(success=False, error="El nombre es obligatorio."), 400

    exists = db.session.query(Client).filter(func.lower(Client.name) == name.lower()).first()
    if exists:
        return jsonify(success=False, error="Ya existe un cliente con ese nombre."), 409

    c = Client(
        name=name,
        tax_id=(data.get("tax_id") or None),
        contact_name=(data.get("contact_name") or None),
        email=(data.get("email") or None),
        phone=(data.get("phone") or None),
        notes=(data.get("notes") or None),
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(success=True, client={
        "id": c.id, "name": c.name, "tax_id": c.tax_id, "contact_name": c.contact_name,
        "email": c.email, "phone": c.phone, "notes": c.notes
    }), 201


@admin_bp.get("/api/clients/<int:cid>", endpoint="api_clients_get")
@login_required
@roles_required("admin")
def api_clients_get(cid: int):
    _ensure_admin()
    c = db.session.get(Client, cid)
    if not c:
        return jsonify(success=False, error="Cliente no encontrado."), 404
    return jsonify(success=True, client={
        "id": c.id, "name": c.name, "tax_id": c.tax_id, "contact_name": c.contact_name,
        "email": c.email, "phone": c.phone, "notes": c.notes
    })


@admin_bp.put("/api/clients/<int:cid>", endpoint="api_clients_update")
@login_required
@roles_required("admin")
def api_clients_update(cid: int):
    _ensure_admin()
    c = db.session.get(Client, cid)
    if not c:
        return jsonify(success=False, error="Cliente no encontrado."), 404

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(success=False, error="El nombre es obligatorio."), 400

    # Evitar duplicado de nombre
    other = (
        db.session.query(Client)
        .filter(func.lower(Client.name) == name.lower(), Client.id != cid)
        .first()
    )
    if other:
        return jsonify(success=False, error="Ya existe otro cliente con ese nombre."), 409

    c.name = name
    c.tax_id = (data.get("tax_id") or None)
    c.contact_name = (data.get("contact_name") or None)
    c.email = (data.get("email") or None)
    c.phone = (data.get("phone") or None)
    c.notes = (data.get("notes") or None)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(success=False, error="Error de integridad."), 400

    return jsonify(success=True, client={
        "id": c.id, "name": c.name, "tax_id": c.tax_id, "contact_name": c.contact_name,
        "email": c.email, "phone": c.phone, "notes": c.notes
    })


@admin_bp.delete("/api/clients/<int:cid>", endpoint="api_clients_delete")
@login_required
@roles_required("admin")
def api_clients_delete(cid: int):
    _ensure_admin()
    c = db.session.get(Client, cid)
    if not c:
        return jsonify(success=False, error="Cliente no encontrado."), 404

    if Project:
        ref_count = (
            db.session.query(func.count(Project.id))
            .filter(Project.client_id == cid)
            .scalar()
            or 0
        )
        detach = (request.args.get("detach") or "").lower() in ("1", "true", "yes", "y")
        if ref_count > 0 and not detach:
            return jsonify(
                success=False,
                code="REFERENCED",
                message=f"No se puede eliminar: tiene {ref_count} proyecto(s) ligados. "
                        f"Usa ?detach=1 para desligarlos y eliminar.",
            ), 409

        if ref_count > 0 and detach:
            db.session.query(Project).filter(Project.client_id == cid).update({Project.client_id: None})
            db.session.commit()

    db.session.delete(c)
    db.session.commit()
    return jsonify(success=True, message="Cliente eliminado.")

# --- ADICIÓN DE RUTAS (coloca cerca de otras páginas admin) ---
@admin_bp.get("/warnings", endpoint="warnings")
@login_required
@roles_required("admin")
def warnings_page():
    _ensure_admin()
    if not Warning:
        flash("El modelo Warning no está disponible.", "danger")
        return redirect(url_for("admin.dashboard"))

    level = (request.args.get("level") or "").lower().strip()     # bajo|medio|alto|vacío
    qtxt  = (request.args.get("q") or "").strip()

    q = (
        db.session.query(Warning)
        .options(
            joinedload(Warning.project),
            joinedload(Warning.unit),
            joinedload(Warning.worker_user),
        )
        .order_by(Warning.created_at.desc())
    )
    if level in ("bajo", "medio", "alto"):
        q = q.filter(Warning.level == level)
    if qtxt:
        like = f"%{qtxt}%"
        q = q.filter(
            or_(
                Warning.description.ilike(like),
                Warning.worker_name.ilike(like),
            )
        )

    warnings = q.limit(1000).all()

    # KPIs rápidos por nivel (para chips en UI)
    counts = dict(
        db.session.query(Warning.level, func.count(Warning.id)).group_by(Warning.level).all()
    )
    kpis = {
        "total": db.session.query(func.count(Warning.id)).scalar() or 0,
        "bajo": counts.get("bajo", 0),
        "medio": counts.get("medio", 0),
        "alto": counts.get("alto", 0),
    }

    return render_template("admin/warnings.html", warnings=warnings, level=level, q=qtxt, kpis=kpis)
@admin_bp.get("/warnings/<int:warning_id>", endpoint="warning_detail")
@login_required
@roles_required("admin")
def warning_detail(warning_id: int):
    _ensure_admin()
    if not Warning:
        flash("El modelo Warning no está disponible.", "danger")
        return redirect(url_for("admin.warnings"))

    w = db.session.get(Warning, warning_id)
    if not w:
        flash("Advertencia no encontrada.", "warning")
        return redirect(url_for("admin.warnings"))

    # Reusa la misma plantilla con foco en un item (opcional)
    return render_template("admin/warnings.html", warnings=[w], focus_id=w.id, level=None)

# =================================================================
#                     API Accesorios (catálogo)
# =================================================================

@admin_bp.get("/api/accessories", endpoint="api_accessories_list")
@login_required
@roles_required("admin")
def api_accessories_list():
    _ensure_admin()
    if not Accessory:
        return jsonify(ok=False, error="Modelo Accessory no disponible."), 500

    kind = (request.args.get("kind") or "").strip().lower()
    q = db.session.query(Accessory).filter(Accessory.active.is_(True))
    if kind in ("operator", "driver"):
        q = q.filter(Accessory.kind == kind)
    q = q.order_by(Accessory.kind.asc(), Accessory.name.asc())
    items = [{"id": a.id, "kind": a.kind, "name": a.name, "active": a.active} for a in q.all()]
    return jsonify(ok=True, items=items)


@admin_bp.post("/api/accessories", endpoint="api_accessories_create")
@login_required
@roles_required("admin")
def api_accessories_create():
    _ensure_admin()
    if not Accessory:
        return jsonify(ok=False, error="Modelo Accessory no disponible."), 500

    data = request.get_json() or {}
    kind = (data.get("kind") or "").strip().lower()
    name = (data.get("name") or "").strip()

    if kind not in ("operator", "driver"):
        return jsonify(ok=False, error="kind inválido (usa 'operator' o 'driver')."), 400
    if not name:
        return jsonify(ok=False, error="El nombre es obligatorio."), 400
    if len(name) > 120:
        return jsonify(ok=False, error="El nombre es demasiado largo (máx. 120)."), 400

    # validar duplicados (mismo kind + name)
    exists = (
        db.session.query(Accessory)
        .filter(Accessory.kind == kind, func.lower(Accessory.name) == name.lower())
        .first()
    )
    if exists:
        return jsonify(ok=False, error="Ya existe un accesorio con ese nombre en ese catálogo."), 409

    a = Accessory(kind=kind, name=name, active=True)
    db.session.add(a)
    db.session.commit()
    return jsonify(ok=True, id=a.id, item={"id": a.id, "kind": a.kind, "name": a.name, "active": a.active}), 201


@admin_bp.put("/api/accessories/<int:acc_id>", endpoint="api_accessories_update")
@login_required
@roles_required("admin")
def api_accessories_update(acc_id: int):
    _ensure_admin()
    a = db.session.get(Accessory, acc_id)
    if not a:
        return jsonify(ok=False, error="Accesorio no encontrado."), 404

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, error="El nombre es obligatorio."), 400
    if len(name) > 120:
        return jsonify(ok=False, error="El nombre es demasiado largo (máx. 120)."), 400

    # evitar duplicado dentro del mismo kind
    dup = (
        db.session.query(Accessory)
        .filter(
            Accessory.kind == a.kind,
            func.lower(Accessory.name) == name.lower(),
            Accessory.id != a.id,
        )
        .first()
    )
    if dup:
        return jsonify(ok=False, error="Ya existe otro accesorio con ese nombre en ese catálogo."), 409

    a.name = name
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(ok=False, error="Error de integridad al actualizar."), 400

    return jsonify(ok=True)


@admin_bp.delete("/api/accessories/<int:acc_id>", endpoint="api_accessories_delete")
@login_required
@roles_required("admin")
def api_accessories_delete(acc_id: int):
    _ensure_admin()
    a = db.session.get(Accessory, acc_id)
    if not a:
        return jsonify(ok=False, error="Accesorio no encontrado."), 404

    # “Soft delete” para no romper históricos si algún día se referencian
    soft = (request.args.get("soft") or "").lower() in ("1", "true", "yes", "y")
    if soft:
        a.active = False
        db.session.commit()
        return jsonify(ok=True, message="Accesorio desactivado."), 200

    db.session.delete(a)
    db.session.commit()
    return jsonify(ok=True, message="Accesorio eliminado."), 200


# =========================
# GESTIÓN DE COMPRAS DE COMBUSTIBLE
# =========================
@admin_bp.route("/fuel-purchases")
@login_required
@roles_required("admin")
def fuel_purchases():
    _ensure_admin()

    # Filtros simples
    page = request.args.get("page", 1, type=int)

    q = db.session.query(FuelPurchase).order_by(FuelPurchase.created_at.desc())

    pagination = q.paginate(page=page, per_page=20, error_out=False)

    return render_template(
        "admin/fuel_purchases.html",
        purchases=pagination.items,
        pagination=pagination
    )


@admin_bp.route("/fuel-purchases/<int:fp_id>")
@login_required
@roles_required("admin")
def fuel_purchase_detail(fp_id):
    _ensure_admin()

    fp = db.session.get(FuelPurchase, fp_id)
    if not fp:
        flash("Compra no encontrada.", "danger")
        return redirect(url_for("admin.fuel_purchases"))

    # Obtener dispersiones (OperatorLogs vinculados)
    dispersions = (
        db.session.query(OperatorLog)
        .filter(OperatorLog.fuel_purchase_id == fp_id)
        .order_by(OperatorLog.created_at.asc())
        .all()
    )

    return render_template(
        "admin/fuel_purchase_detail.html",
        purchase=fp,
        dispersions=dispersions
    )
