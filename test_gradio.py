import os
import json
import gradio as gr
from dotenv import load_dotenv

# Cargar variables (.env)
load_dotenv()

try:
    from emex.api.openai_service import process_whatsapp_message
except ImportError:
    print("Error: Por favor ejecuta este script desde la raíz del proyecto (appRegistros)")
    exit(1)

# Variable global para mantener el contexto de la sesión actual
chat_context = []

def chat_logic(user_message, history):
    global chat_context
    
    if not os.getenv("OPENAI_API_KEY"):
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": "❌ **ERROR:** No se encontró `OPENAI_API_KEY` en el archivo `.env`. Por favor, configúralo primero."})
        return history, ""
    
    if user_message.strip().lower() in ('reiniciar', 'reset'):
        chat_context = []
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": "🔄 **Contexto borrado.** Listo para un nuevo registro. ¿Eres Operador, Chofer o Gestor de Compras?"})
        return history, ""
        
    reply_text, extracted_data, new_context = process_whatsapp_message(chat_context, user_message)
    chat_context = new_context
    
    final_reply = reply_text
    
    if extracted_data:
        json_str = json.dumps(extracted_data, indent=2, ensure_ascii=False)
        final_reply += f"\n\n✅ **¡Datos Extraídos Exitosamente!**\n```json\n{json_str}\n```\n\n*(Automáticamente el sistema guardaría esto en la DB. El contexto se ha reiniciado para un nuevo registro).* \n\n¿Quieres registrar algo más? Empieza diciéndome tu rol."
        chat_context = []
        
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": final_reply})
    
    return history, ""

def clear_context():
    global chat_context
    chat_context = []
    return []

with gr.Blocks(title="Simulador Bot EMEX") as demo:
    gr.Markdown("# 🤖 Simulador del Bot de WhatsApp (EMEX)")
    gr.Markdown("Escribe como si fueras el trabajador por WhatsApp. Para empezar un nuevo registro desde cero en cualquier momento, escribe **reiniciar**. **Recuerda:** Necesitas tener `OPENAI_API_KEY` definido en tu archivo `.env`.")
    
    chatbot = gr.Chatbot(label="Chat de WhatsApp", height=500)
    
    with gr.Row():
        msg = gr.Textbox(placeholder="Escribe tu mensaje aquí y presiona Enter...", label="Tu mensaje", scale=8)
        submit_btn = gr.Button("Enviar", variant="primary", scale=1)
        
    clear = gr.Button("🗑️ Reiniciar Registro Completo", variant="secondary")
    
    # Eventos
    msg.submit(chat_logic, [msg, chatbot], [chatbot, msg])
    submit_btn.click(chat_logic, [msg, chatbot], [chatbot, msg])
    clear.click(clear_context, None, chatbot, queue=False)

if __name__ == "__main__":
    print("🚀 Iniciando interfaz gráfica de pruebas en http://127.0.0.1:7860")
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False, theme=gr.themes.Soft(primary_hue="blue"))
