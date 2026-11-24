"""Armazenamento local seguro de configuração Firebase (sem credenciais ou senhas)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

CONFIG_FIELDS = ("projectId", "apiKey", "authDomain")


def get_app_base_dir() -> Path:
    """Retorna o diretório do executável (quando empacotado) ou raiz do projeto."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def get_resource_dir() -> Path:
    """Retorna o diretório de recursos (compatível com PyInstaller _MEIPASS)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]


def get_user_config_path() -> Path:
    """Caminho padrão em %APPDATA%/coleta-dados-ao/config.json."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "coleta-dados-ao" / "config.json"
    return Path.home() / ".config" / "coleta-dados-ao" / "config.json"


def _normalize_config(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {"projectId": "", "apiKey": "", "authDomain": ""}
    project_id = str(raw.get("projectId") or "").strip()
    api_key = str(raw.get("apiKey") or "").strip()
    auth_domain = str(raw.get("authDomain") or "").strip()
    if project_id and not auth_domain:
        auth_domain = f"{project_id}.firebaseapp.com"
    return {
        "projectId": project_id,
        "apiKey": api_key,
        "authDomain": auth_domain,
    }


def is_config_complete(cfg: dict[str, str]) -> bool:
    return bool(cfg.get("projectId") and cfg.get("apiKey") and cfg.get("authDomain"))


def load_firebase_config() -> dict[str, str]:
    """Carrega configuração Firebase de arquivo local ou %APPDATA% (sem segredos)."""
    local_candidates = [
        get_app_base_dir() / "config.json",
        get_app_base_dir() / "firebase-config.json",
        get_user_config_path(),
    ]
    for path in local_candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cfg = _normalize_config(data)
            if is_config_complete(cfg):
                return cfg
        except Exception:
            continue
    return {"projectId": "", "apiKey": "", "authDomain": ""}


def save_firebase_config(raw: dict[str, Any]) -> dict[str, str]:
    """Valida e grava a configuração pública do Firebase no diretório do usuário."""
    cfg = _normalize_config(raw)
    if not is_config_complete(cfg):
        raise ValueError("Preencha projectId, apiKey e authDomain.")
    target = get_user_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg
