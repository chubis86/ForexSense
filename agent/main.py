import asyncio
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
from notifier import send_message, send_signal, send_closure_notification
from calendar_filter import fetch_high_impact_events, is_news_blackout
from trade_log import log_trade_open, log_trade_close, get_context_for_signal
from state import load_positions, save_positions
from trader import (
    DAILY_TARGET_PCT,
    DAILY_LOSS_PCT,
    MAX_OPEN_POSITIONS,
    SYMBOL_MAP,
    get_balance,
    get_daily_profit,
    get_unrealized_pnl,
    get_open_positions,
    get_open_positions_count,
    get_closed_deals_since,
    has_open_position,
    has_open_correlated_position,
    open_trade,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

ASSETS = [
    {"name": "BTC/USD",  "source": "crypto", "ticker": "BTC-USD"},
    {"name": "ETH/USD",  "source": "crypto", "ticker": "ETH-USD"},
    {"name": "XAU/USD",  "source": "tradfi", "ticker": "GC=F"},
    {"name": "EUR/USD",  "source": "tradfi", "ticker": "EURUSD=X"},
]

# Semaphore: allows parallel analysis but serializes actual trade opens
_trade_semaphore = asyncio.Semaphore(1)


def validate_secrets() -> None:
    required = (
        "ANTHROPIC_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "METAAPI_TOKEN",
        "METAAPI_ACCOUNT_ID",
    )
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        logger.error(f"Secrets faltantes: {', '.join(missing)}. Configúralos en GitHub Secrets.")
        sys.exit(1)


async def process_asset(asset: dict, trading_enabled: bool, balance: float, news_events: list) -> None:
    name = asset["name"]
    logger.info(f"--- Procesando {name} ---")

    try:
        # 1. Economic calendar blackout check
        if is_news_blackout(name, news_events):
            return

        # 2. Fetch data (run in thread to avoid blocking the event loop)
        fetch_fn = fetch_crypto if asset["source"] == "crypto" else fetch_tradfi
        df_1h = await asyncio.to_thread(fetch_fn, asset["ticker"], "1h")
        df_4h = await asyncio.to_thread(fetch_fn, asset["ticker"], "4h")

        if df_1h is None or df_4h is None:
            logger.info(f"{name}: datos no disponibles, saltando")
            return

        # 3. Day open & daily movement filter
        open_price = get_day_open(df_1h)
        if open_price is None:
            logger.warning(f"{name}: no se pudo obtener precio de apertura, saltando")
            return

        current_price = float(df_1h["close"].iloc[-1])
        daily_movement = get_daily_movement_pct(current_price, open_price)

        if not check_daily_limit(name, current_price, open_price):
            return

        logger.info(f"{name}: movimiento diario {daily_movement:+.2f}% — dentro del límite")

        # 4. Technical analysis
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

        # 5. Pattern detection, S/R levels, session
        patterns = detect_patterns(df_1h)
        sr_levels = detect_sr_levels(df_1h)
        session = get_market_session()

        if patterns:
            logger.info(f"{name}: patrones detectados — {patterns}")
        logger.info(f"{name}: sesión de mercado = {session}")

        # 6. Claude confirmation
        result = await analyze_asset(
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

        if signal == "NONE":
            logger.info(f"{name}: Claude descartó el setup")
            return

        # 7. Execute trade (semaphore prevents concurrent opens exceeding MAX_OPEN_POSITIONS)
        symbol = SYMBOL_MAP.get(name)
        atr = indicators_1h.get("atr")
        if trading_enabled and symbol:
            async with _trade_semaphore:
                already_open = await has_open_position(symbol)
                if already_open:
                    logger.info(f"{name}: ya hay una posición abierta, omitiendo")
                    return
                correlated_open = await has_open_correlated_position(symbol)
                if correlated_open:
                    logger.info(f"{name}: activo correlacionado ya tiene posición abierta, omitiendo")
                    return
                current_open = await get_open_positions_count()
                if current_open >= MAX_OPEN_POSITIONS:
                    logger.info(f"{name}: máximo de posiciones ({MAX_OPEN_POSITIONS}) alcanzado, omitiendo")
                    return
                trade_result = await open_trade(symbol, signal, current_price, balance, atr=atr)
                result["trade"] = trade_result
                if trade_result:
                    # Find the new position ID to associate with this signal
                    new_positions = await get_open_positions()
                    new_pos = next((p for p in new_positions if p.get("symbol") == symbol), None)
                    pos_id = str(new_pos.get("id", symbol)) if new_pos else symbol
                    log_trade_open(pos_id, result, trade_result)
        else:
            logger.warning(f"{name}: MetaAPI no disponible — señal sin ejecutar")

        # 8. Notify via Telegram
        await send_signal(result)

    except Exception as e:
        logger.error(f"{name}: error inesperado — {e}", exc_info=True)


async def check_closed_positions() -> list:
    """Detects positions closed since last run, sends notifications, returns current positions."""
    prev_positions = load_positions()
    current_positions = await get_open_positions()

    if prev_positions:
        current_ids = {str(p.get("id", "")) for p in current_positions}
        closed = [p for p in prev_positions if str(p.get("id", "")) not in current_ids]
        if closed:
            logger.info(f"{len(closed)} posición(es) cerrada(s) desde la última ejecución")
            deals = await get_closed_deals_since(minutes=90)
            deals_by_pos = {str(d.get("positionId", "")): d for d in deals}
            for pos in closed:
                pos_id = str(pos.get("id", ""))
                deal = deals_by_pos.get(pos_id)
                if deal:
                    await send_closure_notification(deal, pos)
                    log_trade_close(pos_id, deal)
                else:
                    logger.info(f"Posición {pos.get('symbol')} cerrada — deal no encontrado en historial reciente")

    return current_positions


async def main() -> None:
    logger.info("=== ForexSense iniciando ===")
    validate_secrets()

    # Detect closures and immediately persist current state to prevent duplicate notifications
    try:
        snapshot = await check_closed_positions()
        save_positions(snapshot)
    except Exception as e:
        logger.error(f"Error verificando posiciones cerradas: {e}")

    # Get account state via MetaAPI REST
    balance = 0.0
    trading_enabled = True
    try:
        balance = await get_balance()
        realized_pnl = await get_daily_profit()
        unrealized_pnl = await get_unrealized_pnl()
        daily_profit = realized_pnl + unrealized_pnl
        daily_pct = (daily_profit / balance * 100) if balance > 0 else 0
        logger.info(
            f"Balance: {balance:.2f} | P&L hoy: {daily_profit:+.2f} ({daily_pct:+.2f}%) "
            f"[realizado: {realized_pnl:+.2f}, no realizado: {unrealized_pnl:+.2f}]"
        )

        if daily_pct >= DAILY_TARGET_PCT * 100:
            logger.info(f"Meta diaria del {DAILY_TARGET_PCT*100:.1f}% alcanzada. Sin nuevas operaciones.")
            await send_message(
                f"✅ *Meta diaria alcanzada*\n"
                f"Ganancia: `+{daily_pct:.2f}%` (`+{daily_profit:.2f} USD`)\n"
                f"No se abrirán más posiciones hoy."
            )
            return

        if daily_pct <= -(DAILY_LOSS_PCT * 100):
            logger.info(f"Límite de pérdida diaria del {DAILY_LOSS_PCT*100:.0f}% alcanzado. Sin nuevas operaciones.")
            await send_message(
                f"🛑 *Límite de pérdida diaria alcanzado*\n"
                f"Pérdida: `{daily_pct:.2f}%` (`{daily_profit:.2f} USD`)\n"
                f"No se abrirán más posiciones hoy."
            )
            return

    except Exception as e:
        logger.error(f"Error consultando MetaAPI: {e}")
        trading_enabled = False

    session = get_market_session()
    logger.info(f"Sesión de mercado actual: {session}")

    if trading_enabled:
        open_count = await get_open_positions_count()
        logger.info(f"Posiciones abiertas: {open_count}/{MAX_OPEN_POSITIONS}")
        if open_count >= MAX_OPEN_POSITIONS:
            logger.info(f"Máximo de {MAX_OPEN_POSITIONS} posiciones simultáneas alcanzado. Sin nuevas operaciones.")
            return

    # Fetch economic calendar once — shared across all assets
    news_events = await fetch_high_impact_events()

    await asyncio.gather(*[
        process_asset(asset, trading_enabled, balance, news_events)
        for asset in ASSETS
    ])

    # Update state again to capture any newly opened positions this run
    if trading_enabled:
        try:
            save_positions(await get_open_positions())
        except Exception as e:
            logger.error(f"Error actualizando estado de posiciones: {e}")

    logger.info("=== ForexSense completado ===")


if __name__ == "__main__":
    asyncio.run(main())
