"""Servidor HTTP local da interface desktop, SSE da raspagem e bridge de arquivos/Firebase."""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import queue
import secrets
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from config_store import (
    get_resource_dir,
    is_config_complete,
    load_firebase_config,
    save_firebase_config,
)
from firebase_client import (
    FirebaseError,
    check_user_permission,
    list_existing_periods,
    refresh_id_token,
    upload_catalog_period,
)
from portal import ScrapeError
from scrape import run_scrape

TYPE_LABELS = {
    "MANDATORY": "Obrigatória",
    "DEFINED": "Definida",
    "UNIVERSAL": "Universal",
    "RESTRICTED": "Restrita",
}


class ScrapeJob:
    """Estado em memória de uma execução de raspagem."""

    def __init__(self, run_id: str, course: str) -> None:
        self.run_id = run_id
        self.course = course
        self.done = False
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._history: list[tuple[str, dict[str, Any]]] = []
        self._subscribers: list[queue.Queue[tuple[str, dict[str, Any]] | None]] = []

    def push_event(self, event_type: str, payload: dict[str, Any]) -> None:
        item = (event_type, payload)
        with self._lock:
            self._history.append(item)
            for sub in list(self._subscribers):
                sub.put(item)

    def finish(self) -> None:
        with self._lock:
            self.done = True
            for sub in list(self._subscribers):
                sub.put(None)

    def subscribe(self) -> tuple[list[tuple[str, dict[str, Any]]], queue.Queue[tuple[str, dict[str, Any]] | None], bool]:
        q: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
        with self._lock:
            history_copy = list(self._history)
            already_done = self.done
            if not already_done:
                self._subscribers.append(q)
        return history_copy, q, already_done

    def unsubscribe(self, q: queue.Queue[tuple[str, dict[str, Any]] | None]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)


class AppState:
    """Estado global em memória do aplicativo desktop (sem credenciais de aluno salvas)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.port: int = 0
        self.firebase_config: dict[str, str] = load_firebase_config()
        self.auth_session: dict[str, str] | None = None
        self.pending_nonces: dict[str, float] = {}
        self.jobs: dict[str, ScrapeJob] = {}
        self.latest_result: dict[str, Any] | None = None
        self.latest_run_id: str = ""
        self.latest_logs: list[str] = []
        self.file_dialog_fn: Callable[[str, str, str], str | None] | None = None


def _default_file_dialog(mode: str, default_name: str, file_ext: str) -> str | None:
    """Fallback nativo com tkinter para salvar ou abrir arquivos."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if mode == "save":
            filetypes = [("JSON", "*.json")] if file_ext == "json" else [("CSV", "*.csv")]
            return filedialog.asksaveasfilename(
                defaultextension=f".{file_ext}",
                initialfile=default_name,
                filetypes=filetypes,
            ) or None
        return filedialog.askopenfilename(filetypes=[("JSON", "*.json")]) or None
    finally:
        root.destroy()


def _build_clean_export_json(result: dict[str, Any]) -> dict[str, Any]:
    """Retorna estrutura limpa sem dados pessoais ou internos."""
    return {
        "course": result.get("course", ""),
        "period": result.get("period", ""),
        "scrapedAt": result.get("scrapedAt", ""),
        "source": result.get("source", "aluno-online"),
        "subjects": result.get("subjects", []),
    }


def _build_csv_text(subjects: list[dict[str, Any]], course: str) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(
        [
            "Curso",
            "Código",
            "Disciplina",
            "Período",
            "Tipo",
            "Créditos",
            "Carga",
            "Turma",
            "Docente",
            "Local",
            "Horário",
            "Do período",
            "Ramificação",
        ]
    )

    course_upper = course.upper() if course else "N/A"
    for subj in subjects:
        classes = subj.get("classes") or []
        iterable = classes if classes else [None]
        for cls in iterable:
            teachers = " / ".join(cls.get("teachers") or []) if cls and cls.get("teachers") else "N/A"
            sched = (
                " · ".join(
                    s.get("label") or f"{s.get('day', '')} {s.get('start', '')}–{s.get('end', '')}"
                    for s in (cls.get("schedule") or [])
                )
                if cls and cls.get("schedule")
                else "N/A"
            )
            credits_val = subj.get("credits")
            writer.writerow(
                [
                    course_upper,
                    subj.get("id") or "N/A",
                    subj.get("name") or "N/A",
                    f"{subj['period']}º" if subj.get("period") else "N/A",
                    subj.get("typeLabel") or TYPE_LABELS.get(subj.get("type", ""), "") or "N/A",
                    str(credits_val) if isinstance(credits_val, int) and credits_val > 0 else "N/A",
                    f"{subj['workload']}h" if subj.get("workload") else "N/A",
                    str(cls["classNumber"]) if cls and cls.get("classNumber") is not None else "N/A",
                    teachers,
                    (cls.get("location") if cls else "") or "N/A",
                    sched,
                    "Sim" if subj.get("subjectOfPeriod") else "Não",
                    subj.get("branch") or "N/A",
                ]
            )
    return "\ufeff" + output.getvalue()


def _render_auth_html(cfg: dict[str, str], nonce: str) -> str:
    cfg_json = json.dumps(cfg)
    nonce_json = json.dumps(nonce)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Entrar com Google — Coleta de Dados AO</title>
  <style>
    body {{
      margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 20px;
      background: #0a0909; color: #f3eee3; font-family: system-ui, -apple-system, sans-serif;
    }}
    .card {{
      width: min(440px, 100%); padding: 28px; border: 1px solid rgba(243,238,227,.2);
      border-top: 3px solid #e00700; background: #110e0e;
    }}
    h1 {{ margin: 0 0 10px; font-size: 1.35rem; text-transform: uppercase; letter-spacing: .04em; }}
    p {{ margin: 0 0 18px; color: #cfc8be; line-height: 1.5; font-size: .92rem; }}
    button {{
      width: 100%; padding: 13px 16px; border: 1px solid #e00700; background: #e00700;
      color: #fff; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; cursor: pointer;
    }}
    button:disabled {{ opacity: .6; cursor: wait; }}
    .status {{ margin-top: 14px; font-size: .85rem; color: #ffd3ce; }}
    .ok {{ color: #9be8b8; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Autenticar envio no Firebase</h1>
    <p>Entre com sua conta Google autorizada para enviar os catálogos coletados ao Firestore.</p>
    <button id="loginBtn" type="button">Entrar com Google</button>
    <div id="status" class="status"></div>
  </div>
  <script type="module">
    import {{ initializeApp }} from "https://www.gstatic.com/firebasejs/11.6.1/firebase-app.js";
    import {{ getAuth, GoogleAuthProvider, signInWithPopup }} from "https://www.gstatic.com/firebasejs/11.6.1/firebase-auth.js";

    const cfg = {cfg_json};
    const nonce = {nonce_json};
    const app = initializeApp(cfg);
    const auth = getAuth(app);
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({{ prompt: "select_account" }});

    const btn = document.getElementById("loginBtn");
    const statusEl = document.getElementById("status");

    btn.addEventListener("click", async () => {{
      btn.disabled = true;
      statusEl.textContent = "Abrindo janela do Google...";
      try {{
        const cred = await signInWithPopup(auth, provider);
        const idToken = await cred.user.getIdToken();
        const refreshToken = cred.user.refreshToken || "";
        const resp = await fetch("/api/auth/callback", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            nonce,
            idToken,
            refreshToken,
            email: cred.user.email || "",
            displayName: cred.user.displayName || ""
          }})
        }});
        if (!resp.ok) throw new Error("Falha ao retornar sessão para o aplicativo.");
        statusEl.className = "status ok";
        statusEl.textContent = "Login concluído! Você já pode fechar esta aba e voltar para o aplicativo.";
        window.setTimeout(() => window.close(), 1200);
      }} catch (err) {{
        statusEl.textContent = err && err.message ? err.message : "Erro ao autenticar com Google.";
        btn.disabled = false;
      }}
    }});
  </script>
</body>
</html>
"""


def make_handler(app_state: AppState) -> type[BaseHTTPRequestHandler]:
    ui_dir = (get_resource_dir() / "ui").resolve()

    class DesktopHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status: int, html_text: str) -> None:
            body = html_text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if length <= 0 or length > 20 * 1024 * 1024:
                return None
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                return data if isinstance(data, dict) else None
            except Exception:
                return None

        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path

            if path == "/api/state":
                with app_state.lock:
                    cfg = dict(app_state.firebase_config)
                    auth_user = (
                        {
                            "email": app_state.auth_session["email"],
                            "displayName": app_state.auth_session.get("displayName", ""),
                            "authorized": bool(app_state.auth_session.get("authorized", False)),
                            "authReason": app_state.auth_session.get("authReason", ""),
                        }
                        if app_state.auth_session
                        else None
                    )
                    latest = app_state.latest_result
                self._send_json(
                    200,
                    {
                        "firebaseConfigured": is_config_complete(cfg),
                        "firebaseConfig": cfg,
                        "authUser": auth_user,
                        "latestResult": latest,
                    },
                )
                return

            if path == "/auth":
                qs = urllib.parse.parse_qs(parsed.query)
                nonce = (qs.get("nonce") or [""])[0]
                with app_state.lock:
                    valid = nonce in app_state.pending_nonces and app_state.pending_nonces[nonce] > time.monotonic()
                    cfg = dict(app_state.firebase_config)
                if not valid or not is_config_complete(cfg):
                    self._send_html(400, "<h1>Sessão de login inválida ou Firebase não configurado.</h1>")
                    return
                self._send_html(200, _render_auth_html(cfg, nonce))
                return

            if path.startswith("/api/scrape/stream/"):
                run_id = path[len("/api/scrape/stream/") :].strip("/")
                self._handle_stream(run_id)
                return

            self._serve_ui(path)

        def do_POST(self) -> None:
            path = urllib.parse.urlsplit(self.path).path

            if path == "/api/config":
                body = self._read_json() or {}
                try:
                    cfg = save_firebase_config(body)
                    with app_state.lock:
                        app_state.firebase_config = cfg
                    self._send_json(200, {"ok": True, "firebaseConfig": cfg})
                except ValueError as err:
                    self._send_json(400, {"error": {"code": "INVALID_CONFIG", "message": str(err)}})
                return

            if path == "/api/auth/start":
                with app_state.lock:
                    cfg = dict(app_state.firebase_config)
                    port = app_state.port
                if not is_config_complete(cfg):
                    self._send_json(
                        400,
                        {"error": {"code": "NO_FIREBASE", "message": "Configure o Firebase antes de entrar com Google."}},
                    )
                    return
                nonce = secrets.token_urlsafe(16)
                with app_state.lock:
                    app_state.pending_nonces[nonce] = time.monotonic() + 300
                webbrowser.open(f"http://localhost:{port}/auth?nonce={urllib.parse.quote(nonce)}")
                self._send_json(200, {"ok": True})
                return

            if path == "/api/auth/callback":
                body = self._read_json() or {}
                nonce = str(body.get("nonce") or "")
                id_token = str(body.get("idToken") or "")
                refresh_token = str(body.get("refreshToken") or "")
                email = str(body.get("email") or "").strip().lower()
                display_name = str(body.get("displayName") or "").strip()

                with app_state.lock:
                    exp = app_state.pending_nonces.pop(nonce, 0.0)
                    cfg = dict(app_state.firebase_config)
                    if exp <= time.monotonic() or not id_token or not email:
                        self._send_json(400, {"error": {"code": "INVALID_NONCE", "message": "Callback inválido."}})
                        return

                perm_check = check_user_permission(cfg.get("projectId", ""), id_token, email)
                with app_state.lock:
                    app_state.auth_session = {
                        "email": email,
                        "displayName": display_name,
                        "idToken": id_token,
                        "refreshToken": refresh_token,
                        "authorized": bool(perm_check.get("authorized", False)),
                        "authReason": str(perm_check.get("reason") or ""),
                    }
                self._send_json(200, {"ok": True, "authorized": bool(perm_check.get("authorized", False))})
                return

            if path == "/api/auth/logout":
                with app_state.lock:
                    app_state.auth_session = None
                self._send_json(200, {"ok": True})
                return

            if path == "/api/scrape/start":
                self._handle_scrape_start()
                return

            if path.startswith("/api/scrape/cancel/"):
                run_id = path[len("/api/scrape/cancel/") :].strip("/")
                with app_state.lock:
                    job = app_state.jobs.get(run_id)
                if not job:
                    self._send_json(404, {"error": {"code": "NOT_FOUND", "message": "Execução não encontrada."}})
                    return
                job.cancel_event.set()
                self._send_json(200, {"ok": True})
                return

            if path == "/api/firebase/periods":
                self._handle_firebase_periods()
                return

            if path == "/api/firebase/upload":
                self._handle_firebase_upload()
                return

            if path == "/api/export/json":
                self._handle_export_json()
                return

            if path == "/api/export/csv":
                self._handle_export_csv()
                return

            if path == "/api/import/json":
                self._handle_import_json()
                return

            self._send_json(404, {"error": {"code": "NOT_FOUND", "message": "Endpoint não encontrado."}})

        def _handle_scrape_start(self) -> None:
            body = self._read_json() or {}
            course = str(body.get("course") or "").strip().lower()
            subject_filter = str(body.get("subjectFilter") or "ALL").strip().upper()
            matricula = str(body.get("matricula") or "").strip()
            senha = str(body.get("senha") or "")
            manual_period = str(body.get("period") or "").strip()

            if course not in ("tads", "cc"):
                self._send_json(400, {"error": {"code": "INVALID_COURSE", "message": "Selecione TADS ou CC."}})
                return
            if subject_filter not in ("ALL", "MANDATORY", "DEFINED"):
                self._send_json(400, {"error": {"code": "INVALID_FILTER", "message": "Escopo inválido."}})
                return
            if not matricula or not senha:
                self._send_json(400, {"error": {"code": "INVALID_INPUT", "message": "Informe matrícula e senha."}})
                return

            run_id = uuid.uuid4().hex
            job = ScrapeJob(run_id, course)
            with app_state.lock:
                app_state.jobs[run_id] = job
                app_state.latest_logs = []

            def on_event(ev: str, data: dict[str, Any]) -> None:
                if ev == "log":
                    with app_state.lock:
                        app_state.latest_logs.append(str(data.get("message") or ""))
                        if len(app_state.latest_logs) > 200:
                            app_state.latest_logs = app_state.latest_logs[-200:]
                elif ev == "auth_ok":
                    with app_state.lock:
                        app_state.latest_run_id = run_id
                        app_state.latest_result = {
                            "course": str(data.get("course") or course),
                            "period": str(data.get("period") or ""),
                            "subjectFilter": str(data.get("subjectFilter") or subject_filter),
                            "scrapedAt": "",
                            "source": "aluno-online",
                            "subjects": [],
                        }
                elif ev == "subject":
                    subj = data.get("subject")
                    if isinstance(subj, dict):
                        with app_state.lock:
                            if not isinstance(app_state.latest_result, dict):
                                app_state.latest_result = {
                                    "course": str(data.get("course") or course),
                                    "period": str(data.get("period") or ""),
                                    "subjectFilter": str(data.get("subjectFilter") or subject_filter),
                                    "scrapedAt": "",
                                    "source": "aluno-online",
                                    "subjects": [],
                                }
                            app_state.latest_result["subjects"].append(subj)
                job.push_event(ev, data)

            def worker() -> None:
                try:
                    result = run_scrape(
                        course=course,
                        matricula=matricula,
                        senha=senha,
                        manual_period=manual_period,
                        subject_filter=subject_filter,
                        on_event=on_event,
                        cancel_event=job.cancel_event,
                    )
                    with app_state.lock:
                        app_state.latest_result = result
                        app_state.latest_run_id = run_id
                    job.push_event("complete", result)
                except ScrapeError as err:
                    payload: dict[str, Any] = {"code": err.code, "message": err.message}
                    if err.extra:
                        payload.update(err.extra)
                    job.push_event("error", payload)
                except Exception:
                    job.push_event("error", {"code": "INTERNAL_ERROR", "message": "Erro inesperado na raspagem."})
                finally:
                    job.finish()

            threading.Thread(target=worker, daemon=True).start()
            self._send_json(200, {"runId": run_id})

        def _handle_stream(self, run_id: str) -> None:
            with app_state.lock:
                job = app_state.jobs.get(run_id)
            if not job:
                self._send_json(404, {"error": {"code": "NOT_FOUND", "message": "Execução não encontrada."}})
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "close")
            self.end_headers()

            def write_sse(ev_type: str, data: dict[str, Any]) -> bool:
                chunk = f"event: {ev_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return False

            history, q, already_done = job.subscribe()
            try:
                for ev_type, payload in history:
                    if not write_sse(ev_type, payload):
                        return
                if already_done:
                    return
                while True:
                    try:
                        item = q.get(timeout=15.0)
                    except queue.Empty:
                        try:
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            return
                        continue
                    if item is None:
                        break
                    if not write_sse(item[0], item[1]):
                        return
            finally:
                job.unsubscribe(q)

        def _with_valid_auth(self) -> tuple[dict[str, str], dict[str, str]] | None:
            with app_state.lock:
                cfg = dict(app_state.firebase_config)
                sess = dict(app_state.auth_session) if app_state.auth_session else None
            if not is_config_complete(cfg):
                self._send_json(400, {"error": {"code": "NO_FIREBASE", "message": "Configure o Firebase primeiro."}})
                return None
            if not sess or not sess.get("idToken"):
                self._send_json(401, {"error": {"code": "AUTH_REQUIRED", "message": "Entre com sua conta Google primeiro."}})
                return None
            return cfg, sess

        def _handle_firebase_periods(self) -> None:
            ctx = self._with_valid_auth()
            if not ctx:
                return
            cfg, sess = ctx
            body = self._read_json() or {}
            course = str(body.get("course") or "").strip().lower()
            if course not in ("tads", "cc"):
                self._send_json(400, {"error": {"code": "INVALID_COURSE", "message": "Curso inválido."}})
                return
            try:
                periods = list_existing_periods(cfg["projectId"], sess["idToken"], course)
                self._send_json(200, {"periods": periods})
            except FirebaseError as err:
                if err.code == "AUTH_EXPIRED" and sess.get("refreshToken"):
                    try:
                        refreshed = refresh_id_token(cfg["apiKey"], sess["refreshToken"])
                        with app_state.lock:
                            if app_state.auth_session:
                                app_state.auth_session.update(refreshed)
                        periods = list_existing_periods(cfg["projectId"], refreshed["idToken"], course)
                        self._send_json(200, {"periods": periods})
                        return
                    except FirebaseError as err2:
                        self._send_json(err2.status, {"error": {"code": err2.code, "message": err2.message}})
                        return
                self._send_json(err.status, {"error": {"code": err.code, "message": err.message}})

        def _handle_firebase_upload(self) -> None:
            ctx = self._with_valid_auth()
            if not ctx:
                return
            cfg, sess = ctx
            if not sess.get("authorized"):
                self._send_json(
                    403,
                    {
                        "error": {
                            "code": "FORBIDDEN",
                            "message": sess.get("authReason")
                            or "Sua conta não possui a permissão 'Coletor Desktop (.exe)' na Gestão.",
                        }
                    },
                )
                return
            body = self._read_json() or {}
            confirm_overwrite = bool(body.get("confirmOverwrite", False))

            with app_state.lock:
                result = body.get("result") or app_state.latest_result
                run_id = app_state.latest_run_id or uuid.uuid4().hex
                logs = list(app_state.latest_logs)

            if not isinstance(result, dict) or not result.get("subjects"):
                self._send_json(400, {"error": {"code": "NO_DATA", "message": "Nenhum dado coletado ou carregado para enviar."}})
                return

            try:
                summary = upload_catalog_period(
                    project_id=cfg["projectId"],
                    id_token=sess["idToken"],
                    user_email=sess["email"],
                    result=result,
                    run_id=run_id,
                    log_lines=logs,
                    confirm_overwrite=confirm_overwrite,
                )
                self._send_json(200, {"ok": True, **summary})
            except FirebaseError as err:
                if err.code == "AUTH_EXPIRED" and sess.get("refreshToken"):
                    try:
                        refreshed = refresh_id_token(cfg["apiKey"], sess["refreshToken"])
                        with app_state.lock:
                            if app_state.auth_session:
                                app_state.auth_session.update(refreshed)
                        summary = upload_catalog_period(
                            project_id=cfg["projectId"],
                            id_token=refreshed["idToken"],
                            user_email=sess["email"],
                            result=result,
                            run_id=run_id,
                            log_lines=logs,
                            confirm_overwrite=confirm_overwrite,
                        )
                        self._send_json(200, {"ok": True, **summary})
                        return
                    except FirebaseError as err2:
                        self._send_json(err2.status, {"error": {"code": err2.code, "message": err2.message}})
                        return
                self._send_json(err.status, {"error": {"code": err.code, "message": err.message}})

        def _choose_file(self, mode: str, default_name: str, ext: str) -> str | None:
            fn = app_state.file_dialog_fn or _default_file_dialog
            return fn(mode, default_name, ext)

        def _handle_export_json(self) -> None:
            body = self._read_json() or {}
            with app_state.lock:
                result = body.get("result") or app_state.latest_result
            if not isinstance(result, dict) or not result.get("subjects"):
                self._send_json(400, {"error": {"code": "NO_DATA", "message": "Nenhum dado disponível para exportar."}})
                return
            default_name = f"catalogo-{result.get('course', 'curso')}-{result.get('period', 'atual')}.json"
            path = self._choose_file("save", default_name, "json")
            if not path:
                self._send_json(200, {"cancelled": True})
                return
            clean = _build_clean_export_json(result)
            Path(path).write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
            self._send_json(200, {"ok": True, "path": path})

        def _handle_export_csv(self) -> None:
            body = self._read_json() or {}
            with app_state.lock:
                result = body.get("result") or app_state.latest_result
            subjects = body.get("subjects") or (result.get("subjects") if isinstance(result, dict) else None)
            course = str(body.get("course") or (result.get("course") if isinstance(result, dict) else "curso"))
            period = str(body.get("period") or (result.get("period") if isinstance(result, dict) else "atual"))
            if not subjects:
                self._send_json(400, {"error": {"code": "NO_DATA", "message": "Nenhuma linha disponível para exportar."}})
                return
            default_name = f"catalogo-{course}-{period}.csv"
            path = self._choose_file("save", default_name, "csv")
            if not path:
                self._send_json(200, {"cancelled": True})
                return
            csv_text = _build_csv_text(subjects, course)
            Path(path).write_text(csv_text, encoding="utf-8")
            self._send_json(200, {"ok": True, "path": path})

        def _handle_import_json(self) -> None:
            path = self._choose_file("open", "", "json")
            if not path:
                self._send_json(200, {"cancelled": True})
                return
            try:
                raw = json.loads(Path(path).read_text(encoding="utf-8"))
                course = str(raw.get("course") or "").strip().lower()
                period = str(raw.get("period") or "").strip()
                subjects = raw.get("subjects")
                if course not in ("tads", "cc") or not period or not isinstance(subjects, list):
                    raise ValueError("JSON fora do formato esperado de catálogo (course, period, subjects).")
                loaded = {
                    "course": course,
                    "period": period,
                    "subjectFilter": "ALL",
                    "scrapedAt": str(raw.get("scrapedAt") or ""),
                    "source": str(raw.get("source") or "aluno-online"),
                    "subjects": subjects,
                }
                with app_state.lock:
                    app_state.latest_result = loaded
                    app_state.latest_run_id = uuid.uuid4().hex
                self._send_json(200, {"ok": True, "path": path, "result": loaded})
            except Exception as err:
                self._send_json(400, {"error": {"code": "INVALID_JSON", "message": str(err)}})

        def _serve_ui(self, url_path: str) -> None:
            clean = urllib.parse.unquote(url_path).lstrip("/")
            if not clean:
                clean = "index.html"
            candidate = (ui_dir / clean).resolve()
            try:
                candidate.relative_to(ui_dir)
            except ValueError:
                self.send_error(403)
                return
            if not candidate.is_file():
                self.send_error(404)
                return
            ctype, _ = mimetypes.guess_type(str(candidate))
            if candidate.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif candidate.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif candidate.suffix == ".html":
                ctype = "text/html; charset=utf-8"
            elif not ctype:
                ctype = "application/octet-stream"
            data = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return DesktopHandler


def start_server(app_state: AppState, preferred_port: int = 8766) -> ThreadingHTTPServer:
    """Inicia o servidor local em 127.0.0.1 escolhendo porta disponível."""
    handler = make_handler(app_state)
    for port in (preferred_port, 0):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            app_state.port = int(server.server_address[1])
            threading.Thread(target=server.serve_forever, daemon=True).start()
            return server
        except OSError:
            continue
    raise RuntimeError("Não foi possível iniciar o servidor local.")
