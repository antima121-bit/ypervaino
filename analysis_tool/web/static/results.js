(function () {
  const runId = window.location.pathname.split("/").filter(Boolean).pop();

  const panels = {
    dashboard: document.getElementById("panel-dashboard"),
    rule_engine: document.getElementById("panel-rule_engine"),
    llm_judge: document.getElementById("panel-llm_judge"),
    information: document.getElementById("panel-information"),
  };

  const errorBanner = document.getElementById("error-banner");
  const runMeta = document.getElementById("run-meta");

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      const key = tab.dataset.tab;
      panels[key].classList.add("active");
    });
  });

  function renderDashboard(data) {
    const lines = (data.dashboard && data.dashboard.summary_lines) || [];
    panels.dashboard.innerHTML =
      '<div class="summary-block">' + lines.map(escapeHtml).join("\n") + "</div>";
  }

  function renderRuleEngine(data) {
    const hyps = (data.rule_engine && data.rule_engine.hypotheses) || [];
    if (!hyps.length) {
      panels.rule_engine.innerHTML = "<p>No rule engine results.</p>";
      return;
    }
    panels.rule_engine.innerHTML = hyps
      .map((h) => {
        const ids = h.failed_session_ids || [];
        const list =
          ids.length === 0
            ? "<p>No failed sessions.</p>"
            : "<ul class=\"session-list\">" +
              ids.map((id) => "<li>" + escapeHtml(id) + "</li>").join("") +
              "</ul>";
        return (
          '<div class="hyp-block"><h3>' +
          escapeHtml(h.title || h.hypothesis_id) +
          "</h3>" +
          list +
          "</div>"
        );
      })
      .join("");
  }

  function judgeSection(title, rows) {
    if (!rows.length) return "<p>None.</p>";
    return (
      '<div class="judge-section"><h4>' +
      escapeHtml(title) +
      "</h4>" +
      rows
        .map(
          (r) =>
            '<div class="judge-row"><div class="sid">' +
            escapeHtml(r.session_id) +
            '</div><div>' +
            escapeHtml(r.description || "") +
            "</div></div>"
        )
        .join("") +
      "</div>"
    );
  }

  function renderLlmJudge(data) {
    const hyps = (data.llm_judge && data.llm_judge.hypotheses) || [];
    if (!hyps.length) {
      panels.llm_judge.innerHTML = "<p>No LLM judge results.</p>";
      return;
    }
    panels.llm_judge.innerHTML = hyps
      .map((h) => {
        return (
          '<div class="hyp-block"><h3>' +
          escapeHtml(h.title || h.hypothesis_id) +
          "</h3>" +
          judgeSection("Failed (LLM)", h.failed || []) +
          judgeSection("Passed (LLM)", h.passed || []) +
          "</div>"
        );
      })
      .join("");
  }

  function renderInformation(data) {
    const raw = data.information && data.information.raw;
    if (!raw) {
      panels.information.innerHTML = "<p>No generated hypothesis data.</p>";
      return;
    }
    panels.information.innerHTML =
      '<pre class="json-block">' + escapeHtml(JSON.stringify(raw, null, 2)) + "</pre>";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function load() {
    runMeta.textContent = "Run ID: " + runId;
    try {
      const res = await fetch("/api/runs/" + runId + "/results");
      const data = await res.json();
      if (!res.ok) {
        errorBanner.hidden = false;
        errorBanner.textContent = data.detail || "Could not load results.";
        return;
      }
      renderDashboard(data);
      renderRuleEngine(data);
      renderLlmJudge(data);
      renderInformation(data);
    } catch (e) {
      errorBanner.hidden = false;
      errorBanner.textContent = String(e);
    }
  }

  load();
})();
