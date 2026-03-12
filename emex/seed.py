# emex/seed.py
import os
from .extensions import db
from .models import User, Unit, Route

def seed_data(app):
    """Carga datos base sin duplicar (idempotente)."""
    with app.app_context():
        # 👇 Si trabajas SIEMPRE con migraciones, no uses create_all():
        # db.create_all()  # <- déjalo comentado o elimínalo

        admin_email = os.getenv("ADMIN_EMAIL", "admin@emex.mx")
        admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

        # ---- Admin ----
        admin = User.query.filter_by(email=admin_email).first()
        if not admin:
            admin = User(name="Admin EMEX", email=admin_email, role="admin")
            admin.set_password(admin_password)
            db.session.add(admin)

        # ---- Units ---- (evita duplicados por code)
        units = [
            dict(code="EXC-001", plate="QRO-123-A",
                 description="Excavadora CAT 320", type="excavadora"),
            dict(code="RET-010", plate="QRO-987-B",
                 description="Retro JCB 3CX", type="retro"),
        ]
        for u in units:
            if not Unit.query.filter_by(code=u["code"]).first():
                db.session.add(Unit(**u))

        # ---- Routes ---- (evita duplicados por origin+destination)
        routes = [
            ("Querétaro", "Celaya"),
            ("Querétaro", "San Miguel de Allende"),
        ]
        for o, d in routes:
            if not Route.query.filter_by(origin=o, destination=d).first():
                db.session.add(Route(origin=o, destination=d))

        db.session.commit()
        print("✔ Seed completado sin duplicados.")
