/* OCR Console (P3-4): upload → theo dõi job → xem kết quả → promote.
   Backend API có sẵn từ lâu (/ocr/jobs...); trang này chỉ là tay cầm. */
"use strict";

const $ = (id) => document.getElementById(id);

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const key = localStorage.getItem("lac.apikey") || "";
  if (key) headers["X-API-Key"] = key;
  const access = localStorage.getItem("lac.access") || "";
  if (access) headers.Authorization = `Bearer ${access}`;
  return headers;
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: authHeaders(options.headers || {}) });
  if (response.status === 401) {
    window.location.href = "/ui/";
    throw new Error("401");
  }
  const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `Lỗi ${response.status}`);
  return data;
}

function notice(text, isError = false) {
  const el = $("ocr-notice");
  el.textContent = text;
  el.style.color = isError ? "#e0575b" : "";
}

let activeJobId = null;
let pollTimer = null;

function renderJob(job) {
  $("ocr-job-panel").hidden = false;
  $("ocr-job-name").textContent = job.filename || job.id;
  $("ocr-job-stage").textContent = job.stage || "";
  $("ocr-job-status").textContent = job.status || "";
  $("ocr-job-pages").textContent = `${job.current_page || 0}/${job.total_pages || "?"}`;
  $("ocr-progress").style.width = `${job.progress || 0}%`;
  const events = (job.events || []).slice(-6);
  $("ocr-events").replaceChildren(...events.map((event) => {
    const item = document.createElement("li");
    item.textContent = `${event.stage}: ${event.message}`;
    return item;
  }));
  const running = job.status === "queued" || job.status === "running";
  $("ocr-cancel").hidden = !running;
  $("ocr-promote").hidden = job.status !== "completed";
  $("ocr-export").hidden = job.status !== "completed";
  const resultBox = $("ocr-result");
  if (job.status === "completed" && Array.isArray(job.pages) && job.pages.length) {
    const preview = job.pages.map((page) => `── Trang ${page.page} ──\n${page.text || ""}`).join("\n\n");
    resultBox.hidden = false;
    resultBox.textContent = preview.slice(0, 6000) + (preview.length > 6000 ? "\n…(đã cắt bớt)" : "");
  } else if (job.status !== "completed") {
    resultBox.hidden = true;
  }
}

async function track(jobId) {
  activeJobId = jobId;
  clearTimeout(pollTimer);
  try {
    const job = await request(`/api/ocr/jobs/${encodeURIComponent(jobId)}`);
    renderJob(job);
    if (job.status === "queued" || job.status === "running") {
      pollTimer = setTimeout(() => track(jobId), 2500);
    } else {
      loadHistory();
    }
  } catch (error) {
    notice(error.message, true);
  }
}

async function loadHistory() {
  const tbody = $("ocr-history");
  try {
    const payload = await request("/api/ocr/history");
    const runs = payload.runs || [];
    if (!runs.length) {
      tbody.replaceChildren(Object.assign(document.createElement("tr"), { innerHTML: '<td colspan="4" class="muted">Chưa có lần chạy nào.</td>' }));
      return;
    }
    tbody.replaceChildren(...runs.map((run) => {
      const row = document.createElement("tr");
      const name = document.createElement("td");
      name.textContent = run.filename || run.id;
      const status = document.createElement("td");
      status.textContent = run.status || "?";
      const model = document.createElement("td");
      model.textContent = run.model || "";
      const actions = document.createElement("td");
      const view = document.createElement("button");
      view.textContent = "Xem";
      view.onclick = () => track(run.id);
      const remove = document.createElement("button");
      remove.textContent = "Xóa";
      remove.onclick = async () => {
        remove.disabled = true;
        try { await request(`/api/ocr/history/${encodeURIComponent(run.id)}`, { method: "DELETE" }); } catch (error) { notice(error.message, true); }
        loadHistory();
      };
      actions.append(view, document.createTextNode(" "), remove);
      row.append(name, status, model, actions);
      return row;
    }));
  } catch (error) {
    tbody.replaceChildren(Object.assign(document.createElement("tr"), { innerHTML: `<td colspan="4" class="muted">${error.message}</td>` }));
  }
}

$("ocr-upload").onclick = async () => {
  const file = $("ocr-file").files[0];
  if (!file) { notice("Chọn một tệp PDF hoặc ảnh trước.", true); return; }
  const body = new FormData();
  body.append("file", file);
  notice("Đang tải lên…");
  $("ocr-upload").disabled = true;
  try {
    const job = await request(`/api/ocr/jobs?dpi=${encodeURIComponent($("ocr-dpi").value)}`, { method: "POST", body });
    notice(`Đã tạo job ${job.id}.`);
    track(job.id);
  } catch (error) {
    notice(error.message, true);
  }
  $("ocr-upload").disabled = false;
};

$("ocr-cancel").onclick = async () => {
  if (!activeJobId) return;
  try { await request(`/api/ocr/jobs/${encodeURIComponent(activeJobId)}/cancel`, { method: "POST" }); } catch (error) { notice(error.message, true); }
};

$("ocr-promote").onclick = async () => {
  if (!activeJobId) return;
  $("ocr-promote").disabled = true;
  try {
    await request(`/api/ocr/jobs/${encodeURIComponent(activeJobId)}/promote`, { method: "POST" });
    notice("Đã gửi vào pipeline tài liệu — theo dõi trạng thái index ở trang chat (Tài liệu).");
  } catch (error) {
    notice(error.message, true);
  }
  $("ocr-promote").disabled = false;
};

$("ocr-export").onclick = async () => {
  if (!activeJobId) return;
  try {
    const response = await fetch(`/api/ocr/jobs/${encodeURIComponent(activeJobId)}/export`, { headers: authHeaders() });
    if (!response.ok) throw new Error(`Lỗi ${response.status}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = Object.assign(document.createElement("a"), { href: url, download: `${activeJobId}.zip` });
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    notice(error.message, true);
  }
};

loadHistory();
