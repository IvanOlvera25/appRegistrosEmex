# emex/api/routes.py
import json
import time
from datetime import datetime
from flask import Blueprint, request, jsonify

from ..extensions import db
from ..models import User, WhatsappSession, OperatorLog, Unit, FuelPurchase
from .evolution_client import send_whatsapp_message
from .openai_service import process_whatsapp_message

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Deduplicación: cache de IDs de mensajes ya procesados (evita respuestas duplicadas)
_processed_msg_ids = {}
_DEDUP_TTL = 120  # segundos que un ID se mantiene en cache

def _is_duplicate(msg_id):
    """Retorna True si el mensaje ya fue procesado. Lo marca como procesado."""
    if not msg_id:
        return False
    now = time.time()
    # Limpiar entradas viejas
    expired = [k for k, v in _processed_msg_ids.items() if now - v > _DEDUP_TTL]
    for k in expired:
        del _processed_msg_ids[k]
    if msg_id in _processed_msg_ids:
        return True
    _processed_msg_ids[msg_id] = now
    return False

@api_bp.route("/webhook/evolution", methods=["POST"])
def evolution_webhook():
    data = request.json
    
    event_type = data.get("event", "")
    
    # WAHA usa "message", Evolution API usa "messages.upsert" / "MESSAGES_UPSERT"
    is_waha = event_type == "message"
    is_evolution = event_type in ["messages.upsert", "MESSAGES_UPSERT"]
    
    if not is_waha and not is_evolution:
        return jsonify({"status": "ignored", "reason": f"not a message event ({event_type})"}), 200
    
    if is_waha:
        # WAHA format: {"event": "message", "payload": {...}}
        payload = data.get("payload", {})
        from_me = payload.get("fromMe", False)
        if from_me:
            return jsonify({"status": "ignored", "reason": "sent by me"}), 200
        
        # chat_id es el identificador completo (puede ser LID o @c.us)
        chat_id = payload.get("from", "")
        msg_id = payload.get("id", {}).get("id", "") if isinstance(payload.get("id"), dict) else payload.get("id", "")
        
        # Deduplicación
        if _is_duplicate(msg_id):
            return jsonify({"status": "ignored", "reason": "duplicate"}), 200
        
        # Ignorar grupos
        if "@g.us" in chat_id:
            return jsonify({"status": "ignored", "reason": "group message"}), 200
        
        phone_number = chat_id.split("@")[0]
        text_content = (payload.get("body") or "").strip()
        
        print(f"[WAHA Webhook] from={chat_id}, msgId={msg_id}, text={text_content[:50]}")
    else:
        # Evolution API format (backwards compat)
        inner_data = data.get("data", {}) if "data" in data else data
        remote_jid = inner_data.get("key", {}).get("remoteJid", "")
        from_me = inner_data.get("key", {}).get("fromMe", False)
        
        if "@g.us" in remote_jid:
            return jsonify({"status": "ignored", "reason": "group message"}), 200
        if from_me:
            return jsonify({"status": "ignored", "reason": "sent by me"}), 200
        
        chat_id = remote_jid
        phone_number = remote_jid.split("@")[0]
        
        msg_obj = inner_data.get("message", {})
        text_content = (
            msg_obj.get("conversation") or 
            msg_obj.get("extendedTextMessage", {}).get("text") or 
            ""
        ).strip()
    
    if not text_content:
        return jsonify({"status": "ignored", "reason": "empty text"}), 200

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
                # Gestor de Compras — soporta una o varias unidades
                dispersiones = extracted_data.get("dispersiones")
                if dispersiones and isinstance(dispersiones, list):
                    # Multi-unidad
                    for disp in dispersiones:
                        d_unit_name = disp.get("unidad", "")
                        d_liters = None
                        try:
                            d_liters = float(disp.get("diesel_litros", 0))
                        except:
                            pass

                        d_unit_id = None
                        if d_unit_name:
                            u = Unit.query.filter(
                                (Unit.code.ilike(f"%{d_unit_name}%")) |
                                (Unit.description.ilike(f"%{d_unit_name}%"))
                            ).first()
                            if u:
                                d_unit_id = u.id

                        if d_liters and d_liters > 0:
                            fp = FuelPurchase(
                                created_at=datetime.utcnow(),
                                provider=f"Dispersión WhatsApp — {worker_name}",
                                liters_bought=d_liters,
                                price_per_liter=0,
                                total_cost=0,
                                liters_dispersed=d_liters,
                                registered_by_id=user.id,
                            )
                            db.session.add(fp)

                        new_log = OperatorLog(
                            worker_id=user.id,
                            worker_name=worker_name,
                            project_name="Dispersión de Diesel",
                            has_fuel=(d_liters is not None and d_liters > 0),
                            fuel_liters=d_liters,
                            main_unit_id=d_unit_id,
                            has_service_incident=False,
                            si_kind="servicio",
                            si_subtype="compras",
                            notes=f"Dispersión de diesel vía WhatsApp. Unidad: {d_unit_name}. Litros: {d_liters}L.",
                            created_at=datetime.utcnow(),
                        )
                        db.session.add(new_log)
                    print(f"[Gestor Multi] {len(dispersiones)} dispersiones registradas por {worker_name}")
                else:
                    # Una sola unidad (formato original)
                    if liters and liters > 0:
                        fuel_purchase = FuelPurchase(
                            created_at=datetime.utcnow(),
                            provider=f"Dispersión WhatsApp — {worker_name}",
                            liters_bought=liters,
                            price_per_liter=0,
                            total_cost=0,
                            liters_dispersed=liters,
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
                        notes=f"Dispersión de diesel vía WhatsApp. Unidad: {extracted_unit or 'N/A'}. Litros: {liters}L.",
                        created_at=datetime.utcnow(),
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

            # reply_text ya viene del openai_service con el mensaje de éxito
            print(f"[Registro OK] Rol={role}, Nombre={worker_name}, Unidad={extracted_unit}")

        except Exception as e:
            print(f"Error al guardar log desde Whatsapp: {e}")
            import traceback
            traceback.print_exc()
            reply_text = "❌ Hubo un error al intentar guardar tu registro en la base de datos."


    # Enviar respuesta al usuario usando el chat_id completo (soporta LID en WAHA)
    print(f"[WhatsApp Reply] Sending to chat_id={chat_id}")
    send_whatsapp_message(chat_id, reply_text)

    return jsonify({"status": "success"}), 200
