import json
import logging
import os

logger = logging.getLogger(__name__)

# Stored one level above agent/ so GitHub Actions cache picks it up at repo root
_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "positions_state.json",
)


def load_positions() -> list:
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE) as f:
                return json.load(f).get("positions", [])
    except Exception as e:
        logger.warning(f"Estado previo no disponible: {e}")
    return []


def save_positions(positions: list) -> None:
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump({"positions": positions}, f)
        logger.info(f"Estado guardado: {len(positions)} posición(es) registrada(s)")
    except Exception as e:
        logger.error(f"Error guardando estado: {e}")
