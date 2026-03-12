import os
import requests

def send_whatsapp_message(phone, text):
    """
    Envía un mensaje usando Evolution API.
    Asegúrate de configurar EVOLUTION_API_URL, EVOLUTION_INSTANCE y EVOLUTION_API_KEY.
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
    
    # Evolution API usualmente espera el número con código de país, ej: "5215512345678"
    # El número provisto debe venir pre-formateado.
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
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error al enviar WhatsApp a {phone}: {e}")
        return False
