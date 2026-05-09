import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_YFINANCE_TIMEOUT = 30  # seconds per request


def _yfinance_history(ticker: str) -> pd.DataFrame:
    return yf.Ticker(ticker).history(period="30d", interval="1h", auto_adjust=True)


def fetch_crypto(ticker: str, timeframe: str, limit: int = 150) -> pd.DataFrame | None:
    """Fetch crypto OHLCV via yfinance (e.g. BTC-USD, ETH-USD). No geo restrictions."""
    return fetch_tradfi(ticker, timeframe, limit=limit, is_crypto=True)


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


def fetch_tradfi(ticker: str, timeframe: str, limit: int = 150, is_crypto: bool = False) -> pd.DataFrame | None:
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_yfinance_history, ticker)
            try:
                raw = future.result(timeout=_YFINANCE_TIMEOUT)
            except FuturesTimeoutError:
                logger.warning(f"{ticker}: timeout fetching data ({_YFINANCE_TIMEOUT}s)")
                return None

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

        # Detect closed market: last candle older than 2 hours (skip for crypto — 24/7)
        if not is_crypto:
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
