from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HID Remapper 压枪轨迹工作台")
    parser.add_argument("--file", help="启动时打开的参数文件")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        import pyqtgraph as pg
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError as exc:
        print(
            "缺少 GUI 依赖。请运行 `trajectory_lab.cmd`，或执行 "
            "`uv run --with PySide6 --with pyqtgraph python -m app.main`。",
            file=sys.stderr,
        )
        print(f"导入错误：{exc}", file=sys.stderr)
        return 1

    from .ui_main import TrajectoryWorkbench

    app_args = [sys.argv[0], *(sys.argv[1:] if argv is None else argv)]
    app = QApplication(app_args)
    app.setApplicationName("压枪轨迹工作台")
    app.setStyle("Fusion")
    pg.setConfigOptions(antialias=True, background="w", foreground="#20262e")

    initial_path = Path(args.file).resolve() if args.file else None
    window = TrajectoryWorkbench(initial_path=initial_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
