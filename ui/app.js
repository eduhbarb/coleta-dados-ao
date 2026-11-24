const TYPE_LABELS = {
  MANDATORY: "Obrigatória",
  DEFINED: "Definida",
  UNIVERSAL: "Universal",
  RESTRICTED: "Restrita"
};

const els = {
  fbPill: document.querySelector("[data-fb-pill]"),
  openFbModalBtn: document.querySelector("[data-open-fb-modal]"),
  authLoginBtn: document.querySelector("[data-auth-login]"),
  authLogoutBtn: document.querySelector("[data-auth-logout]"),
  authUserPill: document.querySelector("[data-auth-user-pill]"),
  authEmail: document.querySelector("[data-auth-email]"),
  globalAlert: document.querySelector("[data-global-alert]"),
  courseBtns: Array.from(document.querySelectorAll("[data-course-btn]")),
  statPeriod: document.querySelector("[data-stat-period]"),
  statSubjects: document.querySelector("[data-stat-subjects]"),
  statClasses: document.querySelector("[data-stat-classes]"),
  statUpdated: document.querySelector("[data-stat-updated]"),
  openScrapeModalBtn: document.querySelector("[data-open-scrape-modal]"),
  importJsonBtn: document.querySelector("[data-import-json]"),
  exportJsonBtn: document.querySelector("[data-export-json]"),
  uploadFirebaseBtn: document.querySelector("[data-upload-firebase]"),
  exportCsvBtn: document.querySelector("[data-export-csv]"),
  statusBadge: document.querySelector("[data-status-badge]"),
  cancelScrapeBtn: document.querySelector("[data-cancel-scrape]"),
  clearLogBtn: document.querySelector("[data-clear-log]"),
  progressText: document.querySelector("[data-progress-text]"),
  progressPct: document.querySelector("[data-progress-pct]"),
  progressFill: document.querySelector("[data-progress-fill]"),
  logList: document.querySelector("[data-log-list]"),
  filterSearch: document.querySelector("[data-filter-search]"),
  filterGrade: document.querySelector("[data-filter-grade]"),
  filterType: document.querySelector("[data-filter-type]"),
  filterOfPeriod: document.querySelector("[data-filter-ofperiod]"),
  filterOnlyClasses: document.querySelector("[data-filter-only-classes]"),
  tableMeta: document.querySelector("[data-table-meta]"),
  tableBody: document.querySelector("[data-table-body]"),
  scrapeModal: document.querySelector("[data-scrape-modal]"),
  scrapeModalClose: document.querySelector("[data-scrape-modal-close]"),
  scrapeModalCancel: document.querySelector("[data-scrape-modal-cancel]"),
  scrapeForm: document.querySelector("[data-scrape-form]"),
  modalCourse: document.querySelector("[data-modal-course]"),
  modalScope: document.querySelector("[data-modal-scope]"),
  modalMatricula: document.querySelector("[data-modal-matricula]"),
  modalSenha: document.querySelector("[data-modal-senha]"),
  togglePassBtn: document.querySelector("[data-toggle-pass]"),
  modalPeriod: document.querySelector("[data-modal-period]"),
  scrapeModalAlert: document.querySelector("[data-scrape-modal-alert]"),
  scrapeSubmitBtn: document.querySelector("[data-scrape-submit]"),
  fbModal: document.querySelector("[data-fb-modal]"),
  fbModalClose: document.querySelector("[data-fb-modal-close]"),
  fbModalCancel: document.querySelector("[data-fb-modal-cancel]"),
  fbForm: document.querySelector("[data-fb-form]"),
  fbProjectId: document.querySelector("[data-fb-project-id]"),
  fbApiKey: document.querySelector("[data-fb-api-key]"),
  fbAuthDomain: document.querySelector("[data-fb-auth-domain]"),
  fbModalAlert: document.querySelector("[data-fb-modal-alert]"),
  overwriteModal: document.querySelector("[data-overwrite-modal]"),
  overwriteMsg: document.querySelector("[data-overwrite-msg]"),
  overwriteClose: document.querySelector("[data-overwrite-close]"),
  overwriteCancel: document.querySelector("[data-overwrite-cancel]"),
  overwriteConfirm: document.querySelector("[data-overwrite-confirm]")
};

const state = {
  selectedCourse: "tads",
  firebaseConfigured: false,
  firebaseConfig: { projectId: "", apiKey: "", authDomain: "" },
  authUser: null,
  latestResult: null,
  activeRunId: null,
  isRunning: false,
  isAuthenticating: false,
  authPollTimer: null
};

const showAlert = (el, msg, variant = "error") => {
  if (!el) return;
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    el.classList.remove("alert-success");
    return;
  }
  el.classList.toggle("alert-success", variant === "success");
  el.textContent = msg;
  el.hidden = false;
};

const nowTime = () =>
  new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

const setStatusBadge = (mode, label) => {
  if (!els.statusBadge) return;
  els.statusBadge.className = `status-pill is-${mode}`;
  els.statusBadge.textContent = label;
};

const updateProgress = (done, total, text) => {
  const safeTotal = Math.max(0, Number(total) || 0);
  const safeDone = Math.max(0, Math.min(safeTotal || done, Number(done) || 0));
  const pct = safeTotal > 0 ? Math.round((safeDone / safeTotal) * 100) : 0;
  if (els.progressPct) els.progressPct.textContent = `${pct}%`;
  if (els.progressText && text) els.progressText.textContent = text;
  if (els.progressFill) els.progressFill.style.width = `${pct}%`;
};

const appendLog = (level, msg) => {
  if (!els.logList) return;
  if (els.logList.firstElementChild && els.logList.firstElementChild.classList.contains("is-muted")) {
    els.logList.textContent = "";
  }
  const line = document.createElement("div");
  line.className = `log-line is-${level || "info"}`;
  const t = document.createElement("span");
  t.className = "log-time";
  t.textContent = `[${nowTime()}]`;
  const m = document.createElement("span");
  m.textContent = msg;
  line.appendChild(t);
  line.appendChild(m);
  els.logList.appendChild(line);
  els.logList.scrollTop = els.logList.scrollHeight;
};

const clearLog = () => {
  if (!els.logList) return;
  els.logList.textContent = "";
  const d = document.createElement("div");
  d.className = "log-line is-muted";
  d.textContent = "Log limpo. Pronto para iniciar uma nova coleta.";
  els.logList.appendChild(d);
  updateProgress(0, 0, "Aguardando início da coleta.");
  setStatusBadge("idle", "Pronto");
};

const refreshTopUi = () => {
  if (els.fbPill) {
    if (!state.firebaseConfigured) {
      els.fbPill.className = "status-pill is-idle";
      els.fbPill.textContent = "Firebase não configurado";
    } else if (!state.authUser) {
      els.fbPill.className = "status-pill is-running";
      els.fbPill.textContent = `Firebase (${state.firebaseConfig.projectId}) · sem login`;
    } else {
      els.fbPill.className = "status-pill is-done";
      els.fbPill.textContent = `Firebase (${state.firebaseConfig.projectId}) · conectado`;
    }
  }

  if (els.authUserPill && els.authLoginBtn && els.authEmail) {
    if (state.authUser) {
      els.authEmail.textContent = state.authUser.email;
      els.authUserPill.hidden = false;
      els.authLoginBtn.hidden = true;
    } else {
      els.authUserPill.hidden = true;
      els.authLoginBtn.hidden = false;
      els.authLoginBtn.disabled = !state.firebaseConfigured;
    }
  }

  const hasData = Boolean(state.latestResult && Array.isArray(state.latestResult.subjects) && state.latestResult.subjects.length);
  if (els.exportJsonBtn) els.exportJsonBtn.disabled = !hasData || state.isRunning;
  if (els.exportCsvBtn) els.exportCsvBtn.disabled = !hasData || state.isRunning;
  if (els.uploadFirebaseBtn) {
    els.uploadFirebaseBtn.disabled = !hasData || state.isRunning || !state.firebaseConfigured || !state.authUser;
  }
};

const updateStats = () => {
  const res = state.latestResult;
  const subjects = res && Array.isArray(res.subjects) ? res.subjects : [];
  const classesCount = subjects.reduce((acc, s) => acc + (Array.isArray(s.classes) ? s.classes.length : 0), 0);

  if (els.statPeriod) els.statPeriod.textContent = res && res.period ? `${res.course.toUpperCase()} ${res.period}` : "—";
  if (els.statSubjects) els.statSubjects.textContent = String(subjects.length);
  if (els.statClasses) els.statClasses.textContent = String(classesCount);
  if (els.statUpdated) {
    els.statUpdated.textContent =
      res && res.scrapedAt ? new Date(res.scrapedAt).toLocaleString("pt-BR") : "—";
  }
};

const populateGradeFilter = () => {
  if (!els.filterGrade) return;
  const subjects = (state.latestResult && state.latestResult.subjects) || [];
  const nums = Array.from(
    new Set(subjects.map((s) => Number(s.period)).filter((n) => Number.isFinite(n) && n > 0))
  ).sort((a, b) => a - b);

  const prev = els.filterGrade.value || "todos";
  els.filterGrade.textContent = "";
  const allOpt = document.createElement("option");
  allOpt.value = "todos";
  allOpt.textContent = "Todos";
  els.filterGrade.appendChild(allOpt);
  for (const n of nums) {
    const opt = document.createElement("option");
    opt.value = String(n);
    opt.textContent = `${n}º período`;
    els.filterGrade.appendChild(opt);
  }
  els.filterGrade.value = nums.map(String).includes(prev) ? prev : "todos";
};

const formatSchedule = (cls) => {
  if (!cls || !Array.isArray(cls.schedule) || !cls.schedule.length) return "N/A";
  return cls.schedule.map((s) => s.label || `${s.day} ${s.start}–${s.end}`).join(" · ");
};

const formatTeachers = (cls) => {
  if (!cls || !Array.isArray(cls.teachers) || !cls.teachers.length) return "N/A";
  return cls.teachers.join(" / ");
};

const renderTable = () => {
  if (!els.tableBody) return;
  const res = state.latestResult;
  const subjects = (res && res.subjects) || [];
  const courseCode = res && res.course ? res.course.toUpperCase() : "N/A";

  const term = (els.filterSearch ? els.filterSearch.value : "").trim().toLowerCase();
  const grade = els.filterGrade ? els.filterGrade.value : "todos";
  const typeFilter = els.filterType ? els.filterType.value : "todos";
  const ofPeriod = els.filterOfPeriod ? els.filterOfPeriod.value : "todos";
  const onlyClasses = Boolean(els.filterOnlyClasses && els.filterOnlyClasses.checked);

  const flatRows = subjects.flatMap((subject) => {
    const classes = Array.isArray(subject.classes) ? subject.classes : [];
    if (classes.length) return classes.map((cls) => ({ subject, cls }));
    return onlyClasses ? [] : [{ subject, cls: null }];
  });

  const filtered = flatRows.filter(({ subject, cls }) => {
    if (grade !== "todos" && String(subject.period) !== grade) return false;
    if (typeFilter !== "todos" && subject.type !== typeFilter) return false;
    if (ofPeriod === "sim" && !subject.subjectOfPeriod) return false;
    if (ofPeriod === "nao" && subject.subjectOfPeriod) return false;

    if (term) {
      const teachers = cls && Array.isArray(cls.teachers) ? cls.teachers.join(" ") : "";
      const location = cls && cls.location ? cls.location : "";
      const sched = cls && Array.isArray(cls.schedule) ? cls.schedule.map((i) => i.label || "").join(" ") : "";
      const haystack = `${courseCode} ${subject.id || ""} ${subject.name || ""} ${teachers} ${location} ${sched}`.toLowerCase();
      if (!haystack.includes(term)) return false;
    }
    return true;
  });

  if (els.tableMeta) {
    els.tableMeta.textContent = subjects.length
      ? `${filtered.length} linha(s) exibida(s) de ${subjects.length} disciplina(s) · ${courseCode} ${res.period || ""}`
      : "Nenhum dado carregado ainda.";
  }

  els.tableBody.textContent = "";
  if (!filtered.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 13;
    td.className = "table-empty";
    td.textContent = subjects.length
      ? "Nenhuma linha encontrada com os filtros atuais."
      : "Execute uma coleta ou abra um JSON local para visualizar os dados.";
    tr.appendChild(td);
    els.tableBody.appendChild(tr);
    return;
  }

  const frag = document.createDocumentFragment();
  for (const { subject, cls } of filtered) {
    const tr = document.createElement("tr");
    const values = [
      courseCode,
      subject.id || "N/A",
      subject.name || "N/A",
      subject.period ? `${subject.period}º` : "N/A",
      subject.typeLabel || TYPE_LABELS[subject.type] || "N/A",
      subject.credits > 0 ? String(subject.credits) : "N/A",
      subject.workload ? `${subject.workload}h` : "N/A",
      cls && cls.classNumber != null ? String(cls.classNumber) : "N/A",
      formatTeachers(cls),
      cls && cls.location ? cls.location : "N/A",
      formatSchedule(cls),
      typeof subject.subjectOfPeriod === "boolean" ? (subject.subjectOfPeriod ? "Sim" : "Não") : "N/A",
      subject.branch ? subject.branch : "N/A"
    ];

    values.forEach((val, idx) => {
      const td = document.createElement("td");
      if (idx === 0) td.classList.add("cell-course");
      if (idx === 1) td.classList.add("cell-code");
      if (idx === 2) td.classList.add("cell-name");
      if (val === "N/A") td.classList.add("cell-na");
      td.textContent = val;
      tr.appendChild(td);
    });
    frag.appendChild(tr);
  }
  els.tableBody.appendChild(frag);
};

const applyLoadedResult = (result) => {
  state.latestResult = result;
  if (result && result.course) setSelectedCourse(result.course);
  updateStats();
  populateGradeFilter();
  renderTable();
  refreshTopUi();
};

const setSelectedCourse = (course) => {
  if (course !== "tads" && course !== "cc") return;
  state.selectedCourse = course;
  els.courseBtns.forEach((btn) => {
    const active = btn.dataset.courseBtn === course;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-pressed", String(active));
  });
  if (els.modalCourse) els.modalCourse.value = course;
};

/* ---------- API State / Config / Google Auth ---------- */

const syncStateFromServer = async () => {
  const resp = await fetch("/api/state");
  const data = await resp.json();
  state.firebaseConfigured = Boolean(data.firebaseConfigured);
  state.firebaseConfig = data.firebaseConfig || { projectId: "", apiKey: "", authDomain: "" };
  state.authUser = data.authUser || null;
  if (data.latestResult) applyLoadedResult(data.latestResult);
  else refreshTopUi();
};

const openFbModal = () => {
  showAlert(els.fbModalAlert, "");
  if (els.fbProjectId) els.fbProjectId.value = state.firebaseConfig.projectId || "";
  if (els.fbApiKey) els.fbApiKey.value = state.firebaseConfig.apiKey || "";
  if (els.fbAuthDomain) els.fbAuthDomain.value = state.firebaseConfig.authDomain || "";
  if (els.fbModal) els.fbModal.hidden = false;
};

const closeFbModal = () => {
  if (els.fbModal) els.fbModal.hidden = true;
};

if (els.fbProjectId && els.fbAuthDomain) {
  els.fbProjectId.addEventListener("input", () => {
    const pid = els.fbProjectId.value.trim();
    if (!els.fbAuthDomain.value || els.fbAuthDomain.dataset.auto !== "false") {
      els.fbAuthDomain.value = pid ? `${pid}.firebaseapp.com` : "";
    }
  });
  els.fbAuthDomain.addEventListener("input", () => {
    els.fbAuthDomain.dataset.auto = els.fbAuthDomain.value.trim() ? "false" : "true";
  });
}

if (els.fbForm) {
  els.fbForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    showAlert(els.fbModalAlert, "");
    const resp = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        projectId: els.fbProjectId.value.trim(),
        apiKey: els.fbApiKey.value.trim(),
        authDomain: els.fbAuthDomain.value.trim()
      })
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      showAlert(els.fbModalAlert, (payload.error && payload.error.message) || "Erro ao salvar configuração.");
      return;
    }
    state.firebaseConfigured = true;
    state.firebaseConfig = payload.firebaseConfig;
    closeFbModal();
    refreshTopUi();
    showAlert(els.globalAlert, "Configuração do Firebase salva localmente.", "success");
  });
}

const startGoogleAuth = async () => {
  showAlert(els.globalAlert, "");
  const resp = await fetch("/api/auth/start", { method: "POST" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    showAlert(els.globalAlert, (data.error && data.error.message) || "Não foi possível iniciar o login Google.");
    return;
  }
  showAlert(els.globalAlert, "Conclua o login com Google na aba do navegador que foi aberta...", "success");
  if (state.authPollTimer) window.clearInterval(state.authPollTimer);
  let attempts = 0;
  state.authPollTimer = window.setInterval(async () => {
    attempts += 1;
    await syncStateFromServer();
    if (state.authUser || attempts > 90) {
      window.clearInterval(state.authPollTimer);
      state.authPollTimer = null;
      if (state.authUser) {
        showAlert(els.globalAlert, `Conectado como ${state.authUser.email}.`, "success");
      }
    }
  }, 1000);
};

/* ---------- Raspagem SSE ---------- */

const setRunningUi = (running) => {
  state.isRunning = running;
  if (els.openScrapeModalBtn) els.openScrapeModalBtn.disabled = running;
  if (els.cancelScrapeBtn) els.cancelScrapeBtn.hidden = !running;
  refreshTopUi();
};

const setModalBusy = (busy) => {
  state.isAuthenticating = busy;
  if (els.scrapeSubmitBtn) {
    els.scrapeSubmitBtn.disabled = busy;
    els.scrapeSubmitBtn.textContent = busy ? "Autenticando no Aluno Online..." : "Entrar e iniciar coleta";
  }
};

const openScrapeModal = () => {
  if (state.isRunning) return;
  showAlert(els.globalAlert, "");
  showAlert(els.scrapeModalAlert, "");
  setModalBusy(false);
  if (els.modalCourse) els.modalCourse.value = state.selectedCourse;
  if (els.modalSenha) {
    els.modalSenha.value = "";
    els.modalSenha.type = "password";
  }
  if (els.togglePassBtn) els.togglePassBtn.textContent = "Mostrar";
  if (els.scrapeModal) els.scrapeModal.hidden = false;
  if (els.modalMatricula) els.modalMatricula.focus();
};

const closeScrapeModal = (force = false) => {
  if (state.isAuthenticating && !force) return;
  if (els.modalSenha) els.modalSenha.value = "";
  if (els.scrapeModal) els.scrapeModal.hidden = true;
  setModalBusy(false);
};

const parseSseBlock = (block) => {
  const lines = block.split(/\r?\n/);
  let eventType = "message";
  const dataLines = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    return { type: eventType, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
};

const startScrape = async () => {
  showAlert(els.scrapeModalAlert, "");
  const course = els.modalCourse.value;
  const subjectFilter = els.modalScope.value;
  const matricula = els.modalMatricula.value.trim();
  const senha = els.modalSenha.value;
  const period = els.modalPeriod.value.trim();

  if (!matricula || !senha) {
    showAlert(els.scrapeModalAlert, "Informe a matrícula e a senha do Aluno Online.");
    return;
  }

  setSelectedCourse(course);
  setModalBusy(true);
  setRunningUi(true);
  setStatusBadge("running", "Autenticando...");
  updateProgress(0, 0, "Autenticando no Aluno Online...");
  appendLog("info", `Preparando coleta de ${course.toUpperCase()}...`);

  let authConfirmed = false;
  try {
    const startResp = await fetch("/api/scrape/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course, subjectFilter, matricula, senha, period })
    });
    const startData = await startResp.json().catch(() => ({}));
    if (!startResp.ok) {
      const msg = (startData.error && startData.error.message) || "Erro ao iniciar coleta.";
      showAlert(els.scrapeModalAlert, msg);
      setModalBusy(false);
      setRunningUi(false);
      setStatusBadge("error", "Erro");
      return;
    }

    state.activeRunId = startData.runId;
    const streamResp = await fetch(`/api/scrape/stream/${state.activeRunId}`);
    const reader = streamResp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sepIdx = buffer.indexOf("\n\n");
      while (sepIdx !== -1) {
        const block = buffer.slice(0, sepIdx);
        buffer = buffer.slice(sepIdx + 2);
        const parsed = parseSseBlock(block);
        if (parsed) {
          const { type, data } = parsed;
          if (type === "log") {
            appendLog(data.level, data.message);
          } else if (type === "auth_ok") {
            authConfirmed = true;
            closeScrapeModal(true);
            setStatusBadge("running", `Coletando ${data.period || ""}`);
          } else if (type === "progress") {
            updateProgress(data.done, data.total, `${data.done} / ${data.total} disciplinas consultadas`);
          } else if (type === "complete") {
            applyLoadedResult(data);
            setStatusBadge("done", "Concluído");
            showAlert(
              els.globalAlert,
              `Coleta concluída: ${data.subjects.length} disciplina(s) em ${data.course.toUpperCase()} (${data.period}). Você já pode exportar JSON/CSV ou subir para o Firebase.`,
              "success"
            );
          } else if (type === "error") {
            const msg = data.message || "Falha na coleta.";
            appendLog("error", `[${data.code || "ERROR"}] ${msg}`);
            if (!authConfirmed) {
              setModalBusy(false);
              showAlert(els.scrapeModalAlert, msg);
              setStatusBadge("error", "Falha no login");
            } else {
              const isCancel = data.code === "CANCELLED";
              setStatusBadge(isCancel ? "idle" : "error", isCancel ? "Cancelado" : "Erro");
              showAlert(els.globalAlert, msg);
            }
          }
        }
        sepIdx = buffer.indexOf("\n\n");
      }
    }
  } catch {
    const msg = "Falha de comunicação interna ao executar a coleta.";
    appendLog("error", msg);
    if (!authConfirmed) showAlert(els.scrapeModalAlert, msg);
    else showAlert(els.globalAlert, msg);
  } finally {
    if (authConfirmed && els.modalSenha) els.modalSenha.value = "";
    setModalBusy(false);
    setRunningUi(false);
  }
};

/* ---------- Exportação local e envio ao Firebase ---------- */

const uploadToFirebase = async (confirmOverwrite = false) => {
  showAlert(els.globalAlert, "");
  if (els.uploadFirebaseBtn) els.uploadFirebaseBtn.disabled = true;
  try {
    const resp = await fetch("/api/firebase/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmOverwrite })
    });
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 409 && data.error && data.error.code === "PERIOD_EXISTS") {
      if (els.overwriteMsg) {
        els.overwriteMsg.textContent = `${data.error.message} Se a coleta atual for parcial (Obrigatórias ou Definidas), os demais tipos já salvos serão preservados.`;
      }
      if (els.overwriteModal) els.overwriteModal.hidden = false;
      return;
    }
    if (!resp.ok) {
      showAlert(els.globalAlert, (data.error && data.error.message) || "Erro ao enviar para o Firebase.");
      if (resp.status === 401) await syncStateFromServer();
      return;
    }
    const mergedTxt = data.merged ? " (mesclado com tipos já salvos)" : "";
    appendLog("ok", `Enviado ao Firestore: ${data.course.toUpperCase()} ${data.period} (${data.savedCount} disciplinas)${mergedTxt}.`);
    showAlert(
      els.globalAlert,
      `Catálogo ${data.course.toUpperCase()} (${data.period}) enviado ao Firebase com sucesso!`,
      "success"
    );
  } finally {
    refreshTopUi();
  }
};

/* ---------- Eventos ---------- */

els.courseBtns.forEach((btn) =>
  btn.addEventListener("click", () => setSelectedCourse(btn.dataset.courseBtn))
);

if (els.openFbModalBtn) els.openFbModalBtn.addEventListener("click", openFbModal);
if (els.fbModalClose) els.fbModalClose.addEventListener("click", closeFbModal);
if (els.fbModalCancel) els.fbModalCancel.addEventListener("click", closeFbModal);
if (els.authLoginBtn) els.authLoginBtn.addEventListener("click", startGoogleAuth);
if (els.authLogoutBtn) {
  els.authLogoutBtn.addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    state.authUser = null;
    refreshTopUi();
  });
}

if (els.openScrapeModalBtn) els.openScrapeModalBtn.addEventListener("click", openScrapeModal);
if (els.scrapeModalClose) els.scrapeModalClose.addEventListener("click", () => closeScrapeModal(false));
if (els.scrapeModalCancel) els.scrapeModalCancel.addEventListener("click", () => closeScrapeModal(false));
if (els.clearLogBtn) els.clearLogBtn.addEventListener("click", clearLog);
if (els.cancelScrapeBtn) {
  els.cancelScrapeBtn.addEventListener("click", async () => {
    if (!state.activeRunId) return;
    await fetch(`/api/scrape/cancel/${state.activeRunId}`, { method: "POST" });
  });
}

if (els.togglePassBtn && els.modalSenha) {
  els.togglePassBtn.addEventListener("click", () => {
    const show = els.modalSenha.type === "password";
    els.modalSenha.type = show ? "text" : "password";
    els.togglePassBtn.textContent = show ? "Ocultar" : "Mostrar";
  });
}

if (els.scrapeForm) {
  els.scrapeForm.addEventListener("submit", (e) => {
    e.preventDefault();
    startScrape();
  });
}

if (els.exportJsonBtn) {
  els.exportJsonBtn.addEventListener("click", async () => {
    const resp = await fetch("/api/export/json", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const data = await resp.json().catch(() => ({}));
    if (data.ok) showAlert(els.globalAlert, `JSON salvo em: ${data.path}`, "success");
    else if (data.error) showAlert(els.globalAlert, data.error.message);
  });
}

if (els.exportCsvBtn) {
  els.exportCsvBtn.addEventListener("click", async () => {
    const resp = await fetch("/api/export/csv", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    const data = await resp.json().catch(() => ({}));
    if (data.ok) showAlert(els.globalAlert, `CSV salvo em: ${data.path}`, "success");
    else if (data.error) showAlert(els.globalAlert, data.error.message);
  });
}

if (els.importJsonBtn) {
  els.importJsonBtn.addEventListener("click", async () => {
    const resp = await fetch("/api/import/json", { method: "POST" });
    const data = await resp.json().catch(() => ({}));
    if (data.ok && data.result) {
      applyLoadedResult(data.result);
      appendLog("ok", `JSON local carregado (${data.result.subjects.length} disciplinas).`);
      showAlert(els.globalAlert, `Arquivo carregado: ${data.path}`, "success");
    } else if (data.error) {
      showAlert(els.globalAlert, data.error.message);
    }
  });
}

if (els.uploadFirebaseBtn) {
  els.uploadFirebaseBtn.addEventListener("click", () => uploadToFirebase(false));
}

if (els.overwriteClose) els.overwriteClose.addEventListener("click", () => { els.overwriteModal.hidden = true; });
if (els.overwriteCancel) els.overwriteCancel.addEventListener("click", () => { els.overwriteModal.hidden = true; });
if (els.overwriteConfirm) {
  els.overwriteConfirm.addEventListener("click", async () => {
    els.overwriteModal.hidden = true;
    await uploadToFirebase(true);
  });
}

[els.filterSearch, els.filterGrade, els.filterType, els.filterOfPeriod, els.filterOnlyClasses].forEach((el) => {
  if (!el) return;
  const evt = el.tagName === "INPUT" && el.type === "search" ? "input" : "change";
  el.addEventListener(evt, renderTable);
});

syncStateFromServer();
