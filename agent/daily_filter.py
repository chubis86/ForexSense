import logging

logger = logging.getLogger(__name__)

CRYPTO_ASSETS = {"BTC/USD", "ETH/USD"}
CRYPTO_THRESHOLD = 0.04  # 4% for crypto
TRADFI_THRESHOLD = 0.02  # 2% for forex/gold


def get_daily_movement_pct(current_price: float, open_price: float) -> float:
    return ((current_price - open_price) / open_price) * 100


def is_within_daily_limit(current_price: float, open_price: float, threshold: float = TRADFI_THRESHOLD) -> bool:
    movement = abs(current_price - open_price) / open_price
    return movement <= threshold


def check_daily_limit(asset_name: str, current_price: float, open_price: float) -> bool:
    """Returns True if asset is within daily limit, False if blocked."""
    threshold = CRYPTO_THRESHOLD if asset_name in CRYPTO_ASSETS else TRADFI_THRESHOLD
    movement_pct = get_daily_movement_pct(current_price, open_price)
    within = is_within_daily_limit(current_price, open_price, threshold)
    if not within:
        sign = "+" if movement_pct > 0 else ""
        logger.info(f"{asset_name}: límite diario alcanzado ({sign}{movement_pct:.1f}%, límite {threshold*100:.0f}%)")
    return within
