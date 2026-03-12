
# emex/auth/routes.py
import os
from types import SimpleNamespace

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func, case

from ..models import User, OperatorLog
from ..extensions import db

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/")
def home():
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return redirect(url_for("admin.dashboard"))
        # Workers: pueden ir a registrar o a su panel personal
        return redirect(url_for("worker.index"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        mode = (request.form.get("mode") or "admin").lower()
        remember = bool(request.form.get("remember"))

        # -------- Empleado: selecciona su nombre + password --------
        if mode == "employee":
            emp_id = request.form.get("employee_id") or ""
            password = request.form.get("password") or ""
            if not emp_id.isdigit():
                flash("Selecciona tu nombre del catálogo.", "danger")
                return redirect(url_for("auth.login"))

            user = User.query.get(int(emp_id))
            if not user or user.role != "worker" or not user.password_hash:
                flash("Empleado no válido o sin cuenta activa.", "danger")
                return redirect(url_for("auth.login"))

            if not user.check_password(password):
                flash("Contraseña incorrecta.", "danger")
                return redirect(url_for("auth.login"))

            login_user(user, remember=remember)
            flash("¡Bienvenido(a)!", "success")
            return redirect(url_for("auth.home"))

        # -------- Administrador: correo + password --------
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter(
            func.lower(User.email) == email,
            User.role == "admin"
        ).first()

        if not user or not user.check_password(password):
            flash("Correo o contraseña inválidos.", "danger")
            return redirect(url_for("auth.login"))

        login_user(user, remember=remember)
        flash("¡Bienvenido(a)!", "success")
        return redirect(url_for("auth.home"))

    # GET - Solo cargar empleados con cuenta activa (optimizado para solo id y name)
    employees = (
        db.session.query(User.id, User.name)
        .filter(
            User.role == "worker",
            User.password_hash.isnot(None),
            func.length(User.password_hash) > 0
        )
        .order_by(User.name.asc())
        .all()
    )

    if request.method == "POST":
        mode = (request.form.get("mode") or "admin").lower()
        remember = bool(request.form.get("remember"))

        # -------- Empleado: selecciona su nombre + password --------
        if mode == "employee":
            emp_id = request.form.get("employee_id") or ""
            password = request.form.get("password") or ""
            if not emp_id.isdigit():
                flash("Selecciona tu nombre del catálogo.", "danger")
                return render_template("auth/login.html", employees=employees)

            user = User.query.get(int(emp_id))
            if not user or user.role != "worker" or not user.password_hash:
                flash("Empleado no válido o sin cuenta activa.", "danger")
                return render_template("auth/login.html", employees=employees)

            if not user.check_password(password):
                flash("Contraseña incorrecta.", "danger")
                return render_template("auth/login.html", employees=employees)

            login_user(user, remember=remember)
            flash("¡Bienvenido(a)!", "success")
            return redirect(url_for("auth.home"))

        # -------- Administrador: correo + password --------
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter(
            func.lower(User.email) == email,
            User.role == "admin"
        ).first()

        if not user or not user.check_password(password):
            flash("Correo o contraseña inválidos.", "danger")
            return render_template("auth/login.html", employees=employees)

        login_user(user, remember=remember)
        flash("¡Bienvenido(a)!", "success")
        return redirect(url_for("auth.home"))

    # GET
    return render_template("auth/login.html", employees=employees)

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for("auth.login"))



@auth_bp.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        # Futuro: validar correo y enviar email con token
        flash('Si el correo existe en EMEX, te enviaremos instrucciones para restablecer la contraseña.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html')


# =========================
# Registro (Empleado / Admin)
# =========================
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # catálogo de empleados = usuarios con rol "worker"
    employees = (
        User.query.filter_by(role="worker")
        .order_by(User.name.asc())
        .all()
    )

    if request.method == "POST":
        mode = (request.form.get("mode") or "").lower()

        # ========== MODO EMPLEADO ==========
        if mode == "employee":
            employee_id = request.form.get("employee_id") or ""
            password    = request.form.get("password") or ""
            password2   = request.form.get("password2") or ""
            email_input = (request.form.get("email") or "").strip().lower()

            # validaciones
            if not employee_id or not employee_id.isdigit():
                flash("Selecciona tu nombre del catálogo de empleados.", "danger")
                return render_template("auth/register.html", employees=employees)

            emp = User.query.get(int(employee_id))
            if not emp or emp.role != "worker":
                flash("Empleado no válido.", "danger")
                return render_template("auth/register.html", employees=employees)

            if not password or not password2:
                flash("Debes indicar y confirmar tu contraseña.", "danger")
                return render_template("auth/register.html", employees=employees)
            if password != password2:
                flash("Las contraseñas no coinciden.", "danger")
                return render_template("auth/register.html", employees=employees)

            # correo: si ya tiene, lo respetamos; si no, lo guardamos (si está libre)
            if not emp.email and email_input:
                exists = User.query.filter(
                    func.lower(User.email) == email_input
                ).first()
                if exists:
                    flash("Ese correo ya está en uso.", "danger")
                    return render_template("auth/register.html", employees=employees)
                emp.email = email_input

            # si sigue sin correo, permitimos continuar (podrá iniciar sesión con email si lo tiene)
            emp.set_password(password)
            db.session.commit()

            login_user(emp)
            flash("Cuenta de empleado activada. ¡Bienvenido(a)!", "success")
            return redirect(url_for("auth.home"))

        # ========== MODO ADMIN ==========
        elif mode == "admin":
            name        = (request.form.get("name") or "").strip()
            email       = (request.form.get("email") or "").strip().lower()
            password    = request.form.get("password") or ""
            password2   = request.form.get("password2") or ""
            admin_code  = (request.form.get("admin_code") or "").strip()

            if not name or not email:
                flash("Nombre y correo son obligatorios.", "danger")
                return render_template("auth/register.html", employees=employees)
            if password != password2:
                flash("Las contraseñas no coinciden.", "danger")
                return render_template("auth/register.html", employees=employees)

            expected = os.getenv("ADMIN_SIGNUP_CODE", "12345")
            if admin_code != expected:
                flash("Código de administrador incorrecto.", "danger")
                return render_template("auth/register.html", employees=employees)

            if User.query.filter(func.lower(User.email) == email).first():
                flash("Ese correo ya está registrado.", "danger")
                return render_template("auth/register.html", employees=employees)

            u = User(name=name, email=email, role="admin")
            u.set_password(password)
            db.session.add(u)
            db.session.commit()

            login_user(u)
            flash("Administrador creado correctamente.", "success")
            return redirect(url_for("auth.home"))

        else:
            raise BadRequest("Modo de registro no válido.")

    # GET: mostrar formulario con catálogo
    return render_template("auth/register.html", employees=employees)
# =========================
# Panel de usuario (empleados)
# =========================
@auth_bp.route("/panel")
@login_required
def user_panel():
    # Admins: a dashboard admin
    if current_user.role == "admin":
        return redirect(url_for("admin.dashboard"))

    # Métricas del empleado actual
    uid = current_user.id
    totals = (
        db.session.query(
            func.count(OperatorLog.id),                                       # logs
            func.coalesce(func.sum(OperatorLog.time_total), 0),               # horas totales
            func.coalesce(func.sum(OperatorLog.time_productive), 0),          # horas productivas
            func.coalesce(func.sum(OperatorLog.overtime_hours), 0),           # horas extra
            func.coalesce(func.sum(OperatorLog.fuel_liters), 0),              # litros
            func.coalesce(func.sum(case((OperatorLog.has_service_incident == True, 1), else_=0)), 0)  # si/incidencias
        )
        .filter(OperatorLog.worker_id == uid)
        .one()
    )

    stats = SimpleNamespace(
        logs=int(totals[0] or 0),
        hours=float(totals[1] or 0),
        prod=float(totals[2] or 0),
        overtime=float(totals[3] or 0),
        liters=float(totals[4] or 0),
        si_count=int(totals[5] or 0),
        performance=((float(totals[2] or 0) / float(totals[1] or 1)) * 100) if float(totals[1] or 0) > 0 else 0.0,
    )

    # Últimos 30 registros para la tabla
    logs = (
        OperatorLog.query
        .filter(OperatorLog.worker_id == uid)
        .order_by(OperatorLog.created_at.desc())
        .limit(30)
        .all()
    )

    return render_template("auth/user_panel.html", stats=stats, logs=logs)
