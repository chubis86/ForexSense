"""
Ejecuta este script para verificar que el bot de Telegram funciona correctamente.
Uso: python test_telegram.py
Requiere: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en variables de entorno o en un archivo .env
"""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from telegram import Bot
from telegram.constants import ParseMode


def _load_dotenv() -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


async def send_test():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("ERROR: Define TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.")
        print("Crea un archivo .env en la raíz del proyecto con:")
        print("  TELEGRAM_BOT_TOKEN=123456:ABCdef...")
        print("  TELEGRAM_CHAT_ID=123456789")
        return

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    message = (
        "🟢 *SEÑAL DE COMPRA — BTC/USDT* (TEST)\n"
        "💰 Precio: `95840`\n"
        "🎯 Target: `97757` (+2%)\n"
        "🛑 Stop: `94882` (-1%)\n"
        "📊 RSI(1H): 38.2  |  MACD: cruce alcista\n"
        "📈 Tendencia 4H: alcista ✓\n"
        "⚡ Fuerza: ALTA ⚡\n"
        "📐 Patrón: bull flag\n"
        "🕐 Sesión: Overlap Londres-NY 🔥\n"
        f"🤖 ForexSense • {now}"
    )

    print(f"Enviando mensaje de prueba al chat {chat_id}...")
    bot = Bot(token=token)
    await bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)
    print("✓ Mensaje enviado. Revisa tu Telegram.")


asyncio.run(send_test())
