"""Parsers HTML para o Aluno Online da UERJ (currículo, turmas e horários)."""

from __future__ import annotations

import html as html_lib
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any

TIME_SLOTS: dict[str, tuple[str, str]] = {
    "M1": ("07:00", "07:50"),
    "M2": ("07:50", "08:40"),
    "M3": ("08:50", "09:40"),
    "M4": ("09:40", "10:30"),
    "M5": ("10:40", "11:30"),
    "M6": ("11:30", "12:20"),
    "T1": ("12:30", "13:20"),
    "T2": ("13:20", "14:10"),
    "T3": ("14:20", "15:10"),
    "T4": ("15:10", "16:00"),
    "T5": ("16:10", "17:00"),
    "T6": ("17:00", "17:50"),
    "N1": ("18:00", "18:45"),
    "N2": ("18:45", "19:30"),
    "N3": ("19:35", "20:20"),
    "N4": ("20:20", "21:05"),
    "N5": ("21:10", "21:55"),
    "N6": ("21:55", "22:40"),
}

SLOT_ORDER: list[str] = [
    "M1", "M2", "M3", "M4", "M5", "M6",
    "T1", "T2", "T3", "T4", "T5", "T6",
    "N1", "N2", "N3", "N4", "N5", "N6",
]
SLOT_INDEX: dict[str, int] = {code: idx for idx, code in enumerate(SLOT_ORDER)}

DAY_MAP: dict[str, str] = {
    "SEG": "Segunda",
    "SEGUNDA": "Segunda",
    "TER": "Terça",
    "TERCA": "Terça",
    "QUA": "Quarta",
    "QUARTA": "Quarta",
    "QUI": "Quinta",
    "QUINTA": "Quinta",
    "SEX": "Sexta",
    "SEXTA": "Sexta",
    "SAB": "Sábado",
    "SABADO": "Sábado",
    "DOM": "Domingo",
    "DOMINGO": "Domingo",
}

SUBJECT_CODE_RE = re.compile(r"[A-Za-z]+\d+-\d+")
MENU_CODE_RE = re.compile(r"([A-Za-z0-9]{20,})")
PERIOD_RE = re.compile(r"\b(20\d{2})\s*[./]\s*([12])\b")


def normalize_text(value: str) -> str:
    """Remove acentos e normaliza espaços para comparações tolerantes."""
    text = html_lib.unescape(value or "")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def clean_html_text(fragment: str) -> str:
    """Converte HTML simples em texto limpo preservando espaços simples."""
    if not fragment:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class _InputCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.all_inputs: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        name = attr_map.get("name", "").strip()
        if name:
            val = html_lib.unescape(attr_map.get("value", "")).strip()
            self.all_inputs.setdefault(name, []).append(val)


def parse_all_form_inputs(page_html: str) -> dict[str, list[str]]:
    """Extrai todas as ocorrências de cada campo <input> da página HTML."""
    collector = _InputCollector()
    collector.feed(page_html or "")
    collector.close()
    return collector.all_inputs


def parse_form_inputs(page_html: str) -> dict[str, str]:
    """Extrai o primeiro valor não vazio de cada campo <input> da página HTML."""
    all_inputs = parse_all_form_inputs(page_html)
    result: dict[str, str] = {}
    for name, values in all_inputs.items():
        non_empty = [v for v in values if v]
        result[name] = non_empty[0] if non_empty else (values[0] if values else "")
    return result


def parse_login_form(page_html: str) -> dict[str, str]:
    """Extrai requisicao e _token do formulário de login do Aluno Online."""
    inputs = parse_form_inputs(page_html)
    return {
        "requisicao": inputs.get("requisicao", "").strip(),
        "_token": inputs.get("_token", "").strip(),
    }


def is_login_page(page_html: str) -> bool:
    """Indica se o HTML retornado ainda representa a tela de login."""
    if not page_html:
        return False
    inputs = parse_all_form_inputs(page_html)
    if "matricula" in inputs and "senha" in inputs:
        return True
    norm = normalize_text(clean_html_text(page_html)).lower()
    failure_hints = (
        "matricula ou senha",
        "senha invalida",
        "usuario ou senha",
        "dados invalidos",
        "autenticacao falhou",
        "acesso negado",
    )
    return any(hint in norm for hint in failure_hints)


def detect_session_expired(page_html: str) -> bool:
    """Detecta se o portal redirecionou para login ou sessão expirada."""
    if not page_html:
        return False
    if is_login_page(page_html):
        return True
    norm = normalize_text(clean_html_text(page_html)).lower()
    return "sessao expirada" in norm or "faca login novamente" in norm


class _MenuAnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_anchor = False
        self._current_onclick = ""
        self._text_parts: list[str] = []
        self.items: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            attr_map = {k.lower(): (v or "") for k, v in attrs}
            self._in_anchor = True
            self._current_onclick = attr_map.get("onclick", "")
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._in_anchor:
            label = re.sub(r"\s+", " ", "".join(self._text_parts)).strip()
            self.items.append((label, self._current_onclick))
            self._in_anchor = False
            self._current_onclick = ""
            self._text_parts = []


def _canonical_menu_key(label: str) -> str | None:
    norm = normalize_text(label).lower()
    if "disciplinas do curriculo" in norm or "disciplinas do curso" in norm:
        return "DisciplinasCursar"
    if "notas do periodo" in norm:
        return "notas"
    if "rid" in norm and "resultado provisorio" in norm:
        return "RidParcial"
    if "pesquisa de disciplinas" in norm or "consulta de disciplina" in norm:
        return "DadosDisciplina"
    return None


def parse_menu_and_period(page_html: str) -> dict[str, Any]:
    """Extrai o mapa de requisições do menu e o período letivo da página inicial."""
    parser = _MenuAnchorParser()
    parser.feed(page_html or "")
    parser.close()

    menu: dict[str, str | None] = {}
    for label, onclick in parser.items:
        key = _canonical_menu_key(label)
        if not key:
            continue
        code_match = MENU_CODE_RE.search(onclick or "")
        menu[key] = code_match.group(1) if code_match else None

    inputs = parse_form_inputs(page_html)
    plain_text = clean_html_text(page_html)
    period = ""
    period_match = PERIOD_RE.search(plain_text)
    if period_match:
        period = f"{period_match.group(1)}.{period_match.group(2)}"

    return {
        "menu": menu,
        "_token": inputs.get("_token", "").strip(),
        "period": period,
    }


class _TableParser(HTMLParser):
    """Extrai tabelas isoladas evitando corrupção por tabelas aninhadas."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[dict[str, Any]]] = []
        self._stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "table":
            self._stack.append(
                {
                    "rows": [],
                    "in_tr": False,
                    "in_cell": False,
                    "has_th": False,
                    "current_row": [],
                    "cell_parts": [],
                }
            )
            return
        if not self._stack:
            return
        cur = self._stack[-1]
        if t == "tr":
            cur["in_tr"] = True
            cur["has_th"] = False
            cur["current_row"] = []
        elif t in ("td", "th") and cur["in_tr"]:
            cur["in_cell"] = True
            if t == "th":
                cur["has_th"] = True
            cur["cell_parts"] = []
        elif t == "br" and cur["in_cell"]:
            cur["cell_parts"].append(" ")

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1]["in_cell"]:
            self._stack[-1]["cell_parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if not self._stack:
            return
        cur = self._stack[-1]
        if t in ("td", "th") and cur["in_cell"]:
            cell_text = re.sub(r"\s+", " ", html_lib.unescape("".join(cur["cell_parts"]))).strip()
            cur["current_row"].append(cell_text)
            cur["in_cell"] = False
            cur["cell_parts"] = []
        elif t == "tr" and cur["in_tr"]:
            if cur["current_row"]:
                cur["rows"].append({"cells": cur["current_row"], "has_th": cur["has_th"]})
            cur["in_tr"] = False
            cur["current_row"] = []
        elif t == "table":
            finished = self._stack.pop()
            if finished["rows"]:
                self.tables.append(finished["rows"])


def _parse_int(value: str, default: int = 0) -> int:
    match = re.search(r"-?\d+", value or "")
    return int(match.group(0)) if match else default


def _map_subject_type(raw_label: str) -> tuple[str, str]:
    label = (raw_label or "").strip()
    norm = normalize_text(label).lower()
    if "obrigat" in norm:
        return "MANDATORY", label or "Obrigatória"
    if "definid" in norm:
        return "DEFINED", label or "Definida"
    if "universal" in norm:
        return "UNIVERSAL", label or "Universal"
    if "restrit" in norm:
        return "RESTRICTED", label or "Restrita"
    return "DEFINED", label


def _detect_curriculum_columns(header_cells: list[str]) -> dict[str, int] | None:
    """Mapeia índices das colunas pelo cabeçalho quando presente."""
    if len(header_cells) < 7:
        return None
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        norm = normalize_text(cell).lower()
        if "disciplina" in norm and "subject" not in mapping:
            mapping["subject"] = idx
        elif "do periodo" in norm:
            mapping["subjectOfPeriod"] = idx
        elif "periodo" in norm and "period" not in mapping:
            mapping["period"] = idx
        elif "tipo" in norm:
            mapping["type"] = idx
        elif "ramific" in norm:
            mapping["branch"] = idx
        elif ("carga" in norm or norm in ("ch", "c.h.", "c/h")) and "workload" not in mapping:
            mapping["workload"] = idx
        elif "min" in norm and ("cred" in norm or "cr" in norm):
            mapping["minimumCredits"] = idx
        elif "cred" in norm and "credits" not in mapping:
            mapping["credits"] = idx

    if "period" in mapping and "credits" in mapping and "workload" in mapping:
        return mapping
    return None


def _pick_consulta_requisicao(values: list[str], exclude_requisicao: str = "") -> str:
    """Escolhe o código de Consulta de Disciplina ignorando inputs vazios do topo da página."""
    non_empty = [v.strip() for v in values if v and v.strip()]
    if not non_empty:
        return ""
    candidates = [v for v in non_empty if v != exclude_requisicao] or non_empty
    long_codes = [v for v in candidates if len(v) >= 20]
    return long_codes[-1] if long_codes else candidates[-1]


def parse_curriculum_page(page_html: str, *, exclude_requisicao: str = "") -> dict[str, Any]:
    """Lê a tabela de 9 colunas de Disciplinas do Currículo (sem guardar alreadyTaken)."""
    all_inputs = parse_all_form_inputs(page_html)
    consulta_req = _pick_consulta_requisicao(all_inputs.get("requisicao", []), exclude_requisicao)
    tokens = [v.strip() for v in all_inputs.get("_token", []) if v and v.strip()]
    token = tokens[-1] if tokens else ""

    table_parser = _TableParser()
    table_parser.feed(page_html or "")
    table_parser.close()

    subjects: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    detected_headers: list[str] = []

    for table_rows in table_parser.tables:
        col_map: dict[str, int] | None = None
        for row_info in table_rows:
            row = row_info["cells"]
            if len(row) < 8:
                continue

            if row_info["has_th"] or not SUBJECT_CODE_RE.search(row[0]):
                maybe_map = _detect_curriculum_columns(row)
                if maybe_map:
                    col_map = maybe_map
                    detected_headers = row
                continue

            subj_idx = col_map.get("subject", 0) if col_map else 0
            cell0 = row[subj_idx] if subj_idx < len(row) else row[0]
            code_match = SUBJECT_CODE_RE.search(cell0)
            if not code_match:
                continue

            subj_id = code_match.group(0).upper()
            if subj_id in seen_ids:
                continue
            seen_ids.add(subj_id)

            raw_name = (cell0[: code_match.start()] + " " + cell0[code_match.end() :]).strip()
            name = re.sub(r"^[\s\-–—:]+", "", raw_name)
            name = re.sub(r"\s+", " ", name).strip()

            p_idx = col_map.get("period", 1) if col_map else 1
            t_idx = col_map.get("type", 3) if col_map else 3
            b_idx = col_map.get("branch", 4) if col_map else 4
            c_idx = col_map.get("credits", 5) if col_map else 5
            w_idx = col_map.get("workload", 6) if col_map else 6
            m_idx = col_map.get("minimumCredits", 7) if col_map else 7
            s_idx = col_map.get("subjectOfPeriod", 8) if col_map else 8

            def cell_at(i: int) -> str:
                return row[i] if 0 <= i < len(row) else ""

            subject_type, type_label = _map_subject_type(cell_at(t_idx))
            branch_raw = cell_at(b_idx).strip()
            branch = "" if branch_raw in ("", "-", "—") else branch_raw

            # Célula 2 (alreadyTaken) é descartada propositalmente.
            subjects.append(
                {
                    "id": subj_id,
                    "name": name,
                    "period": _parse_int(cell_at(p_idx), 0),
                    "type": subject_type,
                    "typeLabel": type_label,
                    "branch": branch,
                    "credits": _parse_int(cell_at(c_idx), 0),
                    "workload": _parse_int(cell_at(w_idx), 0),
                    "minimumCredits": _parse_int(cell_at(m_idx), 0),
                    "subjectOfPeriod": normalize_text(cell_at(s_idx)).lower() == "sim",
                }
            )

    return {
        "consultaRequisicao": consulta_req,
        "_token": token,
        "subjects": subjects,
        "detectedHeaders": detected_headers,
    }


def _extract_lines_from_html(block_html: str) -> list[str]:
    """Quebra HTML de um bloco de horários em linhas lógicas preservando divs e <br>."""
    if not block_html:
        return []
    prepared = re.sub(r"(?i)<br\s*/?>", "\n", block_html)
    prepared = re.sub(r"(?i)</?(div|p|li|tr|td|th|span)[^>]*>", "\n", prepared)
    prepared = re.sub(r"<[^>]+>", " ", prepared)
    prepared = html_lib.unescape(prepared)
    return [re.sub(r"\s+", " ", line).strip() for line in prepared.splitlines() if line.strip()]


def parse_schedule(block_html: str) -> list[dict[str, Any]]:
    """Converte bloco HTML ou texto de tempos (M1..N6) em intervalos agrupados por continuidade."""
    lines = _extract_lines_from_html(block_html)
    current_day: str | None = None
    day_runs: list[tuple[str, list[str]]] = []

    for line in lines:
        norm_line = normalize_text(line).upper()
        tokens = [t.rstrip(":;,") for t in re.split(r"[\s,;]+", norm_line) if t]
        line_slots: list[str] = []

        for token in tokens:
            if token == "TEMPOS":
                continue
            if token in DAY_MAP:
                current_day = DAY_MAP[token]
                continue
            if token in TIME_SLOTS and current_day:
                line_slots.append(token)

        if line_slots and current_day:
            if day_runs and day_runs[-1][0] == current_day:
                for slot in line_slots:
                    if slot not in day_runs[-1][1]:
                        day_runs[-1][1].append(slot)
            else:
                unique_slots: list[str] = []
                for slot in line_slots:
                    if slot not in unique_slots:
                        unique_slots.append(slot)
                day_runs.append((current_day, unique_slots))

    schedule: list[dict[str, Any]] = []
    for day, slots in day_runs:
        if not slots:
            continue
        ordered = sorted(slots, key=lambda s: SLOT_INDEX[s])
        groups: list[list[str]] = [[ordered[0]]]
        for slot in ordered[1:]:
            prev_idx = SLOT_INDEX[groups[-1][-1]]
            curr_idx = SLOT_INDEX[slot]
            if curr_idx == prev_idx + 1:
                groups[-1].append(slot)
            elif curr_idx > prev_idx + 1:
                groups.append([slot])

        for group in groups:
            start = TIME_SLOTS[group[0]][0]
            end = TIME_SLOTS[group[-1]][1]
            schedule.append(
                {
                    "day": day,
                    "slots": group,
                    "start": start,
                    "end": end,
                    "label": f"{day} {start}–{end}",
                }
            )

    return schedule


class _DivStyleExtractor(HTMLParser):
    """Captura o HTML interno de <div>s cujo atributo style contém uma substring alvo."""

    def __init__(self, style_substring: str) -> None:
        super().__init__(convert_charrefs=False)
        self.target = style_substring.lower().replace(" ", "")
        self.matches: list[str] = []
        self._div_depth = 0
        self._capture_depth: int | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        is_div = tag.lower() == "div"
        if is_div:
            self._div_depth += 1

        if self._capture_depth is not None:
            self._buf.append(self.get_starttag_text() or f"<{tag}>")
            return

        if is_div:
            attr_map = {k.lower(): (v or "") for k, v in attrs}
            style_norm = attr_map.get("style", "").lower().replace(" ", "")
            if self.target in style_norm:
                self._capture_depth = self._div_depth
                self._buf = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._capture_depth is not None:
            self._buf.append(self.get_starttag_text() or f"<{tag}/>")

    def handle_data(self, data: str) -> None:
        if self._capture_depth is not None:
            self._buf.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._capture_depth is not None:
            self._buf.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._capture_depth is not None:
            self._buf.append(f"&#{name};")

    def handle_endtag(self, tag: str) -> None:
        is_div = tag.lower() == "div"
        if self._capture_depth is not None:
            if is_div and self._div_depth == self._capture_depth:
                self.matches.append("".join(self._buf))
                self._capture_depth = None
                self._buf = []
            else:
                self._buf.append(f"</{tag}>")
        if is_div and self._div_depth > 0:
            self._div_depth -= 1


def extract_styled_divs(page_html: str, style_substring: str) -> list[str]:
    """Retorna o HTML interno dos blocos <div style='...'> que correspondem ao seletor."""
    extractor = _DivStyleExtractor(style_substring)
    extractor.feed(page_html or "")
    extractor.close()
    return extractor.matches


def _extract_labeled_section(chunk_html: str, label_pattern: str, stop_patterns: list[str]) -> str:
    stop_union = "|".join(stop_patterns)
    pattern = re.compile(
        rf"(?:{label_pattern})\s*:?\s*(?:</[^>]+>\s*)*([\s\S]*?)(?=(?:{stop_union})\s*:?|$)",
        re.IGNORECASE,
    )
    match = pattern.search(chunk_html)
    return match.group(1) if match else ""


def _parse_teachers(section_html: str) -> list[str]:
    if not section_html:
        return []
    prepared = re.sub(r"(?i)<br\s*/?>", "\n", section_html)
    prepared = re.sub(r"(?i)</?(div|p|li)[^>]*>", "\n", prepared)
    prepared = re.sub(r"<[^>]+>", " ", prepared)
    prepared = html_lib.unescape(prepared)
    teachers: list[str] = []
    for raw in prepared.splitlines():
        cleaned = re.sub(r"\s+", " ", raw).strip()
        cleaned = re.sub(r"^(?:docentes?)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
        if not cleaned or cleaned in ("-", "—"):
            continue
        if normalize_text(cleaned).lower().rstrip(":") in ("docente", "docentes"):
            continue
        if cleaned not in teachers:
            teachers.append(cleaned)
    return teachers


def _parse_location(section_html: str) -> str:
    if not section_html:
        return ""
    lines = _extract_lines_from_html(section_html)
    cleaned_lines: list[str] = []
    for line in lines:
        stripped = re.sub(r"^(?:local(?:\s+das\s+aulas)?)\s*:\s*", "", line, flags=re.IGNORECASE).strip()
        if not stripped:
            continue
        if normalize_text(stripped).lower().rstrip(":") in ("local das aulas", "local"):
            continue
        cleaned_lines.append(stripped)
    joined = " ".join(cleaned_lines).strip()
    return "" if joined in ("-", "—") else joined


def _parse_class_chunk(chunk_html: str, stop_labels: list[str]) -> dict[str, Any] | None:
    plain = clean_html_text(chunk_html)
    turma_match = re.search(r"TURMA\s*:\s*(\d+)", plain, re.IGNORECASE)
    if not turma_match:
        return None

    class_number = int(turma_match.group(1))
    pref_match = re.search(r"Preferencial\s*:\s*(SIM|N[ÃA]O|NAO)", plain, re.IGNORECASE)
    has_preference = bool(pref_match and normalize_text(pref_match.group(1)).upper() == "SIM")

    w86_divs = extract_styled_divs(chunk_html, "width:86%")
    w74_divs = extract_styled_divs(chunk_html, "width:74%")

    schedule = parse_schedule(w86_divs[0]) if len(w86_divs) >= 1 else []
    if not schedule:
        schedule_html = _extract_labeled_section(chunk_html, r"Tempos", stop_labels)
        schedule = parse_schedule(schedule_html)

    location = _parse_location(w74_divs[0]) if len(w74_divs) >= 1 else ""
    if not location:
        location_html = _extract_labeled_section(chunk_html, r"Local\s+das\s+Aulas|Local", stop_labels)
        location = _parse_location(location_html)

    teachers = _parse_teachers(w86_divs[1]) if len(w86_divs) >= 2 else []
    if not teachers:
        teachers_html = _extract_labeled_section(chunk_html, r"Docentes?", stop_labels)
        teachers = _parse_teachers(teachers_html)

    return {
        "classNumber": class_number,
        "hasPreference": has_preference,
        "teachers": teachers,
        "location": location,
        "schedule": schedule,
    }


def parse_subject_classes(page_html: str) -> list[dict[str, Any]]:
    """Extrai a lista de turmas de uma página Consulta de Disciplina."""
    if not page_html:
        return []

    stop_labels = [
        r"Preferencial",
        r"Docentes?",
        r"Local\s+das\s+Aulas",
        r"Tempos",
        r"Vagas",
        r"Observa[çc][õo]es",
    ]

    classes: list[dict[str, Any]] = []
    w58_blocks = extract_styled_divs(page_html, "width:58%")
    for block in w58_blocks:
        parsed = _parse_class_chunk(block, stop_labels)
        if parsed:
            classes.append(parsed)

    if classes:
        return classes

    turma_matches = list(
        re.finditer(
            r"TURMA\s*(?:<[^>]+>|\s|&nbsp;)*:\s*(?:<[^>]+>|\s|&nbsp;)*(\d+)",
            page_html,
            re.IGNORECASE,
        )
    )
    for idx, match in enumerate(turma_matches):
        start_pos = match.start()
        end_pos = turma_matches[idx + 1].start() if idx + 1 < len(turma_matches) else len(page_html)
        parsed = _parse_class_chunk(page_html[start_pos:end_pos], stop_labels)
        if parsed:
            classes.append(parsed)

    return classes


def parse_subject_workload(page_html: str) -> int:
    """Fallback para extrair Carga Horária da página Consulta de Disciplina."""
    if not page_html:
        return 0
    plain = clean_html_text(page_html)
    match = re.search(r"Carga\s+Hor[áa]ria\s*:?\s*(\d+)", plain, re.IGNORECASE)
    return int(match.group(1)) if match else 0
