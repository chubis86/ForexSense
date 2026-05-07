import logging
from datetime import datetime, timezone, timedelta

import ccxt
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_crypto(symbol: str, timeframe: str, limit: int = 150) -> pd.DataFrame | None:
    try:
        exchange = ccxt.bybit()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception as e:
        logger.error(f"Error fetching crypto {symbol} {timeframe}: {e}")
        return None


def _resample_to_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    df = df_1h.set_index("timestamp")
    df_4h = df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return df_4h.reset_index()


def fetch_tradfi(ticker: str, timeframe: str, limit: int = 150) -> pd.DataFrame | None:
    try:
        ticker_obj = yf.Ticker(ticker)
        raw = ticker_obj.history(period="30d", interval="1h", auto_adjust=True)

        if raw.empty:
            logger.warning(f"No data returned for {ticker}")
            return None

        raw = raw.reset_index()
        raw.columns = [c.lower() for c in raw.columns]
        col_map = {"datetime": "timestamp", "date": "timestamp"}
        raw = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})

        if "timestamp" not in raw.columns:
            logger.error(f"No timestamp column for {ticker}, columns: {raw.columns.tolist()}")
            return None

        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
        df = raw[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        df = df.sort_values("timestamp").tail(limit).reset_index(drop=True)

        # Detect closed market: last candle older than 2 hours
        last_candle_age = datetime.now(timezone.utc) - df["timestamp"].iloc[-1].to_pydatetime()
        if last_candle_age > timedelta(hours=2):
            logger.info(f"{ticker}: mercado cerrado (último candle hace {last_candle_age})")
            return None

        if timeframe == "4h":
            df = _resample_to_4h(df)

        return df
    except Exception as e:
        logger.error(f"Error fetching tradfi {ticker} {timeframe}: {e}")
        return None


def get_day_open(df_1h: pd.DataFrame) -> float | None:
    try:
        today_utc = datetime.now(timezone.utc).date()
        today_candles = df_1h[df_1h["timestamp"].dt.date == today_utc]
        if not today_candles.empty:
            return float(today_candles.iloc[0]["open"])
        last_close = float(df_1h.iloc[-1]["close"])
        logger.warning(f"Precio de apertura no disponible, usando último close ({last_close}) como referencia")
        return last_close
    except Exception as e:
        logger.error(f"Error obteniendo precio de apertura: {e}")
        return None
