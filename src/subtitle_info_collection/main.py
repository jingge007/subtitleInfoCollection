from __future__ import annotations

import sys


def main() -> int:
    try:
        from subtitle_info_collection.gui.main_window import run_app
    except ImportError as exc:
        print("运行桌面应用需要安装 PySide6。")
        print(f"导入错误：{exc}")
        return 1

    return run_app(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
