import logging
import sys


def setup_logging(settings=None) -> None:
    level = getattr(settings, "LOG_LEVEL", logging.INFO) if settings else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,
    )
