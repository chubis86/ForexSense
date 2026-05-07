import logging
import os
from datetime import datetime, timezone

from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


def format_message(signal_data: dict) -> str:
    asset = signal_data["asset"]
    price = signal_data["price"]
    signal = signal_data["signal"]
    strength = signal_data["strength"]
    trend_4h = signal_data["trend_4h"]
    indicators = signal_data["indicators_1h"]
    target = signal_data["target"]
    stop = signal_data["stop"]
    patterns = signal_data.get("patterns", [])
    session = signal_data.get("session", "")

    if signal == "BUY":
        emoji = "🟢"
        direction = "COMPRA"
        target_pct = "+2%"
        stop_pct = "-1%"
        trend_emoji = "📈"
    else:
        emoji = "🔴"
        direction = "VENTA"
        target_pct = "-2%"
        stop_pct = "+1%"
        trend_emoji = "📉"

    strength_map = {"HIGH": "ALTA ⚡", "MEDIUM": "MEDIA 🔸", "LOW": "BAJA"}
    strength_label = strength_map.get(strength, strength)

    rsi = round(indicators["rsi"], 1)
    macd_cross = indicators.get("macd_cross", "—")
    macd_desc = "cruce alcista" if macd_cross == "bullish" else "cruce bajista"

    trend_label = {"BULLISH": "alcista ✓", "BEARISH": "bajista ✓", "NEUTRAL": "neutral"}.get(trend_4h, trend_4h)

    now_utc = datetime.now(timezone.utc).strftime("%H:%M UTC")

    lines = [
        f"{emoji} *SEÑAL DE {direction} — {asset}*",
        f"💰 Precio: `{price:,.5g}`",
        f"🎯 Target: `{target:,.5g}` ({target_pct})",
        f"🛑 Stop: `{stop:,.5g}` ({stop_pct})",
        f"📊 RSI(1H): {rsi}  |  MACD: {macd_desc}",
        f"{trend_emoji} Tendencia 4H: {trend_label}",
        f"⚡ Fuerza: {strength_label}",
    ]

    if patterns:
        lines.append(f"📐 Patrón: {', '.join(patterns)}")

    if session:
        session_label = {
            "london_newyork_overlap": "Overlap Londres-NY 🔥",
            "london": "Sesión Londres",
            "new_york": "Sesión Nueva York",
            "tokyo": "Sesión Tokyo",
            "off_hours": "Fuera de sesión",
            "closed": "Mercado cerrado",
        }.get(session, session)
        lines.append(f"🕐 Sesión: {session_label}")

    # Trade execution result
    if "trade" in signal_data:
        trade = signal_data["trade"]
        if trade:
            lines.append(f"📋 *Ejecutado:* `{trade['lots']} lots`")
        else:
            lines.append("⚠️ *Error al ejecutar operación*")

    lines.append(f"🤖 ForexSense • {now_utc}")
    return "\n".join(lines)


async def send_message(text: str) -> None:
    try:
        bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
        await bot.send_message(
            chat_id=os.environ["TELEGRAM_CHAT_ID"],
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")


async def send_signal(signal_data: dict) -> None:
    strength = signal_data.get("strength", "LOW")
    if strength not in ("HIGH", "MEDIUM"):
        logger.info(f"{signal_data['asset']}: señal de baja confianza ({strength}), omitida")
        return

    try:
        message = format_message(signal_data)
        await send_message(message)
        logger.info(f"{signal_data['asset']}: señal {signal_data['signal']} ({strength}) enviada a Telegram")
    except Exception as e:
        logger.error(f"Error procesando señal para Telegram: {e}")
