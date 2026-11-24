"""Ponto de entrada do aplicativo desktop coleta-dados-ao."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app_server import AppState, start_server


def main() -> None:
    app_state = AppState()
    server = start_server(app_state)
    url = f"http://127.0.0.1:{app_state.port}/"

    if "--browser" in sys.argv:
        webbrowser.open(url)
        print(f"coleta-dados-ao ativo em {url} (Pressione Ctrl+C para encerrar)")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.shutdown()
            return

    try:
        import webview

        window_holder: list[Any] = []

        def dialog_bridge(mode: str, default_name: str, ext: str) -> str | None:
            if not window_holder:
                return None
            win = window_holder[0]
            file_types = (
                ("JSON (*.json)",) if ext == "json" else ("CSV (*.csv)",)
            )
            if mode == "save":
                res = win.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=default_name,
                    file_types=file_types,
                )
            else:
                res = win.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=False,
                    file_types=("JSON (*.json)",),
                )
            if isinstance(res, (list, tuple)):
                return str(res[0]) if res else None
            return str(res) if res else None

        app_state.file_dialog_fn = dialog_bridge
        win = webview.create_window(
            "Coleta de Dados — Aluno Online UERJ",
            url,
            width=1280,
            height=840,
            min_size=(920, 620),
            background_color="#0a0909",
        )
        window_holder.append(win)
        webview.start()
    except Exception:
        webbrowser.open(url)
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
