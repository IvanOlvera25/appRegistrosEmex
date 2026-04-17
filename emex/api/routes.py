# emex/api/routes.py
import json
from datetime import datetime
from flask import Blueprint, request, jsonify

from ..extensions import db
from ..models import User, WhatsappSession, OperatorLog, Unit, FuelPurchase
from .evolution_client import send_whatsapp_message
from .openai_service import process_whatsapp_message

api_bp = Blueprint("api", __name__, url_prefix="/api")

@api_bp.route("/webhook/evolution", methods=["POST"])
def evolution_webhook():
    data = request.json
    
    event_type = data.get("event")
    # Aceptar variaciones comunes en el nombre del evento
    if event_type not in ["messages.upsert", "MESSAGES_UPSERT"]:
        return jsonify({"status": "ignored", "reason": f"not a message event ({event_type})"}), 200
        
    # En la versión 2.x, el payload viene dentro de "data"
    inner_data = data.get("data", {}) if "data" in data else data
    
    # Extraer identificadores que están al nivel de "data"
    remote_jid = inner_data.get("key", {}).get("remoteJid", "")
    from_me = inner_data.get("key", {}).get("fromMe", False)
    
    if "@g.us" in remote_jid:
        return jsonify({"status": "ignored", "reason": "group message"}), 200
        
    if from_me:
        return jsonify({"status": "ignored", "reason": "sent by me"}), 200

    # WhatsApp usa LID (Linked ID) que Evolution API v1 no puede resolver.
    # El webhook v1 incluye un campo "sender" con el número real @s.whatsapp.net
    if "@lid" in remote_jid:
        sender = data.get("sender", "")
        reply_jid = sender if sender else remote_jid
    else:
        reply_jid = remote_jid
    phone_number = reply_jid.split("@")[0]
    
    # El objeto de mensaje en sí (qué contiene el texto, audio, etc)
    msg_obj = inner_data.get("message", {})
    
    # Manejar los distintos tipos de mensajes de texto en WhatsApp
    text_content = (
        msg_obj.get("conversation") or 
        msg_obj.get("extendedTextMessage", {}).get("text") or 
        ""
    )
    
    if not text_content:
        return jsonify({"status": "ignored", "reason": "empty text"}), 200
        
    text_content = text_content.strip()

    user = User.query.filter_by(phone=phone_number).first()
    
    if not user:
        # Modo abierto: Crear un usuario genérico en el momento si no existe
        print(f"Nuevo usuario contactó por WhatsApp: {phone_number}. Creando perfil temporal...")
        user = User.query.filter_by(phone="whatsapp_temporal").first()
        
        if not user:
            # Si ni siquiera existe el genérico, lo creamos
            user = User(
                name=f"Usuario Anónimo ({phone_number})",
                phone="whatsapp_temporal",
                password_hash="temp",
                role="worker"
            )
            db.session.add(user)
            db.session.commit()

    session = WhatsappSession.query.filter_by(phone=phone_number).first()
    if not session:
        session = WhatsappSession(phone=phone_number, worker_id=user.id, state="idle", context_data="[]")
        db.session.add(session)
        db.session.commit()

    context = []
    if session.context_data:
        try:
            context = json.loads(session.context_data)
        except:
            pass
            
    if text_content.lower() in ("hacer registro", "nuevo registro", "hola", "reset"):
        context = []
        session.state = "idle"

    reply_text, extracted_data, new_context = process_whatsapp_message(context, text_content)
    
    session.context_data = json.dumps(new_context)
    session.last_interaction = datetime.utcnow()
    db.session.commit()

    if extracted_data:
        try:
            role = extracted_data.get("role", "operador").lower()
            
            # --- Buscar Unidad en la BD por nombre/código ---
            unit_id = None
            extracted_unit = extracted_data.get("unidad")
            if extracted_unit and str(extracted_unit).lower() != "null":
                unit = Unit.query.filter(
                    (Unit.code.ilike(f"%{extracted_unit}%")) |
                    (Unit.description.ilike(f"%{extracted_unit}%"))
                ).first()
                if unit:
                    unit_id = unit.id

            # --- Diesel ---
            liters = extracted_data.get("diesel_litros")
            try:
                liters = float(liters) if liters else None
            except:
                liters = None

            # --- Nombre del trabajador (del JSON, o fallback al user registrado) ---
            worker_name = extracted_data.get("nombre") or user.name

            # --- Servicio / Incidencia ---
            servicio = extracted_data.get("servicio_incidencia") or ""
            has_si = bool(servicio and servicio.strip().lower() not in ("sin incidencias", "sin novedad", "ninguno", ""))

            # --- Fecha ---
            fecha_str = extracted_data.get("fecha")
            log_date = datetime.utcnow()
            if fecha_str:
                try:
                    log_date = datetime.strptime(fecha_str, "%Y-%m-%d")
                except:
                    pass

            # --- Ruta ---
            ruta = extracted_data.get("ruta") or ""

            # --- Cantidad: horas (operador) o viajes (chofer) ---
            cantidad_raw = extracted_data.get("cantidad") or ""
            hours = None
            trips_text = None

            if role == "operador":
                # Extraer número de horas
                import re
                match = re.search(r"[\d\.]+", str(cantidad_raw))
                if match:
                    try:
                        hours = float(match.group())
                    except:
                        pass
            elif role == "chofer":
                trips_text = cantidad_raw  # ej: "3 viajes"

            # =============================================
            # LÓGICA POR ROL
            # =============================================

            if role == "gestor":
                # Gestor de Compras: solo crea FuelPurchase + log mínimo
                if liters and liters > 0:
                    fuel_purchase = FuelPurchase(
                        created_at=log_date,
                        provider=f"Dispersión WhatsApp — {worker_name}",
                        liters_bought=liters,
                        price_per_liter=0,
                        total_cost=0,
                        liters_dispersed=liters,  # ya dispersado a la unidad
                        registered_by_id=user.id,
                    )
                    db.session.add(fuel_purchase)

                new_log = OperatorLog(
                    worker_id=user.id,
                    worker_name=worker_name,
                    project_name="Dispersión de Diesel",
                    has_fuel=(liters is not None and liters > 0),
                    fuel_liters=liters,
                    main_unit_id=unit_id,
                    has_service_incident=False,
                    si_kind="servicio",
                    si_subtype="compras",
                    notes=f"Dispersión de diesel registrada vía WhatsApp. Unidad: {extracted_unit or 'N/A'}. Litros: {liters}L.",
                    created_at=log_date,
                )
                db.session.add(new_log)

            elif role == "chofer":
                full_notes = f"🚚 Viajes: {trips_text}\n📍 Ruta: {ruta}"
                if servicio:
                    full_notes += f"\n🔧 Servicio/Incidencia: {servicio}"

                new_log = OperatorLog(
                    worker_id=user.id,
                    worker_name=worker_name,
                    project_name=ruta or "Ruta no especificada",
                    has_fuel=(liters is not None and liters > 0),
                    fuel_liters=liters,
                    main_unit_id=unit_id,
                    route_other_origin=ruta,
                    has_service_incident=has_si,
                    si_kind="incidencia" if has_si else None,
                    si_subtype=servicio if has_si else None,
                    notes=full_notes,
                    created_at=log_date,
                )
                db.session.add(new_log)

            else:
                # Operador
                full_notes = f"📍 Ruta/Lugar: {ruta}"
                if servicio:
                    full_notes += f"\n🔧 Servicio/Incidencia: {servicio}"

                new_log = OperatorLog(
                    worker_id=user.id,
                    worker_name=worker_name,
                    project_name=ruta or "Lugar no especificado",
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

            # Limpiar sesión
            session.state = "idle"
            session.context_data = "[]"
            db.session.commit()

            reply_text = f"✅ Registro de *{role.capitalize()}* guardado exitosamente en el sistema EMEX."

        except Exception as e:
            print(f"Error al guardar log desde Whatsapp: {e}")
            reply_text = "❌ Hubo un error al intentar guardar tu registro en la base de datos."


    # Enviar respuesta al usuario (Evolution API v1 necesita solo el número, sin @s.whatsapp.net)
    send_whatsapp_message(phone_number, reply_text)

    return jsonify({"status": "success"}), 200
