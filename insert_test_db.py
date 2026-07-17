import os
import json
from datetime import datetime
from dotenv import load_dotenv

# Cargar configuración y DB URL
load_dotenv()

# Importar la app de Flask creada para poder usar el contexto y las tablas
from emex import create_app, db
from emex.models import User, OperatorLog, Unit, FuelPurchase, WhatsappSession

def test_db_insertion():
    app = create_app()
    
    with app.app_context():
        # JSON Simulado como si nos lo hubiera entregado OpenAI
        extracted_data = {
            "complete": True,
            "role": "operador",
            "nombre": "Iván Prueba Local",
            "unidad": "Retro 4",
            "diesel_litros": 50.0,
            "cantidad": "8 horas",
            "servicio_incidencia": "mantenimiento preventivo prueba",
            "fecha": datetime.utcnow().strftime("%Y-%m-%d"),
            "ruta": "Obra Reforma (Test DB)"
        }
        
        print("1. JSON Simulado de OpenAI:")
        print(json.dumps(extracted_data, indent=2, ensure_ascii=False))
        
        # Simular al usuario que mandó el WhatsApp
        phone_number = "5215584852504"
        user = User.query.filter_by(phone=phone_number).first()
        
        if not user:
            print(f"\n2. Creando usuario temporal para {phone_number}...")
            user = User.query.filter_by(phone="whatsapp_temporal").first()
            if not user:
                user = User(
                    name=f"Usuario Anónimo ({phone_number})",
                    phone="whatsapp_temporal",
                    password_hash="temp",
                    role="worker"
                )
                db.session.add(user)
                db.session.commit()
        else:
            print(f"\n2. Usuario encontrado: {user.name}")
            
        # ==========================================
        # MISMA LÓGICA DE ROUTES.PY
        # ==========================================
        print("\n3. Comenzando inserción a la Base de Datos Hostinger...")
        
        role = extracted_data.get("role", "operador").lower()
        
        # Buscar Unidad
        unit_id = None
        extracted_unit = extracted_data.get("unidad")
        if extracted_unit and str(extracted_unit).lower() != "null":
            unit = Unit.query.filter(
                (Unit.code.ilike(f"%{extracted_unit}%")) |
                (Unit.description.ilike(f"%{extracted_unit}%"))
            ).first()
            if unit:
                unit_id = unit.id

        liters = extracted_data.get("diesel_litros")
        try: liters = float(liters) if liters else None
        except: liters = None

        worker_name = extracted_data.get("nombre") or user.name

        servicio = extracted_data.get("servicio_incidencia") or ""
        has_si = bool(servicio and servicio.strip().lower() not in ("sin incidencias", "sin novedad", "ninguno", ""))

        fecha_str = extracted_data.get("fecha")
        log_date = datetime.utcnow()
        if fecha_str:
            try: log_date = datetime.strptime(fecha_str, "%Y-%m-%d")
            except: pass

        ruta = extracted_data.get("ruta") or "Lugar no especificado"

        cantidad_raw = extracted_data.get("cantidad") or ""
        hours = None
        
        # Extraer horas
        import re
        match = re.search(r"[\d\.]+", str(cantidad_raw))
        if match:
            try: hours = float(match.group())
            except: pass
            
        full_notes = f"📍 Ruta/Lugar: {ruta}"
        if servicio:
            full_notes += f"\n🔧 Servicio/Incidencia: {servicio}"

        new_log = OperatorLog(
            worker_id=user.id,
            worker_name=worker_name,
            project_name=ruta,
            time_productive=hours,
            time_total=hours,
            has_fuel=(liters is not None and liters > 0),
            fuel_liters=liters,
            main_unit_id=unit_id,
            has_service_incident=has_si,
            si_kind="incidencia" if has_si else None,
            si_subtype=servicio if has_si else None,
            notes=full_notes,
            created_at=log_date,
        )
        db.session.add(new_log)
        db.session.commit()
        
        print("\n✅ ¡ÉXITO! El registro ha sido guardado en la Base de Datos remotamente.")
        print(f"ID del nuevo log: {new_log.id} | Proyecto: {new_log.project_name}")

if __name__ == "__main__":
    try:
        test_db_insertion()
    except Exception as e:
        print(f"❌ ERROR: {e}")
