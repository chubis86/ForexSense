import logging
import os
import sys

from data_fetcher import fetch_crypto, fetch_tradfi, get_day_open
from daily_filter import check_daily_limit, get_daily_movement_pct
from technical_analysis import (
    calculate_indicators_1h,
    detect_patterns,
    detect_setup,
    detect_sr_levels,
    get_4h_trend,
    get_market_session,
)
from signal_engine import analyze_asset
from notifier import send_signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

ASSETS = [
    {"name": "BTC/USDT", "source": "crypto", "symbol": "BTC/USDT"},
    {"name": "ETH/USDT", "source": "crypto", "symbol": "ETH/USDT"},
    {"name": "XAU/USD",  "source": "tradfi",  "ticker": "GC=F"},
    {"name": "EUR/USD",  "source": "tradfi",  "ticker": "EURUSD=X"},
]


def validate_secrets() -> None:
    required = ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        logger.error(f"Secrets faltantes: {', '.join(missing)}. Configúralos en GitHub Secrets.")
        sys.exit(1)


def process_asset(asset: dict) -> None:
    name = asset["name"]
    logger.info(f"--- Procesando {name} ---")

    try:
        # 1. Fetch data
        if asset["source"] == "crypto":
            df_1h = fetch_crypto(asset["symbol"], "1h")
            df_4h = fetch_crypto(asset["symbol"], "4h")
        else:
            df_1h = fetch_tradfi(asset["ticker"], "1h")
            df_4h = fetch_tradfi(asset["ticker"], "4h")

        if df_1h is None or df_4h is None:
            logger.info(f"{name}: datos no disponibles, saltando")
            return

        # 2. Day open & daily filter
        open_price = get_day_open(df_1h)
        if open_price is None:
            logger.warning(f"{name}: no se pudo obtener precio de apertura, saltando")
            return

        current_price = float(df_1h["close"].iloc[-1])
        daily_movement = get_daily_movement_pct(current_price, open_price)

        if not check_daily_limit(name, current_price, open_price):
            return

        logger.info(f"{name}: movimiento diario {daily_movement:+.2f}% — dentro del límite")

        # 3. Technical analysis
        indicators_1h = calculate_indicators_1h(df_1h)
        if indicators_1h is None:
            logger.info(f"{name}: indicadores no calculables, saltando")
            return

        trend_4h = get_4h_trend(df_4h)
        logger.info(f"{name}: tendencia 4H = {trend_4h}")

        setup_type, conditions_count = detect_setup(indicators_1h, trend_4h)
        if setup_type is None:
            logger.info(f"{name}: sin setup técnico detectado")
            return

        logger.info(f"{name}: {setup_type} con {conditions_count} condiciones TA")

        # 4. Pattern detection, S/R levels, session
        patterns = detect_patterns(df_1h)
        sr_levels = detect_sr_levels(df_1h)
        session = get_market_session()

        if patterns:
            logger.info(f"{name}: patrones detectados — {patterns}")
        logger.info(f"{name}: sesión de mercado = {session}")

        # 5. Claude confirmation
        result = analyze_asset(
            asset=name,
            price=current_price,
            indicators_1h=indicators_1h,
            trend_4h=trend_4h,
            setup_type=setup_type,
            conditions_count=conditions_count,
            daily_movement=daily_movement,
            patterns=patterns,
            session=session,
            sr_levels=sr_levels,
        )

        if result is None:
            logger.info(f"{name}: sin señal generada por Claude")
            return

        signal = result["signal"]
        strength = result["strength"]
        logger.info(f"{name}: Claude → {signal} ({strength}) — {result['reasoning']}")

        # 6. Send notification
        if signal != "NONE":
            send_signal(result)
        else:
            logger.info(f"{name}: Claude descartó el setup")

    except Exception as e:
        logger.error(f"{name}: error inesperado — {e}", exc_info=True)


def main() -> None:
    logger.info("=== ForexSense iniciando ===")
    validate_secrets()

    session = get_market_session()
    logger.info(f"Sesión de mercado actual: {session}")

    for asset in ASSETS:
        process_asset(asset)

    logger.info("=== ForexSense completado ===")


if __name__ == "__main__":
    main()
