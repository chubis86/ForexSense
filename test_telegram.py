"""
Ejecuta este script para verificar que el bot de Telegram funciona correctamente.
Uso: python test_telegram.py
Requiere: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID como variables de entorno
  o crea un archivo .env con esos valores y descomenta las líneas de dotenv.
"""
import asyncio
import os
from datetime import datetime, timezone

# Si tienes un archivo .env local, descomenta estas dos líneas:
# from dotenv import load_dotenv
# load_dotenv()

from telegram import Bot
from telegram.constants import ParseMode


async def send_test():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("ERROR: Define TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID como variables de entorno.")
        print("Ejemplo:")
        print('  set TELEGRAM_BOT_TOKEN=123456:ABCdef...')
        print('  set TELEGRAM_CHAT_ID=123456789')
        return

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    message = (
        "🟢 *SEÑAL DE COMPRA — BTC/USDT* \\[TEST\\]\n"
        "💰 Precio: `95,840`\n"
        "🎯 Target: `97,757` (+2%)\n"
        "🛑 Stop: `94,882` (-1%)\n"
        "📊 RSI(1H): 38.2  |  MACD: cruce alcista\n"
        "📈 Tendencia 4H: alcista ✓\n"
        "⚡ Fuerza: ALTA ⚡\n"
        "📐 Patrón: bull\\_flag\n"
        "🕐 Sesión: Overlap Londres-NY 🔥\n"
        f"🤖 ForexSense • {now}"
    )

    print(f"Enviando mensaje de prueba al chat {chat_id}...")
    bot = Bot(token=token)
    await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)
    print("✓ Mensaje enviado. Revisa tu Telegram.")


asyncio.run(send_test())
