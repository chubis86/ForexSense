import logging

logger = logging.getLogger(__name__)


def get_daily_movement_pct(current_price: float, open_price: float) -> float:
    return ((current_price - open_price) / open_price) * 100


def is_within_daily_limit(current_price: float, open_price: float, threshold: float = 0.02) -> bool:
    movement = abs(current_price - open_price) / open_price
    return movement <= threshold


def check_daily_limit(asset_name: str, current_price: float, open_price: float) -> bool:
    """Returns True if asset is within daily limit, False if blocked."""
    movement_pct = get_daily_movement_pct(current_price, open_price)
    within = is_within_daily_limit(current_price, open_price)
    if not within:
        sign = "+" if movement_pct > 0 else ""
        logger.info(f"{asset_name}: límite diario alcanzado ({sign}{movement_pct:.1f}%)")
    return within
