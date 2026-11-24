"""Cliente REST do Firebase Firestore usando apenas stdlib e ID Token do usuário."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class FirebaseError(Exception):
    """Erro estruturado ao comunicar com a API do Firebase."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def to_firestore_value(value: Any) -> dict[str, Any]:
    """Converte tipos Python para o formato Value da API REST do Firestore."""
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        if not value:
            return {"arrayValue": {}}
        return {"arrayValue": {"values": [to_firestore_value(item) for item in value]}}
    if isinstance(value, dict):
        fields = {str(k): to_firestore_value(v) for k, v in value.items()}
        return {"mapValue": {"fields": fields}}
    return {"stringValue": str(value)}


def from_firestore_value(raw: dict[str, Any]) -> Any:
    """Converte um objeto Value da API REST do Firestore de volta para Python."""
    if not isinstance(raw, dict):
        return None
    if "nullValue" in raw:
        return None
    if "booleanValue" in raw:
        return bool(raw["booleanValue"])
    if "integerValue" in raw:
        return int(raw["integerValue"])
    if "doubleValue" in raw:
        return float(raw["doubleValue"])
    if "stringValue" in raw:
        return str(raw["stringValue"])
    if "timestampValue" in raw:
        return str(raw["timestampValue"])
    if "arrayValue" in raw:
        values = (raw["arrayValue"] or {}).get("values") or []
        return [from_firestore_value(v) for v in values]
    if "mapValue" in raw:
        fields = (raw["mapValue"] or {}).get("fields") or {}
        return {k: from_firestore_value(v) for k, v in fields.items()}
    return None


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json; charset=utf-8"

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as err:
        raw_err = err.read().decode("utf-8", errors="replace")
        detail = ""
        try:
            parsed = json.loads(raw_err)
            detail = (parsed.get("error") or {}).get("message") or ""
        except Exception:
            detail = raw_err[:200]

        if err.code == 401:
            raise FirebaseError("AUTH_EXPIRED", "Sua sessão Google expirou. Entre novamente com o Google.", 401) from err
        if err.code == 403:
            raise FirebaseError(
                "PERMISSION_DENIED",
                "Permissão negada no Firestore. Verifique se seu cargo possui acesso em Dados/Coleta e se as regras estão publicadas.",
                403,
            ) from err
        if err.code == 404:
            raise FirebaseError("NOT_FOUND", "Documento não encontrado.", 404) from err
        raise FirebaseError("FIREBASE_ERROR", detail or f"Erro HTTP {err.code} no Firebase.", err.code) from err
    except urllib.error.URLError as err:
        raise FirebaseError("NETWORK_ERROR", "Não foi possível conectar ao Firebase. Verifique sua internet.", 503) from err


def refresh_id_token(api_key: str, refresh_token: str) -> dict[str, str]:
    """Renova o Firebase ID Token usando o refresh token."""
    url = f"https://securetoken.googleapis.com/v1/token?key={urllib.parse.quote(api_key)}"
    body = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return {
                "idToken": str(payload.get("id_token") or ""),
                "refreshToken": str(payload.get("refresh_token") or refresh_token),
            }
    except Exception as err:
        raise FirebaseError("AUTH_EXPIRED", "Não foi possível renovar a sessão Google. Entre novamente.", 401) from err


def list_existing_periods(project_id: str, id_token: str, course: str) -> list[str]:
    """Lista os IDs de períodos já salvos em catalogs/{course}/periods."""
    base = f"https://firestore.googleapis.com/v1/projects/{urllib.parse.quote(project_id)}/databases/(default)/documents"
    url = f"{base}/catalogs/{urllib.parse.quote(course)}/periods?pageSize=50"
    try:
        payload = _http_json(url, headers={"Authorization": f"Bearer {id_token}"})
    except FirebaseError as err:
        if err.code == "NOT_FOUND":
            return []
        raise
    docs = payload.get("documents") or []
    periods: list[str] = []
    for d in docs:
        name = str(d.get("name") or "")
        pid = name.rsplit("/", 1)[-1]
        if pid:
            periods.append(pid)
    periods.sort(reverse=True)
    return periods


def get_period_doc(project_id: str, id_token: str, course: str, period: str) -> dict[str, Any] | None:
    """Lê um documento catalogs/{course}/periods/{period} se existir."""
    base = f"https://firestore.googleapis.com/v1/projects/{urllib.parse.quote(project_id)}/databases/(default)/documents"
    url = f"{base}/catalogs/{urllib.parse.quote(course)}/periods/{urllib.parse.quote(period)}"
    try:
        raw = _http_json(url, headers={"Authorization": f"Bearer {id_token}"})
    except FirebaseError as err:
        if err.code == "NOT_FOUND":
            return None
        raise
    fields = raw.get("fields") or {}
    return {k: from_firestore_value(v) for k, v in fields.items()}


def merge_subjects_by_filter(
    existing_subjects: list[dict[str, Any]],
    new_subjects: list[dict[str, Any]],
    subject_filter: str,
) -> list[dict[str, Any]]:
    """Preserva disciplinas de outros tipos quando subject_filter != 'ALL'."""
    if subject_filter == "ALL" or not existing_subjects:
        return list(new_subjects)

    preserved = [s for s in existing_subjects if isinstance(s, dict) and s.get("type") != subject_filter]
    by_id: dict[str, dict[str, Any]] = {}
    for item in preserved:
        if item.get("id"):
            by_id[str(item["id"])] = item
    for item in new_subjects:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item

    return sorted(by_id.values(), key=lambda s: (int(s.get("period") or 0), str(s.get("id") or "")))


def build_commit_payload(
    *,
    project_id: str,
    user_email: str,
    course: str,
    period: str,
    scraped_at: str,
    source: str,
    final_subjects: list[dict[str, Any]],
    run_id: str,
    done_count: int,
    log_lines: list[str],
) -> dict[str, Any]:
    """Monta o payload da Firestore REST API :commit compatível com REQUEST_TIME."""
    doc_root = f"projects/{project_id}/databases/(default)/documents"
    email_lower = user_email.strip().lower()
    course_name = "TADS" if course == "tads" else "CC"

    period_fields = {
        "scrapedAt": to_firestore_value(scraped_at),
        "source": to_firestore_value(source or "aluno-online"),
        "subjects": to_firestore_value(final_subjects),
        "updatedBy": to_firestore_value(email_lower),
    }
    catalog_fields = {
        "name": to_firestore_value(course_name),
        "currentPeriod": to_firestore_value(period),
        "updatedBy": to_firestore_value(email_lower),
    }
    run_fields = {
        "course": to_firestore_value(course),
        "period": to_firestore_value(period),
        "status": to_firestore_value("done"),
        "done": to_firestore_value(done_count),
        "total": to_firestore_value(done_count),
        "log": to_firestore_value(log_lines[-150:]),
        "error": to_firestore_value(None),
        "updatedBy": to_firestore_value(email_lower),
    }

    return {
        "writes": [
            {
                "update": {
                    "name": f"{doc_root}/catalogs/{course}/periods/{period}",
                    "fields": period_fields,
                },
                "updateTransforms": [
                    {"fieldPath": "updatedAt", "setToServerValue": "REQUEST_TIME"},
                ],
            },
            {
                "update": {
                    "name": f"{doc_root}/catalogs/{course}",
                    "fields": catalog_fields,
                },
                "updateTransforms": [
                    {"fieldPath": "updatedAt", "setToServerValue": "REQUEST_TIME"},
                ],
            },
            {
                "update": {
                    "name": f"{doc_root}/scrapeRuns/{run_id}",
                    "fields": run_fields,
                },
                "updateTransforms": [
                    {"fieldPath": "finishedAt", "setToServerValue": "REQUEST_TIME"},
                ],
            },
        ]
    }


def upload_catalog_period(
    *,
    project_id: str,
    id_token: str,
    user_email: str,
    result: dict[str, Any],
    run_id: str,
    log_lines: list[str],
    confirm_overwrite: bool = False,
) -> dict[str, Any]:
    """Valida existência, mescla se parcial e grava no Firestore via :commit."""
    course = str(result.get("course") or "").strip().lower()
    period = str(result.get("period") or "").strip()
    subject_filter = str(result.get("subjectFilter") or "ALL").strip().upper()
    new_subjects = list(result.get("subjects") or [])

    if course not in ("tads", "cc") or not period:
        raise FirebaseError("INVALID_DATA", "Dados incompletos: curso ou período inválido.")

    existing_doc = get_period_doc(project_id, id_token, course, period)
    if existing_doc is not None and not confirm_overwrite:
        raise FirebaseError(
            "PERIOD_EXISTS",
            f"O período {period} de {course.upper()} já existe no Firestore. Confirme para atualizar.",
            409,
        )

    existing_subjects = list((existing_doc or {}).get("subjects") or [])
    final_subjects = merge_subjects_by_filter(existing_subjects, new_subjects, subject_filter)

    payload = build_commit_payload(
        project_id=project_id,
        user_email=user_email,
        course=course,
        period=period,
        scraped_at=str(result.get("scrapedAt") or ""),
        source=str(result.get("source") or "aluno-online"),
        final_subjects=final_subjects,
        run_id=run_id,
        done_count=len(new_subjects),
        log_lines=log_lines,
    )

    commit_url = (
        f"https://firestore.googleapis.com/v1/projects/{urllib.parse.quote(project_id)}"
        f"/databases/(default)/documents:commit"
    )
    _http_json(
        commit_url,
        method="POST",
        body=payload,
        headers={"Authorization": f"Bearer {id_token}"},
    )

    return {
        "course": course,
        "period": period,
        "savedCount": len(final_subjects),
        "merged": subject_filter != "ALL" and len(existing_subjects) > 0,
    }
