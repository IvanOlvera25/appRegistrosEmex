# emex/worker/routes.py

import os
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from werkzeug.utils import secure_filename
from flask_login import current_user

from ..extensions import db
from ..models import Unit, OperatorLog, Route, User, Accessory, FuelPurchase
import json

# Soporte a Project (si existe)
try:
    from ..models import Project  # type: ignore
except Exception:
    Project = None  # type: ignore

# Soporte a Warning (nuevo modelo para advertencias)
try:
    from ..models import Warning  # type: ignore
except Exception:
    Warning = None  # type: ignore

worker_bp = Blueprint("worker", __name__, template_folder="../templates/worker")

# -------------------- Helpers de catálogos (reales) --------------------
def get_workers():
    """Usuarios con rol 'worker' ordenados por nombre (sin dummy)."""
    return User.query.filter_by(role="worker").order_by(User.name.asc()).all()

def get_projects():
    """Proyectos reales (activos si el modelo tiene 'active')."""
    if not Project:
        return []
    q = db.session.query(Project)
    if hasattr(Project, "active"):
        q = q.filter(Project.active.is_(True))
    return q.order_by(getattr(Project, "name", "id")).all()

def _accessories_by_kind(kind: str):
    """
    Regresa objetos Accessory por tipo ('operator' o 'driver'),
    sólo activos si el modelo tiene ese campo.
    """
    q = db.session.query(Accessory).filter(Accessory.kind == kind)
    if hasattr(Accessory, "active"):
        q = q.filter(Accessory.active.is_(True))
    return q.order_by(Accessory.name.asc()).all()

def get_operator_accessories_names():
    """Lista de nombres de accesorios para operadores."""
    return [a.name for a in _accessories_by_kind("operator")]

def get_driver_accessories_names():
    """Lista de nombres de accesorios para choferes."""
    return [a.name for a in _accessories_by_kind("driver")]

def to_int(value):
    try:
        return int(value)
    except Exception:
        return None

def parse_datetime_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None

# -------------------- Config y helpers de archivos (Advertencias) --------------------
ALLOWED_WARN_EXTS = {"jpg", "jpeg", "png", "pdf", "doc", "docx"}
MAX_WARN_SIZE_MB = 10

def _save_warning_file(file_storage, base_folder="uploads/warnings"):
    """
    Guarda el archivo de advertencia dentro de /static/uploads/warnings/<año>/<mes>/.
    Devuelve (relative_path, mime) o (None, None) si no hay archivo.
    """
    if not file_storage or not file_storage.filename:
        return None, None

    fname = secure_filename(file_storage.filename)
    ext = (fname.rsplit(".", 1)[-1].lower() if "." in fname else "")

    if ext not in ALLOWED_WARN_EXTS:
        raise ValueError("Formato no permitido. Usa JPG/PNG/PDF/DOC/DOCX.")

    # Verificación de tamaño
    file_storage.stream.seek(0, os.SEEK_END)
    size_mb = file_storage.stream.tell() / (1024 * 1024)
    file_storage.stream.seek(0)
    if size_mb > MAX_WARN_SIZE_MB:
        raise ValueError(f"Archivo mayor a {MAX_WARN_SIZE_MB} MB.")

    now = datetime.utcnow()
    rel_dir = os.path.join(base_folder, str(now.year), f"{now.month:02d}")  # p.ej. uploads/warnings/2025/10
    abs_dir = os.path.join(current_app.static_folder, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    unique = uuid.uuid4().hex[:12]
    stored_name = f"{os.path.splitext(fname)[0]}_{unique}.{ext}"
    abs_path = os.path.join(abs_dir, stored_name)
    file_storage.save(abs_path)

    rel_path = f"{rel_dir}/{stored_name}".replace("\\", "/")
    return rel_path, (file_storage.mimetype or "")

# -------------------- Vistas --------------------
@worker_bp.route("/")
def index():
    return render_template("worker/index.html")

@worker_bp.route("/operadores", methods=["GET", "POST"])
def operadores():
    units = Unit.query.order_by(Unit.code).all()
    workers = get_workers()
    projects = get_projects()
    accessories = get_operator_accessories_names()  # desde BD (tipo operator)

    if request.method == "POST":
        # ---- Identificación (IDs reales) ----
        worker_id = to_int(request.form.get("worker_id"))
        worker_name_manual = (request.form.get("worker_name") or "").strip()
        project_id = to_int(request.form.get("project_id"))
        project_text = (request.form.get("project_text") or "").strip()
        main_unit_id = to_int(request.form.get("main_unit_id") or request.form.get("main_unit"))
        unit_accessories = request.form.getlist("unit_accessories") or []

        # Valida: requiere (worker_id o worker_name_manual) y (project_id o project_text)
        if not worker_id and not worker_name_manual:
            flash("Selecciona un trabajador o escribe uno manual.", "danger")
            return redirect(url_for("worker.operadores"))
        if not project_id and not project_text:
            flash("Selecciona una obra o escribe una manual.", "danger")
            return redirect(url_for("worker.operadores"))

        # ---- Servicio/Incidencia ----
        has_si = (request.form.get("has_si") == "si")
        si_kind = request.form.get("si_kind") if has_si else None
        si_subtype = request.form.get("si_subtype") if has_si else None
        si_unit_id = to_int(request.form.get("si_unit_id")) if has_si else None
        si_amount = request.form.get("si_amount") if has_si else None

        # ---- Combustible ----
        has_fuel = (request.form.get("has_fuel") == "si")
        fuel_time = parse_datetime_iso(request.form.get("fuel_time") if has_fuel else None)
        fuel_unit_id = to_int(request.form.get("fuel_unit_id")) if has_fuel else None
        fuel_liters = request.form.get("fuel_liters") if has_fuel else None

        # ---- Tiempos ----
        time_total = request.form.get("time_total") or None
        time_productive = request.form.get("time_productive") or None
        time_si_duration = request.form.get("time_si_duration") or None
        time_fuel_duration = request.form.get("time_fuel_duration") or None
        notes = request.form.get("notes") or None

        overtime = (request.form.get("overtime") == "si")
        overtime_hours = request.form.get("overtime_hours") if overtime else None
        overtime_reason = request.form.get("overtime_reason") if overtime else None

        # ---- Persistencia ----
        entry = OperatorLog(
            # worker
            worker_id=worker_id if worker_id else (current_user.id if current_user.is_authenticated else None),
            worker_name=None,  # lo seteamos abajo
            # S/I
            has_service_incident=has_si,
            si_kind=si_kind,
            si_subtype=si_subtype,
            si_unit_id=si_unit_id,
            si_amount=si_amount,
            # Combustible
            has_fuel=has_fuel,
            fuel_time=fuel_time,
            fuel_unit_id=fuel_unit_id,
            fuel_liters=fuel_liters,
            # Tiempos
            time_total=time_total,
            time_productive=time_productive,
            time_si_duration=time_si_duration,
            time_fuel_duration=time_fuel_duration,
            notes=notes,
            # Extra
            overtime=overtime,
            overtime_hours=overtime_hours,
            overtime_reason=overtime_reason,
        )

        # Asignar nombre del trabajador coherente
        if worker_id:
            u = db.session.get(User, worker_id)
            entry.worker_name = u.name if u else (worker_name_manual or "—")
        else:
            entry.worker_name = worker_name_manual

        # Proyecto: prioriza project_id; si no, texto libre
        if hasattr(entry, "project_id") and project_id and Project:
            entry.project_id = project_id
        elif hasattr(entry, "project_name"):
            entry.project_name = project_text or None

        # Unidad principal y accesorios
        if hasattr(entry, "main_unit_id"):
            entry.main_unit_id = main_unit_id
        if hasattr(entry, "unit_accessories"):
            entry.unit_accessories = ", ".join(unit_accessories) if unit_accessories else None

        db.session.add(entry)
        db.session.commit()
        flash("Registro de operador guardado.", "success")
        return redirect(url_for("worker.index"))

    return render_template(
        "worker/operator_form.html",
        units=units, workers=workers,
        projects=projects, accessories=accessories
    )

@worker_bp.route("/choferes", methods=["GET", "POST"])
def choferes():
    units = Unit.query.order_by(Unit.code).all()
    workers = get_workers()
    routes = Route.query.filter_by(active=True).order_by(Route.origin, Route.destination).all()
    projects = get_projects()
    accessories = get_driver_accessories_names()  # desde BD (tipo driver)

    if request.method == "POST":
        # ---- Identificación ----
        worker_id = to_int(request.form.get("worker_id"))
        worker_name_manual = (request.form.get("worker_name") or "").strip()
        project_id = to_int(request.form.get("project_id"))
        project_text = (request.form.get("project_text") or "").strip()
        main_unit_id = to_int(request.form.get("main_unit_id") or request.form.get("main_unit"))
        unit_accessories = request.form.getlist("unit_accessories") or []

        if not worker_id and not worker_name_manual:
            flash("Selecciona un trabajador o escribe uno manual.", "danger")
            return redirect(url_for("worker.choferes"))
        if not project_id and not project_text:
            flash("Selecciona una obra o escribe una manual.", "danger")
            return redirect(url_for("worker.choferes"))

        # ---- Ruta ----
        route_select = request.form.get("route_select")  # id de ruta o 'other'
        route_id = None
        route_other_origin = None
        route_other_destination = None

        if route_select == "other":
            route_other_origin = (request.form.get("route_other_origin") or "").strip()
            route_other_destination = (request.form.get("route_other_destination") or "").strip()
            if not route_other_origin or not route_other_destination:
                flash("Ingresa origen y destino para 'Otros'.", "danger")
                return redirect(url_for("worker.choferes"))
            new_r = Route(origin=route_other_origin, destination=route_other_destination)
            db.session.add(new_r)
            db.session.flush()
            route_id = new_r.id
        else:
            route_id = to_int(route_select) if route_select else None

        # ---- Servicio/Incidencia ----
        has_si = (request.form.get("has_si") == "si")
        si_kind = request.form.get("si_kind") if has_si else None
        si_subtype = request.form.get("si_subtype") if has_si else None
        si_unit_id = to_int(request.form.get("si_unit_id")) if has_si else None
        si_amount = request.form.get("si_amount") if has_si else None

        # ---- Combustible ----
        has_fuel = (request.form.get("has_fuel") == "si")
        fuel_time = parse_datetime_iso(request.form.get("fuel_time") if has_fuel else None)
        fuel_unit_id = to_int(request.form.get("fuel_unit_id")) if has_fuel else None
        fuel_liters = request.form.get("fuel_liters") if has_fuel else None

        # ---- Tiempos ----
        time_total = request.form.get("time_total") or None
        time_productive = request.form.get("time_productive") or None
        time_si_duration = request.form.get("time_si_duration") or None
        time_fuel_duration = request.form.get("time_fuel_duration") or None
        notes = request.form.get("notes") or None

        overtime = (request.form.get("overtime") == "si")
        overtime_hours = request.form.get("overtime_hours") if overtime else None
        overtime_reason = request.form.get("overtime_reason") if overtime else None

        # ---- Persistencia ----
        entry = OperatorLog(
            worker_id=worker_id if worker_id else (current_user.id if current_user.is_authenticated else None),
            worker_name=None,  # seteamos abajo
            # Ruta
            route_id=route_id,
            route_other_origin=route_other_origin,
            route_other_destination=route_other_destination,
            # S/I
            has_service_incident=has_si,
            si_kind=si_kind,
            si_subtype=si_subtype,
            si_unit_id=si_unit_id,
            si_amount=si_amount,
            # Combustible
            has_fuel=has_fuel,
            fuel_time=fuel_time,
            fuel_unit_id=fuel_unit_id,
            fuel_liters=fuel_liters,
            # Tiempos
            time_total=time_total,
            time_productive=time_productive,
            time_si_duration=time_si_duration,
            time_fuel_duration=time_fuel_duration,
            notes=notes,
            # Extra
            overtime=overtime,
            overtime_hours=overtime_hours,
            overtime_reason=overtime_reason,
        )

        # worker_name coherente
        if worker_id:
            u = db.session.get(User, worker_id)
            entry.worker_name = u.name if u else (worker_name_manual or "—")
        else:
            entry.worker_name = worker_name_manual

        # Proyecto
        if hasattr(entry, "project_id") and project_id and Project:
            entry.project_id = project_id
        elif hasattr(entry, "project_name"):
            entry.project_name = project_text or None

        if hasattr(entry, "main_unit_id"):
            entry.main_unit_id = main_unit_id
        if hasattr(entry, "unit_accessories"):
            entry.unit_accessories = ", ".join(unit_accessories) if unit_accessories else None

        # ---- Procesar viajes múltiples (trips_json) ----
        trips_json_str = request.form.get("trips_json")
        trips_data = []
        if trips_json_str:
            try:
                trips_data = json.loads(trips_json_str)
            except:
                trips_data = []

        # Construir notas con información de viajes
        trips_notes = []
        total_trips_count = 0
        for t in trips_data:
            t_unit_id = t.get("unit_id")
            t_route_id = t.get("route_id")
            t_origin = t.get("other_origin") or ""
            t_dest = t.get("other_destination") or ""
            t_count = int(t.get("count") or 1)
            total_trips_count += t_count

            # Obtener nombres legibles
            unit_label = "Sin unidad"
            if t_unit_id:
                u_obj = db.session.get(Unit, t_unit_id)
                if u_obj:
                    unit_label = u_obj.label

            route_label = "Ruta personalizada"
            if t_route_id and t_route_id != "other":
                r_obj = db.session.get(Route, t_route_id)
                if r_obj:
                    route_label = r_obj.label
            elif t_origin or t_dest:
                route_label = f"{t_origin} → {t_dest}"

            trips_notes.append(f"• {unit_label}: {route_label} | {t_count} viaje(s)")

        if trips_notes:
            existing_notes = entry.notes or ""
            trip_summary = f"🚚 VIAJES ({total_trips_count} total):\n" + "\n".join(trips_notes)
            entry.notes = f"{trip_summary}\n\n{existing_notes}".strip() if existing_notes else trip_summary

        db.session.add(entry)
        db.session.commit()
        flash("Registro de chofer guardado.", "success")
        return redirect(url_for("worker.index"))

    return render_template(
        "worker/driver_form.html",
        units=units, workers=workers, routes=routes,
        projects=projects, accessories=accessories
    )

@worker_bp.route("/add-route", methods=["POST"])
def add_route():
    data = request.get_json(force=True, silent=True) or {}
    origin = (data.get("origin") or "").strip()
    destination = (data.get("destination") or "").strip()
    if not origin or not destination:
        return jsonify({"ok": False, "error": "Origen y destino son requeridos."}), 400
    r = Route(origin=origin, destination=destination)
    db.session.add(r)
    db.session.commit()
    return jsonify({"ok": True, "id": r.id, "label": r.label})

# -------------------- NUEVO: Crear Advertencias (POST) --------------------
@worker_bp.route("/warnings", methods=["POST"], endpoint="create_warning")
def create_warning():
    """
    Crea una advertencia desde los formularios de Operador/Chofer.
    Los modales envían a action=url_for('worker.create_warning').
    """
    if not Warning:
        flash("El modelo Warning no está disponible en el servidor.", "danger")
        return redirect(request.referrer or url_for("worker.index"))

    source_form  = (request.form.get("source_form") or "").strip()  # 'operator' | 'driver'
    project_id   = to_int(request.form.get("project_id"))
    worker_id    = to_int(request.form.get("worker_id"))
    worker_name  = (request.form.get("worker_name") or "").strip()
    unit_id      = to_int(request.form.get("unit_id"))
    description  = (request.form.get("description") or "").strip()
    level        = (request.form.get("level") or "bajo").strip().lower()
    file_storage = request.files.get("attachment")

    # Validaciones mínimas
    if not description:
        flash("La descripción es obligatoria.", "danger")
        return redirect(request.referrer or url_for("worker.index"))
    if not unit_id:
        flash("Selecciona una unidad antes de registrar la advertencia.", "danger")
        return redirect(request.referrer or url_for("worker.index"))
    if not (worker_id or worker_name):
        flash("Selecciona o escribe el nombre del trabajador.", "danger")
        return redirect(request.referrer or url_for("worker.index"))
    if level not in {"bajo", "medio", "alto"}:
        level = "bajo"

    # Guardar adjunto (si viene)
    attachment_path = None
    attachment_mime = None
    try:
        if file_storage and file_storage.filename:
            attachment_path, attachment_mime = _save_warning_file(file_storage)
    except Exception as e:
        flash(f"Adjunto no guardado: {e}", "warning")

    # Crear entidad Warning
    w = Warning(
        project_id      = project_id,
        worker_id       = worker_id,
        worker_name     = (worker_name or None) if not worker_id else None,
        unit_id         = unit_id,
        description     = description,
        level           = level,
        attachment_path = attachment_path,   # relativo a /static
        attachment_mime = attachment_mime,
        source_form     = source_form if source_form in ("operator","driver") else None,
        created_at      = datetime.utcnow()
    )

    db.session.add(w)
    db.session.commit()

    flash("Advertencia registrada correctamente.", "success")

    # Redirección al formulario de origen
    if source_form == "driver":
        return redirect(request.referrer or url_for("worker.choferes"))
    elif source_form == "operator":
        return redirect(request.referrer or url_for("worker.operadores"))
    return redirect(request.referrer or url_for("worker.index"))


# ==================== GESTOR DE COMPRAS ====================
@worker_bp.route("/gestor-compras", methods=["GET", "POST"])
def gestor_compras():
    """Formulario para registrar compras: diesel, refacciones, servicios."""
    units = Unit.query.order_by(Unit.code).all()
    workers = get_workers()
    projects = get_projects()

    if request.method == "POST":
        # ---- Información General ----
        manager_id = to_int(request.form.get("manager_id"))
        manager_name = (request.form.get("manager_name") or "").strip()
        project_id = to_int(request.form.get("project_id"))
        project_text = (request.form.get("project_text") or "").strip()
        purchase_date = parse_datetime_iso(request.form.get("purchase_date"))

        # Validaciones básicas
        if not manager_id and not manager_name:
            flash("Selecciona un gestor o escribe uno manual.", "danger")
            return redirect(url_for("worker.gestor_compras"))
        if not project_id and not project_text:
            flash("Selecciona una obra o escribe una manual.", "danger")
            return redirect(url_for("worker.gestor_compras"))
        if not purchase_date:
            flash("La fecha de compra es obligatoria.", "danger")
            return redirect(url_for("worker.gestor_compras"))

        # ---- Compra de Diesel ----
        has_diesel = (request.form.get("has_diesel") == "si")
        diesel_unit_id = to_int(request.form.get("diesel_unit_id")) if has_diesel else None
        diesel_type = request.form.get("diesel_type") if has_diesel else None
        diesel_amount = request.form.get("diesel_amount") if has_diesel else None
        diesel_price_per_liter = request.form.get("diesel_price_per_liter") if has_diesel else None
        diesel_total_cost = request.form.get("diesel_total_cost") if has_diesel else None
        diesel_notes = request.form.get("diesel_notes") if has_diesel else None

        # ---- Compra de Refacciones ----
        has_parts = (request.form.get("has_parts") == "si")
        parts_unit_id = to_int(request.form.get("parts_unit_id")) if has_parts else None
        parts_name = request.form.get("parts_name") if has_parts else None
        parts_cost = request.form.get("parts_cost") if has_parts else None
        parts_invoice = request.form.get("parts_invoice") if has_parts else None
        parts_notes = request.form.get("parts_notes") if has_parts else None

        # ---- Pago a Prestadores ----
        has_service = (request.form.get("has_service") == "si")
        service_unit_id = to_int(request.form.get("service_unit_id")) if has_service else None
        service_type = request.form.get("service_type") if has_service else None
        service_provider = request.form.get("service_provider") if has_service else None
        service_cost = request.form.get("service_cost") if has_service else None
        service_invoice = request.form.get("service_invoice") if has_service else None
        service_description = request.form.get("service_description") if has_service else None

        # ---- Notas Generales ----
        general_notes = request.form.get("general_notes") or None

        # ---- Guardar Adjuntos ----
        attachments_paths = []
        files = request.files.getlist("attachments")
        for file_storage in files:
            if file_storage and file_storage.filename:
                try:
                    path, mime = _save_warning_file(file_storage, base_folder="uploads/purchases")
                    if path:
                        attachments_paths.append(path)
                except Exception as e:
                    flash(f"Error al guardar archivo {file_storage.filename}: {e}", "warning")

        # ---- Persistencia: Crear registro OperatorLog ----
        # Usamos OperatorLog para mantener coherencia con el sistema existente
        entry = OperatorLog(
            created_at=purchase_date,
            worker_id=manager_id if manager_id else (current_user.id if current_user.is_authenticated else None),
            worker_name=None,  # Se asigna abajo
        )

        # Nombre del gestor
        if manager_id:
            u = db.session.get(User, manager_id)
            entry.worker_name = u.name if u else (manager_name or "Gestor")
        else:
            entry.worker_name = manager_name

        # Proyecto
        if hasattr(entry, "project_id") and project_id and Project:
            entry.project_id = project_id
        elif hasattr(entry, "project_name"):
            entry.project_name = project_text or None

        # ---- Mapeo de datos de compras ----

        # 1. Compra de Diesel (FuelPurchase)
        fuel_purchase = None
        if has_diesel:
            try:
                # Calcular valores maestros
                d_amount = float(diesel_amount or 0)
                d_price = float(diesel_price_per_liter or 0)
                d_total = float(diesel_total_cost or 0)

                # Si viene en pesos, recalcular litros
                if diesel_type == "pesos" and d_price > 0:
                    d_amount = d_total / d_price

                # Crear la compra maestra
                fuel_purchase = FuelPurchase(
                    created_at=purchase_date,
                    provider=diesel_notes, # Usamos notas como proveedor/info por ahora
                    invoice=None, # Podríamos agregar campo invoice específico si se requiere
                    liters_bought=d_amount,
                    price_per_liter=d_price,
                    total_cost=d_total,
                    liters_dispersed=0,
                    registered_by_id=manager_id if manager_id else (current_user.id if current_user.is_authenticated else None),
                    project_id=project_id if project_id else None
                )
                db.session.add(fuel_purchase)
                db.session.flush() # Para obtener ID

                # 2. Dispersión (OperatorLogs vinculados)
                dispersion_json = request.form.get("diesel_dispersion_data")
                if dispersion_json:
                    dispersions = json.loads(dispersion_json)
                    total_dispersed = 0

                    for disp in dispersions:
                        u_id = to_int(disp.get("unit_id"))
                        liters = float(disp.get("liters") or 0)
                        disp_datetime = parse_datetime_iso(disp.get("datetime")) or purchase_date

                        if u_id and liters > 0:
                            # Crear log de carga de combustible para la unidad
                            disp_log = OperatorLog(
                                created_at=disp_datetime,
                                worker_id=entry.worker_id,
                                worker_name=entry.worker_name,
                                project_id=entry.project_id,
                                project_name=entry.project_name,
                                has_fuel=True,
                                fuel_unit_id=u_id,
                                fuel_liters=liters,
                                fuel_time=disp_datetime,
                                fuel_purchase_id=fuel_purchase.id, # VINCULO CLAVE
                                notes=f"Dispersión de compra #{fuel_purchase.id}"
                            )
                            db.session.add(disp_log)
                            total_dispersed += liters

                    fuel_purchase.liters_dispersed = total_dispersed

            except Exception as e:
                current_app.logger.error(f"Error procesando diesel: {e}")
                flash(f"Error al procesar compra de diesel: {e}", "danger")

        # Refacciones y servicios: los guardamos como servicio/incidencia
        total_service_cost = 0
        service_details = []

        if has_parts:
            try:
                cost = float(parts_cost or 0)
                total_service_cost += cost
                service_details.append(f"Refacción: {parts_name or 'N/A'} - ${cost:.2f} (Factura: {parts_invoice or 'N/A'})")
            except:
                pass

        if has_service:
            try:
                cost = float(service_cost or 0)
                total_service_cost += cost
                service_details.append(f"Servicio {service_type or 'N/A'}: {service_provider or 'N/A'} - ${cost:.2f}")
            except:
                pass

        # Si hay servicios/refacciones, usamos el 'entry' principal (OperatorLog)
        # Si SOLO hubo diesel, 'entry' se usa solo si hay notas generales o adjuntos,
        # pero para no duplicar lógica, guardamos 'entry' si tiene contenido relevante.

        save_main_entry = False

        if total_service_cost > 0:
            save_main_entry = True
            entry.has_service_incident = True
            entry.si_kind = "servicio"
            entry.si_subtype = "compras"  # Identificador especial para compras
            entry.si_amount = total_service_cost

            # Priorizar unidad: parts > service
            if parts_unit_id:
                entry.si_unit_id = parts_unit_id
            elif service_unit_id:
                entry.si_unit_id = service_unit_id

        # ---- Consolidar notas ----
        notes_parts = []

        if has_diesel and diesel_notes:
            notes_parts.append(f"🛢️ Compra Diesel: {diesel_notes}")

        if has_parts and parts_notes:
            notes_parts.append(f"🔧 Refacciones: {parts_notes}")

        if has_service and service_description:
            notes_parts.append(f"👷 Servicio: {service_description}")

        if service_details:
            notes_parts.append("\n📋 Detalle de compras:\n" + "\n".join(service_details))

        if general_notes:
            notes_parts.append(f"\n📝 Notas: {general_notes}")

        if attachments_paths:
            notes_parts.append(f"\n📎 Adjuntos: {', '.join(attachments_paths)}")

        entry.notes = "\n".join(notes_parts) if notes_parts else None

        if entry.notes:
            save_main_entry = True

        # ---- Guardar en BD ----
        if save_main_entry:
            db.session.add(entry)

        db.session.commit()

        flash("Registro de compras guardado exitosamente.", "success")
        return redirect(url_for("worker.index"))

    return render_template(
        "worker/purchase_manager_form.html",
        units=units,
        workers=workers,
        projects=projects
    )