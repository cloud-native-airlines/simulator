"""Run the simulator: ``python -m simulator``."""

from __future__ import annotations

import uvicorn

from .app import create_app
from .config import load_config
from .logging_config import configure_logging


def main() -> None:
    configure_logging()
    config = load_config()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_config=None)


if __name__ == "__main__":
    main()
