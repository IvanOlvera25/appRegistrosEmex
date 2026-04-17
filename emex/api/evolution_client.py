import os
import requests


def resolve_lid_to_phone(lid_jid):
    """
    Cuando WhatsApp envía un LID (Linked ID) como remoteJid,
    consultamos la API de contactos de Evolution para obtener el número real.
    Si no se puede resolver, devuelve None.
    """
    api_url = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    instance = os.getenv("EVOLUTION_INSTANCE", "")
    api_key = os.getenv("EVOLUTION_API_KEY", "")

    if not api_url or not instance or not api_key:
        return None

    headers = {"apikey": api_key, "Content-Type": "application/json"}

    # Intentar buscar el contacto por su LID en el store de Evolution API v1
    try:
        url = f"{api_url}/chat/findContacts/{instance}"
        resp = requests.post(url, json={"where": {"id": lid_jid}}, headers=headers, timeout=10)
        if resp.ok:
            contacts = resp.json()
            if isinstance(contacts, list) and len(contacts) > 0:
                contact = contacts[0]
                # El contacto puede tener un campo 'id' con @s.whatsapp.net
                contact_id = contact.get("id", "")
                if "@s.whatsapp.net" in contact_id:
                    return contact_id.split("@")[0]
    except Exception as e:
        print(f"Error al resolver LID {lid_jid}: {e}")

    return None


def send_whatsapp_message(phone, text):
    """
    Envía un mensaje usando Evolution API v1.8.2.
    Acepta un número de teléfono limpio (ej: 5214423444997).
    """
    api_url = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    instance = os.getenv("EVOLUTION_INSTANCE", "")
    api_key = os.getenv("EVOLUTION_API_KEY", "")

    if not api_url or not instance or not api_key:
        print("Faltan variables de entorno para Evolution API")
        return False

    # El endpoint para enviar texto
    url = f"{api_url}/message/sendText/{instance}"

    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }

    # Evolution API v1.8.2 format
    payload = {
        "number": phone,
        "options": {
            "delay": 1200,
            "presence": "composing"
        },
        "textMessage": {
            "text": text
        }
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"[WhatsApp Send] phone={phone}, status={resp.status_code}, body={resp.text[:200]}")
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Error al enviar WhatsApp a {phone}: {e}")
        return False
