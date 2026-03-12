import os
import json
from dotenv import load_dotenv

# Cargar variables (.env) antes de importar nuestro servicio
load_dotenv()

try:
    from emex.api.openai_service import process_whatsapp_message
except ImportError:
    print("Por favor ejecuta este script desde la raíz del proyecto (appRegistros)")
    exit(1)

def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ ERROR: No se encontró OPENAI_API_KEY en el archivo .env")
        print("Añade tu API key al archivo .env antes de probar.")
        return

    print("=========================================================")
    print("🤖 Simulador del Bot de WhatsApp (EMEX)")
    print("Escribe tus mensajes como si fueras el operador.")
    print("Escribe 'salir' para terminar o 'reiniciar' para borrar el contexto.")
    print("=========================================================")

    context = []

    while True:
        try:
            user_input = input("\n📱 Tú: ")
            
            if user_input.lower() in ('salir', 'exit', 'quit'):
                break
                
            if user_input.lower() in ('reiniciar', 'reset'):
                context = []
                print("🔄 [Contexto borrado]")
                continue

            if not user_input.strip():
                continue

            print("⏳ Pensando...")
            reply_text, extracted_data, new_context = process_whatsapp_message(context, user_input)
            
            context = new_context
            
            print(f"🤖 Bot: {reply_text}")
            
            if extracted_data:
                print("\n✅ ¡Datos Extraídos Exitosamente!")
                print(json.dumps(extracted_data, indent=2, ensure_ascii=False))
                print("\nAutomáticamente el sistema guardaría esto en la base de datos.")
                print("🔄 [Contexto borrado para un nuevo registro]")
                context = []

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
