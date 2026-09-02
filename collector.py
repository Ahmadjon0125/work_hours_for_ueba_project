"""CLI: 60 kunlik tarixni yig'ib raw_data_for_train ga yozadi."""
import sys

from services.collector import collect
from utils.logger import get_logger

log = get_logger("cli")

if __name__ == "__main__":
    try:
        collect()
    except Exception as e:
        log.error("Collector xatosi: %s", e)
        sys.exit(1)
