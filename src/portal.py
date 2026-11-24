"""Cliente HTTP com sessão por cookies, redirect manual e decodificação windows-1252."""

from __future__ import annotations

import http.cookiejar
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from parsers import (
    detect_session_expired,
    is_login_page,
    parse_curriculum_page,
    parse_login_form,
    parse_menu_and_period,
    parse_subject_classes,
    parse_subject_workload,
)

BASE_URL = "https://www.alunoonline.uerj.br"


class ScrapeError(Exception):
    """Erro estruturado do fluxo de raspagem."""

    def __init__(self, code: str, message: str, extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra or {}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PortalClient:
    """Cliente HTTP sequencial para o Aluno Online da UERJ."""

    def __init__(self, base_url: str = BASE_URL, timeout: float = 25.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            _NoRedirectHandler(),
        )
        self.token: str = ""
        self.menu: dict[str, str | None] = {}
        self.consulta_requisicao: str = ""
        self.consulta_source: str = "none"
        self.curriculum_headers: list[str] = []
        self.period: str = ""

    def _request(self, path_or_url: str, *, no_cache: bool = False) -> tuple[int, str, str]:
        """Executa GET com redirect manual sem nunca logar URLs sensíveis."""
        current_url = (
            path_or_url
            if path_or_url.startswith("http://") or path_or_url.startswith("https://")
            else f"{self.base_url}{path_or_url}"
        )

        for _ in range(6):
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; ColetaDadosAO/1.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
            if no_cache:
                headers["Cache-Control"] = "no-store"
                headers["Pragma"] = "no-cache"

            req = urllib.request.Request(current_url, headers=headers, method="GET")
            try:
                with self.opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    html = raw.decode("windows-1252", errors="replace")
                    return resp.status, html, resp.geturl()
            except urllib.error.HTTPError as err:
                if err.code in (301, 302, 303, 307, 308):
                    location = err.headers.get("Location")
                    if not location:
                        raise ScrapeError("PORTAL_DOWN", "Portal retornou redirecionamento inválido.")
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue
                if err.code == 429:
                    raise ScrapeError(
                        "RATE_LIMITED",
                        "O Aluno Online limitou as requisições (HTTP 429). Aguarde alguns minutos antes de tentar novamente.",
                    )
                if err.code >= 500:
                    raise ScrapeError(
                        "PORTAL_DOWN",
                        f"O Aluno Online respondeu com erro interno (HTTP {err.code}). Tente novamente mais tarde.",
                    )
                raise ScrapeError(
                    "PORTAL_DOWN",
                    f"Falha HTTP {err.code} ao acessar o Aluno Online.",
                )
            except (TimeoutError, socket.timeout) as err:
                raise ScrapeError(
                    "TIMEOUT",
                    "Tempo limite esgotado ao aguardar resposta do Aluno Online.",
                ) from err
            except urllib.error.URLError as err:
                if isinstance(err.reason, (TimeoutError, socket.timeout)):
                    raise ScrapeError(
                        "TIMEOUT",
                        "Tempo limite esgotado ao conectar com o Aluno Online.",
                    ) from err
                raise ScrapeError(
                    "PORTAL_DOWN",
                    "Não foi possível conectar ao Aluno Online da UERJ. Verifique sua conexão.",
                ) from err

        raise ScrapeError("PORTAL_DOWN", "Excesso de redirecionamentos ao acessar o Aluno Online.")

    def login(self, matricula: str, senha: str) -> dict[str, Any]:
        """Executa o fluxo de 3 passos de login do Aluno Online."""
        self._request("/", no_cache=True)

        _, form_html, _ = self._request("/requisicaoaluno/", no_cache=True)
        form_data = parse_login_form(form_html)
        if not form_data["requisicao"] or not form_data["_token"]:
            raise ScrapeError(
                "PORTAL_LAYOUT_CHANGED",
                "Não foi possível localizar os campos de autenticação no formulário do Aluno Online.",
            )

        query = urllib.parse.urlencode(
            {
                "requisicao": form_data["requisicao"],
                "matricula": matricula,
                "senha": senha,
                "_token": form_data["_token"],
            }
        )
        _, login_html, _ = self._request(f"/requisicaoaluno/?{query}", no_cache=True)
        del query

        if is_login_page(login_html):
            raise ScrapeError(
                "LOGIN_FAILED",
                "Matrícula ou senha inválida no Aluno Online. Confira os dados e tente novamente.",
            )

        menu_info = parse_menu_and_period(login_html)
        if not menu_info["menu"]:
            raise ScrapeError(
                "PORTAL_LAYOUT_CHANGED",
                "Login efetuado, mas o menu do Aluno Online não foi reconhecido (possível mudança de layout).",
            )

        self.menu = menu_info["menu"]
        self.token = menu_info["_token"] or form_data["_token"]
        self.period = menu_info["period"]
        return menu_info

    def fetch_curriculum(self) -> list[dict[str, Any]]:
        """Baixa e interpreta a página Disciplinas do Currículo."""
        if "DisciplinasCursar" not in self.menu:
            raise ScrapeError(
                "PORTAL_LAYOUT_CHANGED",
                "Item 'Disciplinas do Currículo' não encontrado no menu do Aluno Online.",
            )
        req_code = self.menu["DisciplinasCursar"]
        if not req_code:
            raise ScrapeError(
                "MENU_BLOCKED",
                "O item 'Disciplinas do Currículo' está bloqueado para esta conta neste momento.",
            )

        query = urllib.parse.urlencode(
            {
                "controle": "Aluno",
                "requisicao": req_code,
                "_token": self.token,
            }
        )
        _, html, _ = self._request(f"/requisicaoaluno/?{query}", no_cache=True)

        if detect_session_expired(html):
            raise ScrapeError("SESSION_EXPIRED", "Sessão expirada ao abrir o currículo.")

        parsed = parse_curriculum_page(html, exclude_requisicao=req_code)
        if parsed["_token"]:
            self.token = parsed["_token"]
        self.curriculum_headers = parsed.get("detectedHeaders") or []

        if parsed["consultaRequisicao"]:
            self.consulta_requisicao = parsed["consultaRequisicao"]
            self.consulta_source = "curriculum_input"
        elif self.menu.get("DadosDisciplina"):
            self.consulta_requisicao = str(self.menu["DadosDisciplina"])
            self.consulta_source = "menu_fallback"
        else:
            self.consulta_requisicao = ""
            self.consulta_source = "none"

        return parsed["subjects"]

    def fetch_subject_detail(self, subject_id: str) -> dict[str, Any]:
        """Consulta os detalhes de uma disciplina (turmas e fallback de carga)."""
        if not self.consulta_requisicao:
            raise ScrapeError(
                "PORTAL_LAYOUT_CHANGED",
                "Código de requisição de Consulta de Disciplina não encontrado na página do currículo nem no menu.",
            )

        subject_number = subject_id.split("-", 1)[1] if "-" in subject_id else subject_id
        query = urllib.parse.urlencode(
            {
                "controle": "Aluno",
                "requisicao": self.consulta_requisicao,
                "_token": self.token,
                "disciplinas[0]": subject_number,
            },
            safe="[]",
        )
        _, html, _ = self._request(f"/requisicaoaluno/?{query}", no_cache=True)

        if detect_session_expired(html):
            raise ScrapeError("SESSION_EXPIRED", f"Sessão expirada ao consultar {subject_id}.")

        return {
            "classes": parse_subject_classes(html),
            "workload": parse_subject_workload(html),
        }

    def fetch_subject_classes(self, subject_id: str) -> list[dict[str, Any]]:
        """Consulta as turmas de uma disciplina pelo número pós-hífen."""
        return self.fetch_subject_detail(subject_id)["classes"]
