import os
import requests


def send_whatsapp_message(chat_id, text):
    """
    Envía un mensaje usando WAHA (WhatsApp HTTP API).
    chat_id puede ser un LID (ej: 280147848630492@lid) o un número (ej: 5214642020177@c.us)
    """
    api_url = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    api_key = os.getenv("EVOLUTION_API_KEY", "")

    if not api_url or not api_key:
        print("Faltan variables de entorno para WAHA")
        return False

    url = f"{api_url}/api/sendText"

    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json"
    }

    # Si el chat_id no tiene sufijo, agregar @c.us
    if "@" not in chat_id:
        chat_id = f"{chat_id}@c.us"

    payload = {
        "chatId": chat_id,
        "text": text,
        "session": "default"
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"[WAHA Send] chatId={chat_id}, status={resp.status_code}, body={resp.text[:200]}")
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Error al enviar WhatsApp a {chat_id}: {e}")
        return False
