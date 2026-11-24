"""Testes unitários com HTML sintético para parsers e orquestração da coleta."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from parsers import (  # noqa: E402
    parse_curriculum_page,
    parse_login_form,
    parse_menu_and_period,
    parse_schedule,
    parse_subject_classes,
    parse_subject_workload,
)
from portal import ScrapeError  # noqa: E402
from scrape import run_scrape  # noqa: E402


CURRICULUM_HTML = """
<html>
  <body>
    <form>
      <input type="hidden" name="requisicao" value="REQ_CONSULTA_DISC_999999999999">
      <input type="hidden" name="_token" value="tok_curriculo_123">
    </form>
    <table>
      <tr>
        <th>Disciplina</th><th>Período</th><th>Cursada</th><th>Tipo</th>
        <th>Ramificação</th><th>Créditos</th><th>CH</th><th>Créd. Mín.</th><th>Do Período</th>
      </tr>
      <tr>
        <td>FCEE01-14886 - Construção de Algoritmos</td>
        <td>1</td>
        <td>Sim</td>
        <td>Obrigatória</td>
        <td>-</td>
        <td>5</td>
        <td>75</td>
        <td>0</td>
        <td>Sim</td>
      </tr>
      <tr>
        <td>FCEE02-14900 - Tópicos Especiais</td>
        <td>6</td>
        <td>Não</td>
        <td>Definida</td>
        <td>847</td>
        <td>4</td>
        <td>60</td>
        <td>80</td>
        <td>Não</td>
      </tr>
    </table>
  </body>
</html>
"""

CONSULTA_HTML = """
<div style="width:58%;text-align:left;float:left;">
  <div>TURMA: 1</div>
  <div>Preferencial: SIM</div>
  <div style="width:86%;text-align:left;float:left;">
    <div>Tempos:</div>
    <div>TER</div>
    <div>N1 N2 N3 N4 N5</div>
  </div>
  <div style="width:74%;text-align:left;float:left;">
    Local das Aulas: Lab. INF. 210 - 2º A
  </div>
  <div style="width:86%;text-align:left;float:left;">
    Docente: EUGENIO DA SILVA<br>MARIA OLIVEIRA
  </div>
</div>
"""


class ParserTests(unittest.TestCase):
    def test_parse_login_form_and_menu(self) -> None:
        form_html = '<form><input name="requisicao" value="abc123"><input name="_token" value="csrf789"></form>'
        self.assertEqual(parse_login_form(form_html), {"requisicao": "abc123", "_token": "csrf789"})

        menu_html = """
        <div>Período Letivo: 2026/1</div>
        <input type="hidden" name="_token" value="tok_menu">
        <a onclick="executaMenu(1, 'aaaaaaaaaaaaaaaaaaaaaaaa', 'x')">Disciplinas do Currículo</a>
        <a onclick="executaMenu(1, 'bbbbbbbbbbbbbbbbbbbbbbbb', 'x')">Pesquisa de Disciplinas</a>
        """
        parsed = parse_menu_and_period(menu_html)
        self.assertEqual(parsed["period"], "2026.1")
        self.assertEqual(parsed["menu"]["DisciplinasCursar"], "aaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(parsed["menu"]["DadosDisciplina"], "bbbbbbbbbbbbbbbbbbbbbbbb")

    def test_curriculum_ignores_header_and_never_keeps_already_taken(self) -> None:
        parsed = parse_curriculum_page(CURRICULUM_HTML)
        self.assertEqual(parsed["consultaRequisicao"], "REQ_CONSULTA_DISC_999999999999")
        subjects = parsed["subjects"]
        self.assertEqual(len(subjects), 2)

        first = subjects[0]
        self.assertEqual(first["id"], "FCEE01-14886")
        self.assertEqual(first["workload"], 75)
        self.assertNotIn("alreadyTaken", first)
        self.assertNotIn("alreadyTaken", subjects[1])

    def test_schedule_day_persists_across_separate_divs_and_gaps(self) -> None:
        sched = parse_schedule("<div>Tempos:</div><div>SEG</div><div>M1 M2</div>")
        self.assertEqual(sched[0]["label"], "Segunda 07:00–08:40")

        merged = parse_schedule("<div>TER</div><div>N1 N2 N3 N4 N5</div>")
        self.assertEqual(merged[0]["label"], "Terça 18:00–21:55")

        gapped = parse_schedule("<div>TER N1 N3</div>")
        self.assertEqual([s["label"] for s in gapped], ["Terça 18:00–18:45", "Terça 19:35–20:20"])

    def test_real_uerj_div_selectors_without_labels_and_multiple_turmas(self) -> None:
        real_detail_html = """
        <div>Carga Horária: 75h</div>
        <div style="width:58%;text-align:left;float:left;">
          <div style="width:50%;float:left;"><b>TURMA:</b>&nbsp;1</div>
          <div style="width:50%;float:left;">Preferencial: SIM</div>
          <div style="width:86%;text-align:left;float:left;">
            <div>SEG</div>
            <div>M1 M2</div>
            <div>QUA</div>
            <div>M1 M2</div>
          </div>
          <div style="width:74%;text-align:left;float:left;">
            Local das Aulas: Lab. INF. 210 - 2º A (Prédio 02 - UERJ-ZO)
          </div>
          <div style="width:86%;text-align:left;float:left;">
            DOCENTE A<br>DOCENTE B
          </div>
        </div>
        """
        self.assertEqual(parse_subject_workload(real_detail_html), 75)
        classes = parse_subject_classes(real_detail_html)
        self.assertEqual(len(classes), 1)
        self.assertEqual(classes[0]["teachers"], ["DOCENTE A", "DOCENTE B"])
        self.assertEqual(classes[0]["location"], "Lab. INF. 210 - 2º A (Prédio 02 - UERJ-ZO)")
        self.assertEqual([s["label"] for s in classes[0]["schedule"]], ["Segunda 07:00–08:40", "Quarta 07:00–08:40"])


class _FakePortal:
    def __init__(self, *, mode: str = "ok") -> None:
        self.mode = mode
        self.login_calls = 0
        self.menu = {"DisciplinasCursar": "aaaaaaaaaaaaaaaaaaaaaaaa"}
        self.period = "2026.1"
        self.subject_calls = 0

    def login(self, matricula: str, senha: str):
        self.login_calls += 1
        if self.mode == "login_failed":
            raise ScrapeError("LOGIN_FAILED", "Matrícula ou senha inválida.")
        if self.mode == "menu_blocked":
            self.menu = {"DisciplinasCursar": None}
        elif self.mode == "empty_period":
            self.period = ""
        return {"menu": self.menu, "period": self.period}

    def fetch_curriculum(self):
        if self.mode == "layout_changed":
            return []
        return parse_curriculum_page(CURRICULUM_HTML)["subjects"]

    def fetch_subject_classes(self, subject_id: str):
        self.subject_calls += 1
        if self.mode == "rate_limited":
            raise ScrapeError("RATE_LIMITED", "HTTP 429")
        if self.mode == "session_expired_once" and self.subject_calls == 1:
            raise ScrapeError("SESSION_EXPIRED", "Sessão expirou")
        return parse_subject_classes(CONSULTA_HTML)


class OrchestratorTests(unittest.TestCase):
    def test_run_scrape_and_no_credentials_in_logs(self) -> None:
        events: list[tuple[str, dict]] = []
        result = run_scrape(
            course="tads",
            matricula="20250000001",
            senha="SecretPassword!",
            on_event=lambda ev, data: events.append((ev, data)),
            portal_factory=lambda: _FakePortal(mode="ok"),
            delay_seconds=0,
        )
        self.assertEqual(len(result["subjects"]), 2)
        subject_events = [data for ev, data in events if ev == "subject"]
        self.assertEqual(len(subject_events), 2)
        self.assertEqual(subject_events[0]["subject"]["id"], "FCEE01-14886")
        serialized = str(events) + str(result)
        self.assertNotIn("20250000001", serialized)
        self.assertNotIn("SecretPassword!", serialized)

    def test_subject_filter_and_retry(self) -> None:
        portal_mand = _FakePortal(mode="ok")
        res = run_scrape(
            course="tads",
            matricula="123",
            senha="abc",
            subject_filter="MANDATORY",
            portal_factory=lambda: portal_mand,
            delay_seconds=0,
        )
        self.assertEqual(portal_mand.subject_calls, 1)
        self.assertEqual(len(res["subjects"]), 1)

        portal_retry = _FakePortal(mode="session_expired_once")
        run_scrape(course="cc", matricula="123", senha="abc", portal_factory=lambda: portal_retry, delay_seconds=0)
        self.assertEqual(portal_retry.login_calls, 2)


if __name__ == "__main__":
    unittest.main()
