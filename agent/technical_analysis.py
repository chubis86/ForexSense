import logging
from datetime import datetime, timezone

import pandas as pd
import ta as ta_lib

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def calculate_indicators_1h(df: pd.DataFrame) -> dict | None:
    if len(df) < 50:
        logger.warning(f"Datos insuficientes: {len(df)} velas (mínimo 50)")
        return None

    close = df["close"]

    rsi_series = ta_lib.momentum.RSIIndicator(close=close, window=14).rsi().dropna()
    macd_obj = ta_lib.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_series = macd_obj.macd().dropna()
    macd_signal_series = macd_obj.macd_signal().dropna()
    macd_hist_series = macd_obj.macd_diff().dropna()
    bb = ta_lib.volatility.BollingerBands(close=close, window=20, window_dev=2)
    ema20_series = ta_lib.trend.EMAIndicator(close=close, window=20).ema_indicator().dropna()
    ema50_series = ta_lib.trend.EMAIndicator(close=close, window=50).ema_indicator().dropna()

    if any(len(s) < 2 for s in [rsi_series, macd_series, macd_signal_series, ema20_series, ema50_series]):
        logger.warning("Datos insuficientes tras calcular indicadores")
        return None

    return {
        "rsi": float(rsi_series.iloc[-1]),
        "macd": float(macd_series.iloc[-1]),
        "macd_signal": float(macd_signal_series.iloc[-1]),
        "macd_hist": float(macd_hist_series.iloc[-1]),
        "macd_prev": float(macd_series.iloc[-2]),
        "macd_signal_prev": float(macd_signal_series.iloc[-2]),
        "bb_lower": float(bb.bollinger_lband().iloc[-1]),
        "bb_mid": float(bb.bollinger_mavg().iloc[-1]),
        "bb_upper": float(bb.bollinger_hband().iloc[-1]),
        "ema20": float(ema20_series.iloc[-1]),
        "ema50": float(ema50_series.iloc[-1]),
        "close": float(close.iloc[-1]),
    }


def get_4h_trend(df_4h: pd.DataFrame) -> str:
    if len(df_4h) < 50:
        return "NEUTRAL"

    close = df_4h["close"]
    ema20_s = ta_lib.trend.EMAIndicator(close=close, window=20).ema_indicator().dropna()
    ema50_s = ta_lib.trend.EMAIndicator(close=close, window=50).ema_indicator().dropna()
    macd_hist_s = ta_lib.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9).macd_diff().dropna()

    if any(len(s) < 1 for s in [ema20_s, ema50_s, macd_hist_s]):
        return "NEUTRAL"

    ema20 = float(ema20_s.iloc[-1])
    ema50 = float(ema50_s.iloc[-1])
    macd_hist = float(macd_hist_s.iloc[-1])

    bullish = ema20 > ema50 and macd_hist > 0
    bearish = ema20 < ema50 and macd_hist < 0

    if bullish:
        return "BULLISH"
    if bearish:
        return "BEARISH"
    return "NEUTRAL"


def _bb_position(price: float, bb_lower: float, bb_upper: float) -> str:
    if price <= bb_lower * 1.01:
        return "near_lower"
    if price >= bb_upper * 0.99:
        return "near_upper"
    return "middle"


def detect_setup(indicators: dict, trend_4h: str) -> tuple[str | None, int]:
    """Returns (setup_type, conditions_count). setup_type is None if no setup."""
    buy_conds = 0
    sell_conds = 0

    # RSI extremes
    if indicators["rsi"] < 35:
        buy_conds += 1
    elif indicators["rsi"] > 65:
        sell_conds += 1

    # MACD crossover
    if indicators["macd_prev"] < indicators["macd_signal_prev"] and indicators["macd"] >= indicators["macd_signal"]:
        buy_conds += 1
    elif indicators["macd_prev"] > indicators["macd_signal_prev"] and indicators["macd"] <= indicators["macd_signal"]:
        sell_conds += 1

    # Bollinger position
    bb_pos = _bb_position(indicators["close"], indicators["bb_lower"], indicators["bb_upper"])
    if bb_pos == "near_lower":
        buy_conds += 1
    elif bb_pos == "near_upper":
        sell_conds += 1

    if buy_conds >= 2:
        setup_type, count = "setup_buy", buy_conds
    elif sell_conds >= 2:
        setup_type, count = "setup_sell", sell_conds
    else:
        return None, 0

    # Counter-trend rejection
    if setup_type == "setup_buy" and trend_4h == "BEARISH":
        logger.info("Setup buy rechazado: contra-tendencia (4H BEARISH)")
        return None, 0
    if setup_type == "setup_sell" and trend_4h == "BULLISH":
        logger.info("Setup sell rechazado: contra-tendencia (4H BULLISH)")
        return None, 0

    return setup_type, count


# ---------------------------------------------------------------------------
# Support / Resistance
# ---------------------------------------------------------------------------

def _find_swing_highs(high: pd.Series, window: int = 3) -> list:
    arr = high.values
    result = []
    for i in range(window, len(arr) - window):
        if arr[i] == max(arr[i - window: i + window + 1]):
            result.append((i, float(arr[i])))
    return result


def _find_swing_lows(low: pd.Series, window: int = 3) -> list:
    arr = low.values
    result = []
    for i in range(window, len(arr) - window):
        if arr[i] == min(arr[i - window: i + window + 1]):
            result.append((i, float(arr[i])))
    return result


def _cluster_levels(swings: list, tolerance: float = 0.003) -> list:
    """Group nearby price levels; return those with 2+ touches."""
    levels: list[dict] = []
    for _, val in swings:
        placed = False
        for lev in levels:
            if abs(val - lev["price"]) / lev["price"] < tolerance:
                n = lev["count"]
                lev["price"] = (lev["price"] * n + val) / (n + 1)
                lev["count"] += 1
                placed = True
                break
        if not placed:
            levels.append({"price": val, "count": 1})
    return [l for l in levels if l["count"] >= 2]


def detect_sr_levels(df: pd.DataFrame) -> dict:
    result = {
        "support_nearby": False,
        "resistance_nearby": False,
        "breakout_retest": False,
        "support_level": None,
        "resistance_level": None,
        "retest_direction": None,
    }

    window = min(50, len(df))
    if window < 20:
        return result

    df_w = df.tail(window).reset_index(drop=True)
    current_price = float(df_w["close"].iloc[-1])
    proximity = 0.005

    swing_highs = _find_swing_highs(df_w["high"])
    swing_lows = _find_swing_lows(df_w["low"])

    res_levels = _cluster_levels(swing_highs)
    sup_levels = _cluster_levels(swing_lows)

    for lev in sorted(res_levels, key=lambda x: abs(x["price"] - current_price)):
        if abs(current_price - lev["price"]) / lev["price"] < proximity:
            result["resistance_nearby"] = True
            result["resistance_level"] = round(lev["price"], 6)
            break

    for lev in sorted(sup_levels, key=lambda x: abs(x["price"] - current_price)):
        if abs(current_price - lev["price"]) / lev["price"] < proximity:
            result["support_nearby"] = True
            result["support_level"] = round(lev["price"], 6)
            break

    # Breakout retest: level crossed in last 3 candles, now retesting
    all_level_prices = [l["price"] for l in res_levels + sup_levels]
    if len(df_w) >= 6:
        closes = df_w["close"].values
        for level_price in all_level_prices:
            for break_idx in (-4, -3):
                pre = closes[break_idx - 1]
                post = closes[break_idx]
                if pre < level_price < post and abs(current_price - level_price) / level_price < proximity:
                    result["breakout_retest"] = True
                    result["retest_direction"] = "bullish_retest"
                    break
                if post < level_price < pre and abs(current_price - level_price) / level_price < proximity:
                    result["breakout_retest"] = True
                    result["retest_direction"] = "bearish_retest"
                    break
            if result["breakout_retest"]:
                break

    return result


# ---------------------------------------------------------------------------
# Chart Patterns
# ---------------------------------------------------------------------------

def _is_double_top(df_w: pd.DataFrame, swing_highs: list, close: float) -> bool:
    if len(swing_highs) < 2:
        return False
    h1_idx, h1 = swing_highs[-2]
    h2_idx, h2 = swing_highs[-1]
    if h2_idx <= h1_idx:
        return False
    if abs(h1 - h2) / h1 > 0.003:
        return False
    valley = float(df_w["low"].iloc[h1_idx: h2_idx + 1].min())
    if (min(h1, h2) - valley) / min(h1, h2) < 0.01:
        return False
    return close < h2 * 0.997


def _is_double_bottom(df_w: pd.DataFrame, swing_lows: list, close: float) -> bool:
    if len(swing_lows) < 2:
        return False
    l1_idx, l1 = swing_lows[-2]
    l2_idx, l2 = swing_lows[-1]
    if l2_idx <= l1_idx:
        return False
    if abs(l1 - l2) / l1 > 0.003:
        return False
    peak = float(df_w["high"].iloc[l1_idx: l2_idx + 1].max())
    if (peak - max(l1, l2)) / max(l1, l2) < 0.01:
        return False
    return close > l2 * 1.003


def _is_head_and_shoulders(df_w: pd.DataFrame, swing_highs: list, close: float) -> bool:
    if len(swing_highs) < 3:
        return False
    ls_idx, ls = swing_highs[-3]
    h_idx, h = swing_highs[-2]
    rs_idx, rs = swing_highs[-1]
    if not (h > ls and h > rs):
        return False
    if abs(ls - rs) / ls > 0.01:
        return False
    neckline = (
        float(df_w["low"].iloc[ls_idx: h_idx + 1].min())
        + float(df_w["low"].iloc[h_idx: rs_idx + 1].min())
    ) / 2
    return close < neckline * 1.002


def _is_inverse_head_and_shoulders(df_w: pd.DataFrame, swing_lows: list, close: float) -> bool:
    if len(swing_lows) < 3:
        return False
    ls_idx, ls = swing_lows[-3]
    h_idx, h = swing_lows[-2]
    rs_idx, rs = swing_lows[-1]
    if not (h < ls and h < rs):
        return False
    if abs(ls - rs) / ls > 0.01:
        return False
    neckline = (
        float(df_w["high"].iloc[ls_idx: h_idx + 1].max())
        + float(df_w["high"].iloc[h_idx: rs_idx + 1].max())
    ) / 2
    return close > neckline * 0.998


def _is_ascending_triangle(swing_highs: list, swing_lows: list) -> bool:
    recent_highs = [v for _, v in swing_highs[-3:]]
    recent_lows = [v for _, v in swing_lows[-3:]]
    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return False
    avg_high = sum(recent_highs) / len(recent_highs)
    flat_resistance = all(abs(h - avg_high) / avg_high <= 0.003 for h in recent_highs)
    rising_lows = all(recent_lows[i] < recent_lows[i + 1] for i in range(len(recent_lows) - 1))
    return flat_resistance and rising_lows


def _is_descending_triangle(swing_highs: list, swing_lows: list) -> bool:
    recent_highs = [v for _, v in swing_highs[-3:]]
    recent_lows = [v for _, v in swing_lows[-3:]]
    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return False
    falling_highs = all(recent_highs[i] > recent_highs[i + 1] for i in range(len(recent_highs) - 1))
    avg_low = sum(recent_lows) / len(recent_lows)
    flat_support = all(abs(l - avg_low) / avg_low <= 0.003 for l in recent_lows)
    return falling_highs and flat_support


def _is_bull_flag(df_w: pd.DataFrame) -> bool:
    if len(df_w) < 15:
        return False
    impulse = df_w.iloc[-15:-8]
    consol = df_w.iloc[-8:]
    impulse_move = (float(impulse["close"].iloc[-1]) - float(impulse["open"].iloc[0])) / float(impulse["open"].iloc[0])
    if impulse_move < 0.02:
        return False
    impulse_range = float(impulse["high"].max()) - float(impulse["low"].min())
    consol_range = float(consol["high"].max()) - float(consol["low"].min())
    if impulse_range == 0 or consol_range / impulse_range > 0.382:
        return False
    consol_slope = (float(consol["close"].iloc[-1]) - float(consol["close"].iloc[0])) / float(consol["close"].iloc[0])
    return consol_slope > -0.02


def _is_bear_flag(df_w: pd.DataFrame) -> bool:
    if len(df_w) < 15:
        return False
    impulse = df_w.iloc[-15:-8]
    consol = df_w.iloc[-8:]
    impulse_move = (float(impulse["close"].iloc[-1]) - float(impulse["open"].iloc[0])) / float(impulse["open"].iloc[0])
    if impulse_move > -0.02:
        return False
    impulse_range = float(impulse["high"].max()) - float(impulse["low"].min())
    consol_range = float(consol["high"].max()) - float(consol["low"].min())
    if impulse_range == 0 or consol_range / impulse_range > 0.382:
        return False
    consol_slope = (float(consol["close"].iloc[-1]) - float(consol["close"].iloc[0])) / float(consol["close"].iloc[0])
    return consol_slope < 0.02


def _is_pennant(df_w: pd.DataFrame) -> bool:
    if len(df_w) < 20:
        return False
    impulse = df_w.iloc[-20:-10]
    pennant = df_w.iloc[-10:]
    impulse_range = float(impulse["high"].max()) - float(impulse["low"].min())
    if impulse_range / float(impulse["close"].iloc[-1]) < 0.015:
        return False
    highs = pennant["high"].values
    lows = pennant["low"].values
    start_range = highs[0] - lows[0]
    end_range = highs[-1] - lows[-1]
    return highs[0] > highs[-1] and lows[0] < lows[-1] and start_range > end_range * 1.5


def detect_patterns(df: pd.DataFrame) -> list:
    window = min(50, len(df))
    if window < 20:
        return []

    df_w = df.tail(window).reset_index(drop=True)
    close = float(df_w["close"].iloc[-1])
    sh = _find_swing_highs(df_w["high"])
    sl = _find_swing_lows(df_w["low"])

    checks = [
        ("double_top",                  lambda: _is_double_top(df_w, sh, close)),
        ("double_bottom",               lambda: _is_double_bottom(df_w, sl, close)),
        ("head_and_shoulders",          lambda: _is_head_and_shoulders(df_w, sh, close)),
        ("inverse_head_and_shoulders",  lambda: _is_inverse_head_and_shoulders(df_w, sl, close)),
        ("ascending_triangle",          lambda: _is_ascending_triangle(sh, sl)),
        ("descending_triangle",         lambda: _is_descending_triangle(sh, sl)),
        ("bull_flag",                   lambda: _is_bull_flag(df_w)),
        ("bear_flag",                   lambda: _is_bear_flag(df_w)),
        ("pennant",                     lambda: _is_pennant(df_w)),
    ]

    patterns = []
    for name, fn in checks:
        try:
            if fn():
                patterns.append(name)
        except Exception:
            pass
    return patterns


# ---------------------------------------------------------------------------
# Market Session
# ---------------------------------------------------------------------------

def get_market_session() -> str:
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    if weekday >= 5:
        return "closed"

    in_london = 7 <= hour < 16
    in_newyork = 13 <= hour < 22

    if in_london and in_newyork:
        return "london_newyork_overlap"
    if in_london:
        return "london"
    if in_newyork:
        return "new_york"
    if 0 <= hour < 9:
        return "tokyo"
    return "off_hours"
