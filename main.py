"""Entry point for the nMCP-client desktop application."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def _setup_logging() -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter("%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s")

    fh = logging.handlers.RotatingFileHandler(
        logs_dir / "nmcp_client.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)


def main() -> None:
    _setup_logging()

    # PySide6 import deferred so logging is configured first
    from PySide6.QtWidgets import QApplication
    from src.ui.app import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("nMCP Client")
    app.setOrganizationName("nMCP")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
