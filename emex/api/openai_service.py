import os
import json
from openai import OpenAI

# Inicializar cliente OpenAI
# Asegúrate de poner OPENAI_API_KEY en tu archivo .env
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
Eres el asistente virtual experto de EMEX para capturar bitácoras de trabajo diarias vía WhatsApp. 
Tu objetivo es registrar las actividades de los empleados. 
El sistema maneja 3 roles distintos: Operador, Chofer y Gestor de Compras. 

## REGLAS PRINCIPALES:
1. SI NO SABES EL ROL DEL USUARIO: Lo primero que debes hacer es saludar y preguntar: "¿Eres Operador, Chofer o Gestor de Compras?".
2. UNA VEZ QUE CONOCES EL ROL: Debes pedirle los DATOS OBLIGATORIOS para su rol de forma amigable.
3. Si en algún momento tienes TODOS los datos obligatorios, no pidas más información. Si tienes todos los obligatorios, genera EXCLUSIVAMENTE el JSON final.

## DATOS POR ROL:

### 👷 OPERADOR
- **Obligatorio**:
  - Nombre del operador
  - Número de máquina / unidad
  - Diesel cargado (litros)
  - Cantidad de horas trabajadas
  - Servicio o incidencia (ej: "inyección a unidad", "mantenimiento", "sin incidencias")
  - Fecha
  - Ruta o lugar de trabajo

### 🚚 CHOFER
- **Obligatorio**:
  - Nombre del chofer
  - Número de camión / unidad
  - Diesel cargado (litros)
  - Cantidad de viajes realizados
  - Servicio o incidencia (ej: "inyección a unidad", "sin novedad")
  - Fecha
  - Ruta (origen y/o destino de los viajes)

### 🛒 GESTOR DE COMPRAS (solo dispersión de diesel)
- **Obligatorio**:
  - Nombre de quien realizó la dispersión
  - Máquina o unidad que recibió el diesel
  - Cantidad de litros de diesel

## CÓMO PREGUNTAR:
- Haz las preguntas de forma natural y conversacional. Puedes pedir varios datos en un mismo mensaje.
- Para Operador/Chofer: si no te dieron el dato de diesel, servicio o ruta, pregunta específicamente por esos campos.
- Para Gestor de Compras: SOLO necesitas los 3 campos mencionados. No preguntes por horas, viajes ni rutas.

## FORMATO DE RESPUESTA FINAL (SOLO CUANDO ESTÉ COMPLETO):
Cuando tengas toda la información OBLIGATORIA para el rol identificado, DEBES responder ÚNICAMENTE con un bloque JSON.
El bloque JSON DEBE empezar con `{` y terminar con `}` sin texto adicional antes ni después.

Estructura del JSON para OPERADOR o CHOFER:
{
  "complete": true,
  "role": "operador" | "chofer",
  "nombre": "Nombre del operador o chofer",
  "unidad": "Número o nombre de la máquina/camión",
  "diesel_litros": 50.0,
  "cantidad": "X horas" | "X viajes",
  "servicio_incidencia": "Descripción del servicio o incidencia",
  "fecha": "YYYY-MM-DD",
  "ruta": "Ruta o lugar de trabajo"
}

Estructura del JSON para GESTOR DE COMPRAS:
{
  "complete": true,
  "role": "gestor",
  "nombre": "Nombre de quien realizó la dispersión",
  "unidad": "Máquina o unidad que recibió el diesel",
  "diesel_litros": 50.0
}
"""

def process_whatsapp_message(session_context, new_message):
    """
    Toma el contexto de la sesión (historial de mensajes) y el nuevo mensaje.
    Retorna (nueva_respuesta, datos_extraidos_json)
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if session_context:
        messages.extend(session_context)
        
    messages.append({"role": "user", "content": new_message})
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2
        )
        
        reply_content = response.choices[0].message.content.strip()
        
        # Verificar si la respuesta es el JSON de completado
        if reply_content.startswith("{") and reply_content.endswith("}"):
            try:
                extracted_data = json.loads(reply_content)
                if extracted_data.get("complete"):
                    return ("¡Registro procesado! Estoy guardando la información...", extracted_data, messages)
            except Exception as e:
                pass # Falló al parsear el JSON, lo tratamos como respuesta de texto
                
        # Si no fue JSON o faltan datos, agregamos la respuesta al historial
        messages.append({"role": "assistant", "content": reply_content})
        return (reply_content, None, messages[1:]) # Retornamos sin el system prompt
        
    except Exception as e:
        print(f"Error procesando con OpenAI: {e}")
        return ("Ocurrió un error al procesar tu mensaje con la IA. Inténtalo más tarde.", None, session_context)
