(function () {
  const form = document.getElementById("eval-form");
  const btnEvaluate = document.getElementById("btn-evaluate");
  const btnResults = document.getElementById("btn-results");
  const logOutput = document.getElementById("log-output");
  const runStatus = document.getElementById("run-status");
  const apiModelSelect = document.getElementById("api_model");

  let currentRunId = null;
  let eventSource = null;
  let runsRefreshTimer = null;
  let logLines = [];

  const dateRe = /^\d{2}-\d{2}-\d{4}$/;
  function isTraceProgress(line) {
    return String(line).startsWith("Traces downloaded:");
  }

  function renderLogs() {
    logOutput.textContent = logLines.length ? logLines.join("\n") + "\n" : "";
    logOutput.scrollTop = logOutput.scrollHeight;
  }

  function pushLogLine(line, replaceLast) {
    if (
      replaceLast ||
      (logLines.length && isTraceProgress(line) && isTraceProgress(logLines[logLines.length - 1]))
    ) {
      if (logLines.length && isTraceProgress(line)) {
        logLines[logLines.length - 1] = line;
      } else {
        logLines.push(line);
      }
    } else {
      logLines.push(line);
    }
    renderLogs();
  }

  function mandatoryValid() {
    const study = form.study_name.value.trim();
    if (!study || !/^[A-Za-z0-9_-]+$/.test(study)) return false;
    if (!form.tenant_name.value.trim()) return false;
    if (!form.assistant_origin_id.value.trim()) return false;
    if (!dateRe.test(form.date_range_start.value.trim())) return false;
    if (!dateRe.test(form.date_range_end.value.trim())) return false;
    if (!form.hypothesis.value.trim()) return false;
    return true;
  }

  function refreshEvaluateButton() {
    const running = btnEvaluate.dataset.running === "1";
    btnEvaluate.disabled = running || !mandatoryValid();
  }

  form.querySelectorAll("input, textarea, select").forEach((el) => {
    el.addEventListener("input", refreshEvaluateButton);
    el.addEventListener("change", refreshEvaluateButton);
  });

  function setStatus(text, cls) {
    runStatus.textContent = text;
    runStatus.className = "status-line" + (cls ? " " + cls : "");
  }

  async function loadLlmOptions() {
    const res = await fetch("/api/llm-options");
    const data = await res.json();
    apiModelSelect.innerHTML = "";
    (data.api_models || []).forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      apiModelSelect.appendChild(opt);
    });
    const defaults = data.defaults || {};
    if (defaults.api_model) apiModelSelect.value = defaults.api_model;
    if (defaults.effort) form.reasoning_effort.value = defaults.effort;
    refreshEvaluateButton();
  }

  function closeStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    if (runsRefreshTimer) {
      clearInterval(runsRefreshTimer);
      runsRefreshTimer = null;
    }
  }

  function startLogStream(runId) {
    closeStream();
    runsRefreshTimer = setInterval(loadRunsList, 15000);
    eventSource = new EventSource(`/api/runs/${runId}/logs/stream`);
    eventSource.onmessage = (ev) => {
      let payload;
      try {
        payload = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (payload.event === "done") {
        closeStream();
        btnEvaluate.dataset.running = "0";
        refreshEvaluateButton();
        if (payload.status === "success") {
          setStatus("Pipeline finished successfully.", "success");
          btnResults.disabled = false;
        } else {
          setStatus(`Pipeline failed (exit code ${payload.exit_code}).`, "failed");
          btnResults.disabled = true;
        }
        loadRunsList();
        return;
      }
      if (payload.line) pushLogLine(payload.line, !!payload.replace_last);
    };
    eventSource.onerror = () => {
      closeStream();
    };
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!mandatoryValid()) return;

    btnResults.disabled = true;
    btnEvaluate.dataset.running = "1";
    refreshEvaluateButton();
    logLines = [];
    renderLogs();
    setStatus("Starting pipeline…", "running");

    const body = {
      study_name: form.study_name.value.trim(),
      tenant_name: form.tenant_name.value.trim(),
      assistant_origin_id: form.assistant_origin_id.value.trim(),
      date_range_start: form.date_range_start.value.trim(),
      date_range_end: form.date_range_end.value.trim(),
      hypothesis: form.hypothesis.value.trim(),
      api_model: form.api_model.value,
      reasoning_effort: form.reasoning_effort.value,
      concurrency: parseInt(form.concurrency.value, 10) || 10,
      limit: parseInt(form.limit.value, 10) || 10000,
    };

    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        const detail = Array.isArray(data.detail)
          ? data.detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : data.detail;
        setStatus(detail || "Failed to start run.", "failed");
        btnEvaluate.dataset.running = "0";
        refreshEvaluateButton();
        return;
      }
      currentRunId = data.run_id;
      setStatus(`Run ${currentRunId} in progress…`, "running");
      loadRunsList();
      startLogStream(currentRunId);
    } catch (err) {
      setStatus(String(err), "failed");
      btnEvaluate.dataset.running = "0";
      refreshEvaluateButton();
    }
  });

  btnResults.addEventListener("click", () => {
    if (!currentRunId) return;
    window.open(`/results/${currentRunId}`, "_blank");
  });

  async function loadRunsList() {
    const container = document.getElementById("runs-list");
    if (!container) return;
    try {
      const res = await fetch("/api/runs/list");
      const data = await res.json();
      const runs = data.runs || [];
      if (!runs.length) {
        container.innerHTML = '<div class="runs-empty">No saved runs yet.</div>';
        return;
      }
      container.innerHTML = runs
        .map((run) => {
          const canResults = run.results_available;
          return (
            '<div class="run-row" data-run-id="' +
            escapeHtml(run.run_id) +
            '">' +
            '<span class="study-name" title="' +
            escapeHtml(run.study_name) +
            '">' +
            escapeHtml(run.study_name) +
            '</span>' +
            '<span class="size-gb">' +
            escapeHtml(String(run.size_gb)) +
            " GB</span>" +
            '<button type="button" class="link-btn btn-run-results" ' +
            (canResults ? "" : "disabled") +
            ">See results</button>" +
            '<button type="button" class="icon-btn btn-run-delete" title="Delete study" aria-label="Delete study">🗑</button>' +
            "</div>"
          );
        })
        .join("");

      container.querySelectorAll(".btn-run-results").forEach((btn, idx) => {
        btn.addEventListener("click", () => {
          const row = btn.closest(".run-row");
          const id = row && row.getAttribute("data-run-id");
          if (id) window.open("/results/" + id, "_blank");
        });
      });
      container.querySelectorAll(".btn-run-delete").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const row = btn.closest(".run-row");
          const id = row && row.getAttribute("data-run-id");
          if (!id) return;
          if (!confirm("Delete this study and all its artifacts?")) return;
          const del = await fetch("/api/runs/" + id, { method: "DELETE" });
          if (del.ok) {
            if (currentRunId === id) currentRunId = null;
            loadRunsList();
          }
        });
      });
    } catch {
      container.innerHTML = '<div class="runs-empty">Could not load runs.</div>';
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  document.getElementById("btn-delete-all").addEventListener("click", async () => {
    if (!confirm("Delete ALL studies from the server? This cannot be undone.")) return;
    const res = await fetch("/api/runs", { method: "DELETE" });
    if (res.ok) {
      currentRunId = null;
      btnResults.disabled = true;
      loadRunsList();
    }
  });

  loadLlmOptions();
  refreshEvaluateButton();
  loadRunsList();
})();
