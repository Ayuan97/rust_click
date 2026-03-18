@echo off
setlocal

uv run --with PySide6 --with pyqtgraph python -m app.main %*

endlocal

