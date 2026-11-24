"""Orquestração sequencial da raspagem com progresso em tempo real."""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from portal import PortalClient, ScrapeError

VALID_COURSES = {"tads", "cc"}
VALID_SUBJECT_FILTERS = {"ALL", "MANDATORY", "DEFINED"}
FILTER_LABELS = {
    "ALL": "Todas as matérias",
    "MANDATORY": "Apenas Obrigatórias",
    "DEFINED": "Apenas Definidas",
}
PERIOD_FORMAT_RE = re.compile(r"^20\d{2}\.[12]$")


def normalize_period(raw_period: str) -> str:
    """Normaliza '2026/1' ou '2026.1' para '2026.1'."""
    cleaned = (raw_period or "").strip().replace("/", ".")
    if PERIOD_FORMAT_RE.match(cleaned):
        return cleaned
    return ""


def run_scrape(
    *,
    course: str,
    matricula: str,
    senha: str,
    manual_period: str = "",
    subject_filter: str = "ALL",
    existing_periods: list[str] | None = None,
    confirm_overwrite: bool = False,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
    portal_factory: Callable[[], PortalClient] | None = None,
    delay_seconds: float = 0.3,
) -> dict[str, Any]:
    """Executa a raspagem completa de um curso de forma estritamente sequencial."""

    def emit(event_type: str, **payload: Any) -> None:
        if on_event:
            on_event(event_type, payload)

    def log(level: str, message: str) -> None:
        emit("log", level=level, message=message, ts=datetime.now(timezone.utc).isoformat())

    def check_cancelled() -> None:
        if cancel_event and cancel_event.is_set():
            raise ScrapeError("CANCELLED", "Coleta cancelada pelo usuário.")

    course_key = (course or "").strip().lower()
    if course_key not in VALID_COURSES:
        raise ScrapeError("INVALID_COURSE", "Curso inválido. Escolha TADS ou CC.")

    filter_key = (subject_filter or "ALL").strip().upper()
    if filter_key not in VALID_SUBJECT_FILTERS:
        raise ScrapeError("INVALID_FILTER", "Escopo inválido. Escolha Todas, Obrigatórias ou Definidas.")

    if not (matricula or "").strip() or not senha:
        raise ScrapeError("INVALID_INPUT", "Informe a matrícula e a senha do Aluno Online.")

    client = portal_factory() if portal_factory else PortalClient()
    existing_set = {str(p).strip() for p in (existing_periods or []) if str(p).strip()}

    emit("phase", phase="authenticating", message="Conectando ao Aluno Online...")
    log("info", f"Iniciando sessão segura no Aluno Online para o curso {course_key.upper()}...")

    client.login(matricula.strip(), senha)
    check_cancelled()

    if "DisciplinasCursar" not in client.menu:
        raise ScrapeError(
            "PORTAL_LAYOUT_CHANGED",
            "Item 'Disciplinas do Currículo' não encontrado no menu após o login.",
        )
    if client.menu.get("DisciplinasCursar") is None:
        raise ScrapeError(
            "MENU_BLOCKED",
            "A página 'Disciplinas do Currículo' está bloqueada para esta matrícula neste momento.",
        )

    detected_period = normalize_period(client.period)
    fallback_period = normalize_period(manual_period)
    target_period = detected_period or fallback_period

    if not target_period:
        raise ScrapeError(
            "PERIOD_REQUIRED",
            "O Aluno Online não informou o período letivo automaticamente. Informe o período manualmente (ex.: 2026.1).",
        )

    if target_period in existing_set and not confirm_overwrite:
        raise ScrapeError(
            "PERIOD_EXISTS",
            f"O período {target_period} já possui coleta salva. Confirme se deseja atualizar os dados desse período.",
            extra={"detectedPeriod": target_period},
        )

    log("ok", f"Login validado com sucesso. Período letivo definido: {target_period}.")
    emit("auth_ok", period=target_period, course=course_key, subjectFilter=filter_key)

    check_cancelled()
    emit("phase", phase="curriculum", message="Baixando Disciplinas do Currículo...")
    log("info", "Consultando página 'Disciplinas do Currículo' (windows-1252)...")

    session_retried = False
    try:
        subjects = client.fetch_curriculum()
    except ScrapeError as err:
        if err.code == "SESSION_EXPIRED" and not session_retried:
            session_retried = True
            log("warn", "Sessão expirou ao abrir currículo. Tentando renovar login uma vez...")
            client.login(matricula.strip(), senha)
            subjects = client.fetch_curriculum()
        else:
            raise

    if not subjects:
        raise ScrapeError(
            "PORTAL_LAYOUT_CHANGED",
            "Nenhuma disciplina foi encontrada na tabela do currículo (possível alteração no layout do portal).",
        )

    total_curriculum = len(subjects)
    if filter_key != "ALL":
        subjects = [s for s in subjects if s.get("type") == filter_key]
        log(
            "info",
            f"Filtro aplicado ({FILTER_LABELS[filter_key]}): {len(subjects)} de {total_curriculum} disciplinas serão consultadas.",
        )
        if not subjects:
            raise ScrapeError(
                "NO_MATCHING_SUBJECTS",
                f"Nenhuma disciplina encontrada no currículo para o filtro '{FILTER_LABELS[filter_key]}'.",
            )

    total = len(subjects)
    consulta_source = getattr(client, "consulta_source", "")
    if consulta_source == "curriculum_input":
        log("info", "Código de Consulta de Disciplina localizado no formulário do currículo.")
    elif consulta_source == "menu_fallback":
        log("info", "Código de Consulta de Disciplina obtido via fallback do menu.")

    log("ok", f"Currículo carregado: {total} disciplinas para consulta sequencial (pausa de 300 ms)...")
    emit("phase", phase="scraping", message="Consultando turmas das disciplinas...")
    emit("progress", done=0, total=total)

    def _fetch_detail(subj_id: str) -> tuple[list[dict[str, Any]], int]:
        if hasattr(client, "fetch_subject_detail"):
            detail = client.fetch_subject_detail(subj_id)
            return list(detail.get("classes") or []), int(detail.get("workload") or 0)
        return list(client.fetch_subject_classes(subj_id) or []), 0

    enriched_subjects: list[dict[str, Any]] = []
    for idx, subject in enumerate(subjects, start=1):
        check_cancelled()
        subj_id = subject["id"]
        subj_name = subject["name"]
        log("info", f"[{idx}/{total}] Consultando {subj_id} — {subj_name}...")

        try:
            classes, detail_workload = _fetch_detail(subj_id)
        except ScrapeError as err:
            if err.code == "SESSION_EXPIRED" and not session_retried:
                session_retried = True
                log("warn", f"Sessão expirou durante {subj_id}. Renovando login uma única vez...")
                client.login(matricula.strip(), senha)
                client.fetch_curriculum()
                classes, detail_workload = _fetch_detail(subj_id)
            else:
                raise

        enriched = dict(subject)
        if not enriched.get("workload") and detail_workload > 0:
            enriched["workload"] = detail_workload
        enriched["classes"] = classes
        enriched_subjects.append(enriched)

        turmas_txt = f"{len(classes)} turma(s)" if classes else "sem turmas ofertadas"
        log("ok", f"[{idx}/{total}] {subj_id}: {turmas_txt}.")
        emit(
            "subject",
            subject=enriched,
            course=course_key,
            period=target_period,
            subjectFilter=filter_key,
            done=idx,
            total=total,
        )
        emit("progress", done=idx, total=total, currentId=subj_id, currentName=subj_name)

        if idx < total and delay_seconds > 0:
            time.sleep(delay_seconds)

    result = {
        "course": course_key,
        "period": target_period,
        "subjectFilter": filter_key,
        "scrapedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "aluno-online",
        "subjects": enriched_subjects,
    }
    log("ok", f"Raspagem concluída: {total} disciplinas processadas para {course_key.upper()} ({target_period}).")
    return result
