"""CLI: raw_data_for_train dan baseline quradi (tmp + atomik swap)."""
import sys

from services.trainer import train
from utils.logger import get_logger

log = get_logger("cli")

if __name__ == "__main__":
    try:
        train()
    except Exception as e:
        log.error("Trainer xatosi: %s", e)
        sys.exit(1)
