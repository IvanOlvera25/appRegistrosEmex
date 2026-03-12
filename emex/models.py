from datetime import datetime, date
from .extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

# =========================
# Usuarios
# =========================
class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(30), unique=True, nullable=True)  # WhatsApp
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="worker")  # 'admin' | 'worker'
    job_title = db.Column(db.String(120))              # cargo
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones de conveniencia
    operator_logs = db.relationship("OperatorLog", backref="worker", foreign_keys="OperatorLog.worker_id")
    sales_registered = db.relationship("OperatorLog", backref="sale_registered_by", foreign_keys="OperatorLog.sale_registered_by_id")

    # NUEVO: Advertencias hechas por este usuario (si aplica)
    warnings = db.relationship("Warning", backref="worker_user", foreign_keys="Warning.worker_id")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# =========================
# Unidades
# =========================
class Unit(db.Model):
    __tablename__ = "units"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    plate = db.Column(db.String(50))
    description = db.Column(db.String(200))
    type = db.Column(db.String(50))
    status = db.Column(db.String(30), default="activa")

    # NUEVO: relación de advertencias
    warnings = db.relationship("Warning", backref="unit", foreign_keys="Warning.unit_id")

    def __repr__(self):
        return f"<Unit {self.code}>"

    def __str__(self):
        if self.description:
            return f"{self.code} — {self.description}"
        if self.type:
            return f"{self.code} — {self.type.capitalize()}"
        return self.code

    @property
    def label(self):
        return str(self)


# --- Accesorios (catálogo global, separados por tipo) ---
class Accessory(db.Model):
    __tablename__ = "accessories"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)              # 'operator' | 'driver'
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("kind", "name", name="uq_accessories_kind_name"),
    )

    def __repr__(self):
        return f"<Accessory {self.kind}:{self.name}>"


# =========================
# Rutas (choferes)
# =========================
class Route(db.Model):
    __tablename__ = "routes"
    id = db.Column(db.Integer, primary_key=True)
    origin = db.Column(db.String(120), nullable=False)
    destination = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def label(self):
        return f"{self.origin} ➝ {self.destination}"


# =========================
# Clientes
# =========================
class Client(db.Model):
    __tablename__ = "clients"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)  # Razón social / nombre
    tax_id = db.Column(db.String(32))                               # RFC
    contact_name = db.Column(db.String(120))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    projects = db.relationship("Project", back_populates="client")


# =========================
# Proyectos / Obras
# =========================
class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    code = db.Column(db.String(64))
    location = db.Column(db.String(160))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    client = db.relationship("Client", back_populates="projects")

    # NUEVO: relación de advertencias
    warnings = db.relationship("Warning", backref="project", foreign_keys="Warning.project_id")

    @property
    def label(self):
        return f"{self.code} — {self.name}" if self.code else self.name


# =========================
# Bitácora unificada
# =========================
class OperatorLog(db.Model):
    __tablename__ = "operator_logs"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Identidad del trabajador
    worker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    worker_name = db.Column(db.String(120), nullable=False)

    # Proyecto / Obra
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    project = db.relationship("Project", backref="operator_logs")
    project_name = db.Column(db.String(160), nullable=True)

    # Unidad principal
    main_unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=True)
    main_unit = db.relationship("Unit", foreign_keys=[main_unit_id])

    # Accesorios de la unidad
    unit_accessories = db.Column(db.Text, nullable=True)

    # Ruta (choferes)
    route_id = db.Column(db.Integer, db.ForeignKey("routes.id"), nullable=True)
    route = db.relationship("Route", backref="operator_logs")
    route_other_origin = db.Column(db.String(120), nullable=True)
    route_other_destination = db.Column(db.String(120), nullable=True)

    # Servicio/Incidencia
    has_service_incident = db.Column(db.Boolean, default=False)
    si_kind = db.Column(db.String(20), nullable=True)        # 'servicio' | 'incidencia'
    si_subtype = db.Column(db.String(60), nullable=True)
    si_unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=True)
    si_unit = db.relationship("Unit", foreign_keys=[si_unit_id])
    si_amount = db.Column(db.Numeric(12, 2), nullable=True)

    # Combustible
    has_fuel = db.Column(db.Boolean, default=False)
    fuel_time = db.Column(db.DateTime, nullable=True)
    fuel_unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=True)
    fuel_unit = db.relationship("Unit", foreign_keys=[fuel_unit_id])
    fuel_liters = db.Column(db.Numeric(12, 2), nullable=True)

    # NUEVO: Relación con la compra maestra de diesel
    fuel_purchase_id = db.Column(db.Integer, db.ForeignKey("fuel_purchases.id"), nullable=True)
    fuel_source_purchase = db.relationship("FuelPurchase", backref="dispersions")

    # Tiempos
    time_total = db.Column(db.Numeric(8, 2), nullable=True)
    time_productive = db.Column(db.Numeric(8, 2), nullable=True)
    time_si_duration = db.Column(db.Numeric(8, 2), nullable=True)
    time_fuel_duration = db.Column(db.Numeric(8, 2), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Horas extra
    overtime = db.Column(db.Boolean, default=False)
    overtime_hours = db.Column(db.Numeric(8, 2), nullable=True)
    overtime_reason = db.Column(db.String(200), nullable=True)

    # Ventas / utilidades
    sale_amount = db.Column(db.Numeric(12, 2), nullable=True)
    sale_registered_at = db.Column(db.DateTime, nullable=True)
    sale_registered_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    invoice_status = db.Column(db.String(30), nullable=True)  # 'pendiente', 'facturado', 'pagado'
    invoice_number = db.Column(db.String(50), nullable=True)

    # Nota / Ticket
    note_number   = db.Column(db.String(50), nullable=True)
    note_date     = db.Column(db.Date, nullable=True)
    note_photo_url = db.Column(db.String(255), nullable=True)

    # --------- helpers de presentación ---------
    @property
    def route_label(self):
        if self.route:
            return self.route.label
        if self.route_other_origin or self.route_other_destination:
            return f"{self.route_other_origin or ''} ➝ {self.route_other_destination or ''}".strip()
        return None

    @property
    def accessories(self):
        if not self.unit_accessories:
            return []
        return [x.strip() for x in self.unit_accessories.split(",") if x.strip()]

    @property
    def project_display(self):
        if self.project:
            return self.project.name
        return self.project_name

    # Cálculos
    @property
    def fuel_cost(self):
        if self.fuel_liters:
            # Si hay una compra origen, usar su precio
            if self.fuel_source_purchase and self.fuel_source_purchase.price_per_liter:
                return float(self.fuel_liters) * float(self.fuel_source_purchase.price_per_liter)
            # Fallback a precio estándar
            return float(self.fuel_liters) * 28.5
        return 0.0

    @property
    def service_cost(self):
        if self.has_service_incident and self.si_amount:
            return float(self.si_amount)
        return 0.0

    @property
    def total_costs(self):
        return self.fuel_cost + self.service_cost

    @property
    def utility(self):
        if self.sale_amount:
            return float(self.sale_amount) - self.total_costs
        return None

    @property
    def utility_margin(self):
        if self.sale_amount and float(self.sale_amount) > 0:
            return (self.utility / float(self.sale_amount)) * 100
        return None

    @property
    def has_sale(self):
        return self.sale_amount is not None and self.sale_amount > 0


    # En la clase OperatorLog, agregar estos métodos helper:

    @property
    def is_purchase_record(self):
        """Identifica si es un registro de compras del gestor."""
        return self.si_subtype == "compras" if hasattr(self, "si_subtype") else False

    @property
    def purchase_details(self):
        """Extrae detalles de compras desde las notas."""
        if not self.notes or not self.is_purchase_record:
            return {}

        details = {
            "diesel": None,
            "parts": [],
            "services": [],
            "attachments": []
        }

        # Parsear notas (formato esperado del formulario)
        lines = self.notes.split("\n")
        for line in lines:
            if "🛢️ Diesel:" in line:
                details["diesel"] = line.replace("🛢️ Diesel:", "").strip()
            elif "🔧 Refacciones:" in line:
                details["parts"].append(line.replace("🔧 Refacciones:", "").strip())
            elif "👷 Servicio:" in line:
                details["services"].append(line.replace("👷 Servicio:", "").strip())
            elif "📎 Adjuntos:" in line:
                attachments = line.replace("📎 Adjuntos:", "").strip()
                details["attachments"] = [a.strip() for a in attachments.split(",")]

        return details

# =========================
# NUEVO: Advertencias
# =========================
class Warning(db.Model):
    __tablename__ = "warnings"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relación con Proyecto (opcional)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)

    # Trabajador: puede venir como FK o solo texto
    worker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    worker_name = db.Column(db.String(120), nullable=True)  # se usa si no hay worker_id

    # Unidad involucrada (requerida en tu flujo)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=False)

    # Datos de la advertencia
    description = db.Column(db.Text, nullable=False)
    level = db.Column(db.String(10), nullable=False, default="bajo")  # 'bajo'|'medio'|'alto', indexable
    source_form = db.Column(db.String(20), nullable=True)  # 'operator' | 'driver' (opcional)

    # Archivo adjunto (relativo a /static)
    attachment_path = db.Column(db.String(255), nullable=True)
    attachment_mime = db.Column(db.String(80), nullable=True)

    __table_args__ = (
        db.Index("ix_warnings_level_created", "level", "created_at"),
    )

    def __repr__(self):
        who = self.worker_user.name if getattr(self, "worker_user", None) else (self.worker_name or "—")
        return f"<Warning {self.level} by {who} at {self.created_at:%Y-%m-%d %H:%M}>"

    @property
    def has_image(self):
        return bool(self.attachment_mime and self.attachment_mime.startswith("image/"))


# =========================
# NUEVO: Compras de Combustible (Inventario)
# =========================
class FuelPurchase(db.Model):
    __tablename__ = "fuel_purchases"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Datos de la compra
    provider = db.Column(db.String(120), nullable=True)  # Gasolinera / Proveedor
    invoice = db.Column(db.String(50), nullable=True)    # Factura / Ticket

    liters_bought = db.Column(db.Numeric(12, 2), nullable=False, default=0.0)
    price_per_liter = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    total_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0.0)

    # Control de dispersión
    liters_dispersed = db.Column(db.Numeric(12, 2), default=0.0)

    # Quién registró
    registered_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    registered_by = db.relationship("User", foreign_keys=[registered_by_id])

    # Proyecto asociado (opcional, si la compra es para una obra específica)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    project = db.relationship("Project", backref="fuel_purchases")

    @property
    def liters_pending(self):
        return float(self.liters_bought or 0) - float(self.liters_dispersed or 0)

    @property
    def status(self):
        pending = self.liters_pending
        if pending <= 0.1: # Tolerancia pequeña
            return "dispersado"
        if float(self.liters_dispersed or 0) > 0:
            return "parcial"
        return "pendiente"


# =========================
# Sesiones de WhatsApp (Chatbot)
# =========================
class WhatsappSession(db.Model):
    __tablename__ = "whatsapp_sessions"
    
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30), unique=True, nullable=False)
    
    worker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    worker = db.relationship("User", foreign_keys=[worker_id])
    
    state = db.Column(db.String(50), default="idle")
    context_data = db.Column(db.Text, nullable=True) # Guarda historial JSON
    
    last_interaction = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<WhatsappSession {self.phone} - state:{self.state}>"

