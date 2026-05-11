import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_YFINANCE_TIMEOUT = 30  # seconds per request


def _yfinance_history(ticker: str) -> pd.DataFrame:
    return yf.Ticker(ticker).history(period="90d", interval="1h", auto_adjust=True)


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


def _fetch_normalized(ticker: str, is_crypto: bool = False) -> pd.DataFrame | None:
    """Single yfinance download, normalized to standard columns. Returns None on failure or closed market."""
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
        df = df.sort_values("timestamp").reset_index(drop=True)

        if not is_crypto:
            last_candle_age = datetime.now(timezone.utc) - df["timestamp"].iloc[-1].to_pydatetime()
            if last_candle_age > timedelta(hours=2):
                logger.info(f"{ticker}: mercado cerrado (último candle hace {last_candle_age})")
                return None

        return df
    except Exception as e:
        logger.error(f"Error fetching {ticker}: {e}")
        return None


def fetch_ohlcv_both(ticker: str, is_crypto: bool = False) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Single download returning (df_1h, df_4h). Avoids fetching the same data twice."""
    df = _fetch_normalized(ticker, is_crypto)
    if df is None:
        return None, None
    df_1h = df.tail(150).reset_index(drop=True)
    df_4h = _resample_to_4h(df).tail(250).reset_index(drop=True)
    return df_1h, df_4h


def fetch_crypto(ticker: str, timeframe: str, limit: int = 150) -> pd.DataFrame | None:
    return fetch_tradfi(ticker, timeframe, limit=limit, is_crypto=True)


def fetch_tradfi(ticker: str, timeframe: str, limit: int = 150, is_crypto: bool = False) -> pd.DataFrame | None:
    df = _fetch_normalized(ticker, is_crypto)
    if df is None:
        return None
    if timeframe == "4h":
        return _resample_to_4h(df).tail(250).reset_index(drop=True)
    return df.tail(limit).reset_index(drop=True)


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
