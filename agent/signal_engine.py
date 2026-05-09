import asyncio
import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a professional forex and crypto trading analyst with 10+ years of experience.
You analyze pre-filtered technical setups and decide whether to confirm or reject a trading signal.

## Market knowledge you apply

### Forex market sessions (UTC)
- Tokyo (00:00-09:00): JPY pairs most active; lower volatility for EUR/USD
- London (07:00-16:00): Highest EUR/GBP volatility; trend often established here
- New York (13:00-22:00): USD moves; most important session for XAU/USD
- London-NY overlap (13:00-16:00): Maximum liquidity; best for breakout entries
- Off-hours: Avoid entries on EUR/USD and XAU/USD; spreads widen, moves are unreliable

### Asset correlations to consider
- EUR/USD moves INVERSE to DXY (dollar index); strong USD = lower EUR/USD
- XAU/USD (gold) rises when: USD weakens, risk-off sentiment, bond yields fall
- BTC/USDT correlates with risk appetite; falls with stock market selloffs
- ETH/USDT follows BTC directionally but with higher beta (moves more %)

### Common false signal scenarios to REJECT
- Volatile news candle: RSI spike not backed by volume continuity → reject
- Weekend gap fills: price returning to Friday close after weekend gap → reject
- Off-hours EUR/USD or XAU/USD breakout: low liquidity = false break → reject
- Counter-trend RSI divergence in strong trend: mean-reversion trap → downgrade to LOW

### Chart pattern confidence boost
When the context includes detected patterns, weight them as follows:
- double_top / double_bottom: strong reversal signal → boost confirmation if aligned with setup
- head_and_shoulders / inverse_head_and_shoulders: high-reliability reversal → strong confirmation
- bull_flag / bear_flag: high-probability continuation → confirm if breakout imminent
- ascending_triangle / descending_triangle: continuation bias → confirm breakout direction
- pennant: explosive move likely after breakout → confirm with momentum
- breakout_retest: highest confirmation value → strong entry signal

### Entry timing quality
- Setup during london_newyork_overlap = highest quality entry window
- Setup during london session = good
- Setup during tokyo = moderate (unless JPY pair)
- Setup during off_hours = reduce strength by one level (HIGH→MEDIUM, MEDIUM→LOW)

## Your output
Respond ONLY with valid JSON: {"signal": "BUY"|"SELL"|"NONE", "strength": "HIGH"|"MEDIUM"|"LOW", "reasoning": "<max 120 chars>"}
- signal: BUY, SELL, or NONE (if setup is weak or risky)
- strength: HIGH (strong confirmation), MEDIUM (probable), LOW (marginal — will not trigger notification)
- reasoning: brief English explanation of your decision"""


def build_prompt(
    asset: str,
    price: float,
    indicators_1h: dict,
    trend_4h: str,
    setup_type: str,
    daily_movement: float,
    patterns: list,
    session: str,
    sr_levels: dict,
) -> str:
    macd_cross = "bullish" if indicators_1h["macd"] > indicators_1h["macd_signal"] else "bearish"
    bb_pos = "near_lower" if indicators_1h["close"] <= indicators_1h["bb_lower"] * 1.01 else \
             "near_upper" if indicators_1h["close"] >= indicators_1h["bb_upper"] * 0.99 else "middle"

    context = {
        "asset": asset,
        "price": round(price, 6),
        "setup": setup_type,
        "daily_movement_pct": round(daily_movement, 2),
        "market_session": session,
        "trend_4h": trend_4h,
        "indicators_1h": {
            "rsi": round(indicators_1h["rsi"], 2),
            "macd_cross": macd_cross,
            "macd_histogram": round(indicators_1h["macd_hist"], 6),
            "bb_position": bb_pos,
            "ema20": round(indicators_1h["ema20"], 6),
            "ema50": round(indicators_1h["ema50"], 6),
        },
        "patterns": patterns,
        "support_nearby": sr_levels["support_nearby"],
        "support_level": sr_levels["support_level"],
        "resistance_nearby": sr_levels["resistance_nearby"],
        "resistance_level": sr_levels["resistance_level"],
        "breakout_retest": sr_levels["breakout_retest"],
        "retest_direction": sr_levels["retest_direction"],
    }
    return json.dumps(context, ensure_ascii=False)


def query_claude(prompt: str) -> dict | None:
    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        if not response.content or response.content[0].type != "text":
            logger.error("Respuesta Claude vacía o tipo inesperado")
            return None
        raw = response.content[0].text.strip()
        if not raw:
            logger.error("Respuesta Claude vacía")
            return None
        # Strip markdown code block if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        required = {"signal", "strength", "reasoning"}
        if not required.issubset(data.keys()):
            logger.error(f"Respuesta Claude con campos faltantes: {data}")
            return None
        if data["signal"] not in ("BUY", "SELL", "NONE"):
            logger.error(f"Valor signal inválido: {data['signal']}")
            return None
        if data["strength"] not in ("HIGH", "MEDIUM", "LOW"):
            logger.error(f"Valor strength inválido: {data['strength']}")
            return None
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Respuesta Claude no es JSON válido: {e}")
        return None
    except Exception as e:
        logger.error(f"Error consultando Claude: {e}")
        return None


def calculate_targets(price: float, signal: str) -> tuple[float, float]:
    if signal == "BUY":
        return round(price * 1.02, 6), round(price * 0.99, 6)
    return round(price * 0.98, 6), round(price * 1.01, 6)


async def analyze_asset(
    asset: str,
    price: float,
    indicators_1h: dict,
    trend_4h: str,
    setup_type: str,
    conditions_count: int,
    daily_movement: float,
    patterns: list,
    session: str,
    sr_levels: dict,
) -> dict | None:
    if conditions_count < 3:
        logger.info(f"{asset}: solo {conditions_count} condiciones TA (mínimo 3 para llamar a Claude)")
        return None

    prompt = build_prompt(asset, price, indicators_1h, trend_4h, setup_type, daily_movement, patterns, session, sr_levels)
    result = await asyncio.to_thread(query_claude, prompt)

    if result is None:
        return None

    target, stop = calculate_targets(price, result["signal"])
    return {
        "asset": asset,
        "price": price,
        "signal": result["signal"],
        "strength": result["strength"],
        "reasoning": result["reasoning"],
        "trend_4h": trend_4h,
        "indicators_1h": indicators_1h,
        "patterns": patterns,
        "session": session,
        "target": target,
        "stop": stop,
    }
