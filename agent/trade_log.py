import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "trades_log.json",
)

MIN_SAMPLE_SIZE = 10  # Minimum closed trades before stats are passed to Claude


def load_trades() -> list:
    try:
        if os.path.exists(_LOG_FILE):
            with open(_LOG_FILE) as f:
                return json.load(f).get("trades", [])
    except Exception as e:
        logger.warning(f"Trade log no disponible: {e}")
    return []


def _save_trades(trades: list) -> None:
    try:
        with open(_LOG_FILE, "w") as f:
            json.dump({"trades": trades}, f, indent=2)
    except Exception as e:
        logger.error(f"Error guardando trade log: {e}")


def log_trade_open(position_id: str, signal_data: dict, trade_result: dict) -> None:
    trades = load_trades()
    # Avoid duplicate entries for the same position
    if any(t.get("id") == position_id for t in trades):
        return

    indicators = signal_data.get("indicators_1h", {})
    entry = {
        "id": position_id,
        "asset": signal_data["asset"],
        "direction": signal_data["signal"],
        "open_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open_price": signal_data["price"],
        "sl": trade_result["sl"],
        "tp": trade_result["tp"],
        "lots": trade_result["lots"],
        "atr": indicators.get("atr"),
        "strength": signal_data["strength"],
        "patterns": signal_data.get("patterns", []),
        "session": signal_data.get("session", ""),
        "trend_4h": signal_data.get("trend_4h", ""),
        "rsi": round(float(indicators.get("rsi", 0)), 2),
        "reasoning": signal_data.get("reasoning", ""),
        "status": "OPEN",
        "close_time": None,
        "close_price": None,
        "pnl_usd": None,
        "result": None,
    }
    trades.append(entry)
    _save_trades(trades)
    logger.info(f"Trade registrado: {entry['asset']} {entry['direction']} @ {entry['open_price']}")


def log_trade_close(position_id: str, deal: dict) -> None:
    trades = load_trades()
    updated = False
    for trade in trades:
        if trade.get("id") == position_id and trade.get("status") == "OPEN":
            pnl = float(deal.get("profit", 0))
            trade["close_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            trade["close_price"] = deal.get("price") or deal.get("closePrice")
            trade["pnl_usd"] = round(pnl, 2)
            trade["result"] = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
            trade["status"] = "CLOSED"
            updated = True
            break
    if updated:
        _save_trades(trades)


def get_stats(trades: list | None = None) -> dict:
    if trades is None:
        trades = load_trades()

    closed = [t for t in trades if t.get("status") == "CLOSED"]
    if not closed:
        return {"sample_size": 0}

    wins = [t for t in closed if t.get("result") == "WIN"]
    losses = [t for t in closed if t.get("result") == "LOSS"]
    total_win_pnl = sum(t["pnl_usd"] for t in wins)
    total_loss_pnl = sum(abs(t["pnl_usd"]) for t in losses)

    def _subset_stats(subset: list) -> dict | None:
        if len(subset) < 5:
            return None
        w = sum(1 for t in subset if t.get("result") == "WIN")
        return {"win_rate": round(w / len(subset), 3), "n": len(subset)}

    # By asset
    assets = set(t["asset"] for t in closed)
    by_asset = {a: _subset_stats([t for t in closed if t["asset"] == a]) for a in assets}

    # By session
    sessions = set(t["session"] for t in closed)
    by_session = {s: _subset_stats([t for t in closed if t["session"] == s]) for s in sessions}

    # By strength
    by_strength = {
        s: _subset_stats([t for t in closed if t["strength"] == s])
        for s in ("HIGH", "MEDIUM")
    }

    # By pattern
    all_patterns = set(p for t in closed for p in t.get("patterns", []))
    by_pattern = {
        p: _subset_stats([t for t in closed if p in t.get("patterns", [])])
        for p in all_patterns
    }

    return {
        "sample_size": len(closed),
        "win_rate": round(len(wins) / len(closed), 3),
        "avg_win_usd": round(total_win_pnl / len(wins), 2) if wins else 0,
        "avg_loss_usd": round(total_loss_pnl / len(losses), 2) if losses else 0,
        "profit_factor": round(total_win_pnl / total_loss_pnl, 2) if total_loss_pnl > 0 else None,
        "by_asset": {k: v for k, v in by_asset.items() if v},
        "by_session": {k: v for k, v in by_session.items() if v},
        "by_strength": {k: v for k, v in by_strength.items() if v},
        "by_pattern": {k: v for k, v in by_pattern.items() if v},
    }


def get_context_for_signal(asset: str, session: str, patterns: list) -> dict | None:
    """Returns performance stats for Claude's context. None if insufficient data."""
    trades = load_trades()
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    if len(closed) < MIN_SAMPLE_SIZE:
        return None

    stats = get_stats(closed)
    ctx: dict = {
        "overall_win_rate": stats["win_rate"],
        "sample_size": stats["sample_size"],
    }

    if s := stats["by_asset"].get(asset):
        ctx["asset_win_rate"] = s["win_rate"]
        ctx["asset_n"] = s["n"]

    if s := stats["by_session"].get(session):
        ctx["session_win_rate"] = s["win_rate"]
        ctx["session_n"] = s["n"]

    pattern_rates = {p: stats["by_pattern"][p]["win_rate"]
                    for p in patterns if p in stats["by_pattern"]}
    if pattern_rates:
        ctx["pattern_win_rates"] = pattern_rates

    return ctx
