/* Bảng điều khiển quản lý agent — chỉ đọc, tự làm mới mỗi 20 giây. */
"use strict";

/* $, el, theme/prefs, authHeaders và requestJson nằm ở /ui/common.js (T8),
   nạp trước file này. Chính trang này là lý do món nợ tồn tại: bản chép
   riêng của nó từng quên X-API-Key, rồi quên luôn refresh token. */

function relativeTime(iso) {
  if (!iso) return "chưa có";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "?";
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return "vừa xong";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} phút trước`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} giờ trước`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)} ngày trước`;
  return new Date(iso).toLocaleDateString("vi-VN");
}

function activityState(iso, activeMinutes = 10) {
  if (!iso) return "unknown";
  const minutes = (Date.now() - new Date(iso).getTime()) / 60000;
  return minutes <= activeMinutes ? "ok" : "degraded";
}

function kvRow(label, value) {
  const row = el("div", "kv");
  row.append(el("b", "", label));
  row.append(el("span", "", value));
  return row;
}

function statCard(value, label) {
  const card = el("div", "stat-card");
  card.append(el("b", "", String(value)));
  card.append(el("span", "", label));
  return card;
}

/* Dashboard là mặt admin: 401 mà refresh cũng không cứu được thì đẩy về
   trang đăng nhập. requestJson đã thử refresh MỘT lần trước khi ném ra —
   trước T8 bước đó không tồn tại ở đây, nên access token hết hạn là văng
   thẳng ra giữa lúc đang xem dù refresh token còn hạn. */
async function fetchJson(path) {
  try {
    return await requestJson(path);
  } catch (error) {
    if (error.status === 401) window.location.href = "/ui/";
    throw error;
  }
}

const TURN_LABELS = {
  queued: "đang chờ", running: "đang chạy", completed: "hoàn tất",
  failed: "thất bại", cancelled: "đã hủy",
};

function tableNotice(tbody, text, colSpan) {
  const row = el("tr");
  row.append(Object.assign(el("td", "muted", text), { colSpan }));
  tbody.replaceChildren(row);
}

function render(stats, health, metrics, models, conversations) {
  // ── Stat cards: chỉ vẽ lại khi có dữ liệu mới, tránh xóa số cũ khi lỗi ──
  const grid = $("stat-grid");
  if (stats || metrics) {
    grid.replaceChildren();
    if (stats) {
      grid.append(statCard(stats.web.conversation_count, "Hội thoại web"));
      grid.append(statCard(stats.web.message_count, "Tin nhắn web"));
      grid.append(statCard(`${stats.discord.active_session_count}/${stats.discord.session_count}`, "Phiên Discord active"));
      grid.append(statCard(stats.discord.turn_counts.completed || 0, "Lượt Discord hoàn tất"));
    }
    if (metrics) {
      grid.append(statCard(metrics.documents_indexed ?? 0, "Tài liệu đã index"));
      grid.append(statCard(metrics.jobs_failed ?? 0, "Job lỗi"));
    }
  }

  // ── Web agent ──
  const webKv = $("web-kv");
  if (stats) {
    webKv.replaceChildren(
      kvRow("Hoạt động gần nhất", relativeTime(stats.web.last_activity_at)),
      kvRow("Tổng hội thoại", String(stats.web.conversation_count)),
      kvRow("Tổng tin nhắn", String(stats.web.message_count)),
    );
    $("web-dot").dataset.state = activityState(stats.web.last_activity_at);
  } else {
    webKv.replaceChildren(kvRow("Lỗi", "Không tải được số liệu"));
    $("web-dot").dataset.state = "down";
  }
  const webRecent = $("web-recent");
  webRecent.replaceChildren();
  // null = fetch lỗi, [] = thật sự chưa có — hai trạng thái khác nhau.
  if (conversations === null) {
    tableNotice(webRecent, "Không tải được danh sách hội thoại.", 3);
  }
  const recentConversations = (conversations || []).slice(0, 6);
  if (conversations !== null && !recentConversations.length) {
    tableNotice(webRecent, "Chưa có hội thoại nào.", 3);
  }
  for (const conversation of recentConversations) {
    const row = el("tr");
    const titleCell = el("td");
    const link = el("a", "", conversation.title || `Trò chuyện ${new Date(conversation.created_at).toLocaleDateString("vi-VN")}`);
    link.href = `/ui/#c=${encodeURIComponent(conversation.id)}`;
    titleCell.append(link);
    row.append(titleCell);
    row.append(el("td", "", String(conversation.message_count)));
    row.append(el("td", "", relativeTime(conversation.updated_at)));
    webRecent.append(row);
  }

  // ── Discord agent ──
  if (stats) {
    const discordKv = $("discord-kv");
    const turnText = Object.entries(stats.discord.turn_counts)
      .map(([status, count]) => `${TURN_LABELS[status] || status}: ${count}`)
      .join(" · ") || "chưa có lượt nào";
    discordKv.replaceChildren(
      kvRow("Hoạt động gần nhất", relativeTime(stats.discord.last_activity_at)),
      kvRow("Phiên (active/tổng)", `${stats.discord.active_session_count}/${stats.discord.session_count}`),
      kvRow("Tin đã gửi lên Discord", String(stats.discord.delivery_count)),
      kvRow("Lượt theo trạng thái", turnText),
    );
    $("discord-dot").dataset.state = activityState(stats.discord.last_activity_at);

    const discordRecent = $("discord-recent");
    discordRecent.replaceChildren();
    if (!stats.discord.recent_sessions.length) {
      tableNotice(discordRecent, "Bot chưa có phiên nào. Chạy run-discord-bot.bat và nhắn @Ún trong Discord.", 4);
    }
    for (const session of stats.discord.recent_sessions) {
      const row = el("tr");
      const place = session.thread_id ? `thread …${session.thread_id.slice(-6)}` : `kênh …${session.channel_id.slice(-6)}`;
      row.append(el("td", "", `${place} @ guild …${session.guild_id.slice(-6)}`));
      const statusCell = el("td");
      statusCell.append(el("span", `status-pill ${session.status === "active" ? "ok" : ""}`, session.status));
      row.append(statusCell);
      row.append(el("td", "", String(session.turn_count)));
      row.append(el("td", "", relativeTime(session.last_active_at)));
      discordRecent.append(row);
    }
  } else {
    $("discord-kv").replaceChildren(kvRow("Lỗi", "Không tải được số liệu"));
    $("discord-dot").dataset.state = "down";
    tableNotice($("discord-recent"), "Không tải được dữ liệu.", 4);
  }

  // ── Health ──
  if (!health) {
    $("health-grid").replaceChildren(el("div", "muted", "Không tải được trạng thái hệ thống."));
  }
  if (health) {
    // Phai phu HET khoa /health tra ve. Thieu mot khoa thi thanh phan do khong
    // bao gio hien: dau trang bao "suy giam" trong khi moi den deu xanh —
    // backup/backup_worker/memory_ingestion tung roi vao dung cai bay do.
    const componentLabels = {
      postgres: "PostgreSQL", redis: "Redis", qdrant: "Qdrant", ollama: "Ollama",
      worker_ocr: "Worker OCR", worker_index: "Worker Index", worker_memory: "Worker Memory",
      outbox_dispatcher: "Outbox", cleanup_worker: "Cleanup",
      backup: "Sao lưu", backup_worker: "Worker sao lưu", memory_ingestion: "Nạp ghi nhớ",
    };
    const healthGrid = $("health-grid");
    healthGrid.replaceChildren();
    for (const [key, label] of Object.entries(componentLabels)) {
      if (!(key in health)) continue;
      const item = el("div", "health-item");
      const dot = el("span", "dot");
      const value = String(health[key]);
      dot.dataset.state = value === "ok" ? "ok" : value === "disabled" || value === "pending" ? "unknown" : "down";
      item.append(dot, el("span", "", `${label}: ${value}`));
      healthGrid.append(item);
    }
  }

  // ── Models & jobs ──
  const opsKv = $("ops-kv");
  opsKv.replaceChildren();
  if (!models && !metrics) {
    opsKv.append(kvRow("Lỗi", "Không tải được dữ liệu"));
  }
  if (models) {
    const labels = { general: "Trò chuyện & RAG", embedding: "Embedding", ocr: "OCR" };
    for (const [key, label] of Object.entries(labels)) {
      const config = models.models?.[key];
      if (config) opsKv.append(kvRow(label, String(config.name)));
    }
  }
  if (metrics) {
    const queue = metrics.queue_length || {};
    opsKv.append(kvRow("Hàng đợi (ocr/index/memory)",
      `${queue.ocr ?? "–"} / ${queue.index ?? "–"} / ${queue.memory ?? "–"}`));
    opsKv.append(kvRow("Job retry / stale", `${metrics.jobs_retrying ?? 0} / ${metrics.jobs_stale ?? 0}`));
    opsKv.append(kvRow("Lượt ingest hoàn tất", String(metrics.runs_completed ?? 0)));
  }
}

/* ── Duyệt đề xuất ghi nhớ (P1-4) ────────────────────────────────── */
async function postJson(path) {
  try {
    return await requestJson(path, { method: "POST" });
  } catch (error) {
    if (error.status === 401) window.location.href = "/ui/";
    // Hai mã này người dùng tự sửa được, nhưng chỗ sửa nằm ở trang khác.
    if (error.code === "API_KEY_REQUIRED" || error.code === "API_KEY_INVALID") {
      error.message += " Mở trang trò chuyện → Cài đặt → Bảo mật để nhập khóa.";
    }
    throw error;
  }
}

function renderReview(candidates) {
  const tbody = $("review-list");
  const badge = $("review-count");
  if (candidates === null) {
    tableNotice(tbody, "Không tải được danh sách đề xuất.", 4);
    badge.hidden = true;
    return;
  }
  badge.textContent = String(candidates.length);
  badge.hidden = candidates.length === 0;
  if (!candidates.length) {
    tableNotice(tbody, "Không có đề xuất nào chờ duyệt.", 4);
    return;
  }
  tbody.replaceChildren(...candidates.map((candidate) => {
    const row = document.createElement("tr");

    const factCell = document.createElement("td");
    const fact = document.createElement("div");
    fact.textContent = candidate.canonical_fact || "";
    const evidence = document.createElement("div");
    evidence.className = "muted";
    evidence.textContent = candidate.evidence_text ? `«${candidate.evidence_text}»` : "";
    factCell.append(fact, evidence);

    const sourceCell = document.createElement("td");
    sourceCell.textContent = `${candidate.author_display_name || candidate.author_id} · ${candidate.memory_type || "?"}`;

    const confidenceCell = document.createElement("td");
    confidenceCell.textContent = candidate.confidence != null ? `${Math.round(candidate.confidence * 100)}%` : "–";

    const actionCell = document.createElement("td");
    const approve = document.createElement("button");
    approve.className = "btn ghost";
    approve.textContent = "Duyệt";
    const reject = document.createElement("button");
    reject.className = "btn ghost";
    reject.textContent = "Từ chối";
    const act = (button, verb) => async () => {
      approve.disabled = reject.disabled = true;
      button.textContent = "Đang xử lý…";
      try {
        await postJson(`/api/memory-review/candidates/${encodeURIComponent(candidate.candidate_id)}/${verb}`);
        refresh();
      } catch (error) {
        approve.disabled = reject.disabled = false;
        approve.textContent = "Duyệt";
        reject.textContent = "Từ chối";
        tableNotice($("review-list"), error.message, 4);
      }
    };
    approve.onclick = act(approve, "approve");
    reject.onclick = act(reject, "reject");
    actionCell.append(approve, document.createTextNode(" "), reject);

    row.append(factCell, sourceCell, confidenceCell, actionCell);
    return row;
  }));
}

/* ── Memory đang hiệu lực + thu hồi (P2-1) ───────────────────────── */
function renderApplied(items) {
  const tbody = $("applied-list");
  const badge = $("applied-count");
  if (items === null) {
    tableNotice(tbody, "Không tải được danh sách memory.", 4);
    badge.hidden = true;
    return;
  }
  badge.textContent = String(items.length);
  badge.hidden = items.length === 0;
  if (!items.length) {
    tableNotice(tbody, "Agent chưa nhớ điều gì.", 4);
    return;
  }
  tbody.replaceChildren(...items.map((item) => {
    const row = document.createElement("tr");

    const factCell = document.createElement("td");
    const fact = document.createElement("div");
    fact.textContent = item.canonical_fact || "";
    const meta = document.createElement("div");
    meta.className = "muted";
    const applied = item.applied_at ? new Date(item.applied_at).toLocaleString("vi-VN") : "";
    meta.textContent = `${item.memory_type || "?"} · v${item.version}${applied ? ` · ${applied}` : ""}`;
    factCell.append(fact, meta);

    const sourceCell = document.createElement("td");
    sourceCell.textContent = item.author_display_name || item.author_id || "?";

    const reviewerCell = document.createElement("td");
    reviewerCell.textContent = item.applied_by === "agent" ? "🤖 agent" : `👤 ${item.applied_by || "?"}`;
    if (item.confidence != null) reviewerCell.textContent += ` · ${Math.round(item.confidence * 100)}%`;

    const actionCell = document.createElement("td");
    const revert = document.createElement("button");
    revert.textContent = "Thu hồi";
    revert.onclick = async () => {
      revert.disabled = true;
      revert.textContent = "Đang thu hồi…";
      try {
        await postJson(`/api/memory-review/candidates/${encodeURIComponent(item.candidate_id)}/revert`);
        refresh();
      } catch (error) {
        revert.disabled = false;
        revert.textContent = "Thu hồi";
        tableNotice($("applied-list"), error.message, 4);
      }
    };
    actionCell.append(revert);

    row.append(factCell, sourceCell, reviewerCell, actionCell);
    return row;
  }));
}

/* ── Biểu đồ 14 ngày (P3-3) — SVG tự vẽ, không thư viện ─────────── */
const SVG_NS = "http://www.w3.org/2000/svg";

function svgRoot(width, height) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.style.width = "100%";
  svg.style.height = "auto";
  return svg;
}

function svgRect(svg, x, y, width, height, fill) {
  const rect = document.createElementNS(SVG_NS, "rect");
  rect.setAttribute("x", x.toFixed(1));
  rect.setAttribute("y", y.toFixed(1));
  rect.setAttribute("width", Math.max(1, width).toFixed(1));
  rect.setAttribute("height", Math.max(0, height).toFixed(1));
  rect.setAttribute("fill", fill);
  rect.setAttribute("rx", "1.5");
  svg.append(rect);
}

function svgText(svg, x, y, content, size = 9, anchor = "middle") {
  const text = document.createElementNS(SVG_NS, "text");
  text.setAttribute("x", x.toFixed(1));
  text.setAttribute("y", y.toFixed(1));
  text.setAttribute("font-size", String(size));
  text.setAttribute("text-anchor", anchor);
  text.setAttribute("fill", "currentColor");
  text.setAttribute("opacity", "0.65");
  text.textContent = content;
  svg.append(text);
}

function svgLine(svg, points, stroke) {
  const line = document.createElementNS(SVG_NS, "polyline");
  line.setAttribute("points", points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", stroke);
  line.setAttribute("stroke-width", "2");
  line.setAttribute("stroke-linejoin", "round");
  svg.append(line);
}

function renderTimeseries(payload) {
  const questionsBox = $("chart-questions");
  const latencyBox = $("chart-latency");
  if (!questionsBox || !latencyBox) return;
  const days = payload?.days;
  if (!days || !days.length) {
    questionsBox.textContent = latencyBox.textContent = "Không tải được dữ liệu.";
    return;
  }
  const W = 560, H = 180, PAD = 26;
  const band = (W - PAD * 2) / days.length;

  const maxCount = Math.max(1, ...days.map((d) => Math.max(d.questions, d.errors)));
  const bars = svgRoot(W, H);
  days.forEach((day, index) => {
    const x = PAD + index * band;
    const questionHeight = (day.questions / maxCount) * (H - PAD * 2);
    const errorHeight = (day.errors / maxCount) * (H - PAD * 2);
    svgRect(bars, x + band * 0.14, H - PAD - questionHeight, band * 0.44, questionHeight, "#4f8cff");
    if (day.errors) svgRect(bars, x + band * 0.62, H - PAD - errorHeight, band * 0.26, errorHeight, "#e0575b");
    if (day.questions) svgText(bars, x + band * 0.36, H - PAD - questionHeight - 4, String(day.questions));
    if (index % 2 === 0) svgText(bars, x + band / 2, H - 8, day.date.slice(5));
  });
  svgLine(bars, [[PAD, H - PAD], [W - PAD, H - PAD]], "currentColor");
  questionsBox.replaceChildren(bars);

  const latencies = days.flatMap((d) => [d.p50_ms, d.p95_ms]).filter((v) => v != null);
  const maxLatency = Math.max(1000, ...latencies);
  const lines = svgRoot(W, H);
  const pointX = (index) => PAD + (index + 0.5) * band;
  const pointY = (value) => H - PAD - (value / maxLatency) * (H - PAD * 2);
  for (const [selector, color] of [[(d) => d.p95_ms, "#e0a34f"], [(d) => d.p50_ms, "#4f8cff"]]) {
    const points = days.map((d, i) => (selector(d) != null ? [pointX(i), pointY(selector(d))] : null)).filter(Boolean);
    if (points.length > 1) svgLine(lines, points, color);
  }
  svgText(lines, PAD + 2, 14, `tối đa ${(maxLatency / 1000).toFixed(1)}s`, 9, "start");
  days.forEach((day, index) => { if (index % 2 === 0) svgText(lines, pointX(index), H - 8, day.date.slice(5)); });
  svgLine(lines, [[PAD, H - PAD], [W - PAD, H - PAD]], "currentColor");
  latencyBox.replaceChildren(lines);
}

/* ── Điều khiển bot Discord (P3-2) ──────────────────────────────── */
async function refreshBotStatus() {
  const stateEl = $("bot-state");
  if (!stateEl) return;
  try {
    const status = await fetchJson("/api/bot/status");
    stateEl.textContent =
      status.state === "running" ? "🟢 đang chạy"
      : status.state === "stopped" ? "⚪ đang tắt"
      : `⚠️ ${status.detail || "không rõ"}`;
    $("bot-start-btn").disabled = status.state === "running";
    $("bot-stop-btn").disabled = status.state !== "running";
  } catch (error) {
    stateEl.textContent = `⚠️ ${error.message}`;
  }
}

function wireBotControls() {
  const wire = (id, path, busyLabel, idleLabel) => {
    const button = $(id);
    if (!button) return;
    button.onclick = async () => {
      button.disabled = true;
      button.textContent = busyLabel;
      try {
        await postJson(path);
      } catch (error) {
        $("bot-state").textContent = `⚠️ ${error.message}`;
      }
      button.textContent = idleLabel;
      refreshBotStatus();
    };
  };
  wire("bot-start-btn", "/api/bot/start", "Đang bật…", "Bật bot");
  wire("bot-stop-btn", "/api/bot/stop", "Đang tắt…", "Tắt bot");
}
wireBotControls();

/* ── Nhật ký hành động agent (P2-4) ─────────────────────────────── */
const ACTIVITY_LABELS = {
  memory_apply: "🧠 Nhớ",
  memory_revert: "↩️ Thu hồi memory",
  memory_reject: "🚫 Từ chối đề xuất",
  agent_answer: "🤖 Trả lời bằng công cụ",
  job: "⚙️ Việc nền",
};

function renderActivity(items) {
  const tbody = $("activity-list");
  if (items === null) {
    tableNotice(tbody, "Không tải được nhật ký.", 4);
    return;
  }
  if (!items.length) {
    tableNotice(tbody, "Chưa có hành động tự hành nào.", 4);
    return;
  }
  tbody.replaceChildren(...items.slice(0, 30).map((item) => {
    const row = document.createElement("tr");
    const timeCell = document.createElement("td");
    timeCell.textContent = new Date(item.at).toLocaleString("vi-VN");
    const actionCell = document.createElement("td");
    const label = document.createElement("div");
    label.textContent = `${ACTIVITY_LABELS[item.kind] || item.kind}${item.actor ? ` · ${item.actor}` : ""}`;
    const detail = document.createElement("div");
    detail.className = "muted";
    detail.textContent = item.title || "";
    actionCell.append(label, detail);
    const statusCell = document.createElement("td");
    statusCell.textContent = item.status || "";
    const undoCell = document.createElement("td");
    if (item.revertable && item.candidate_id) {
      const revert = document.createElement("button");
      revert.textContent = "Thu hồi";
      revert.onclick = async () => {
        revert.disabled = true;
        revert.textContent = "Đang thu hồi…";
        try {
          await postJson(`/api/memory-review/candidates/${encodeURIComponent(item.candidate_id)}/revert`);
          refresh();
        } catch (error) {
          revert.disabled = false;
          revert.textContent = "Thu hồi";
          tableNotice($("activity-list"), error.message, 4);
        }
      };
      undoCell.append(revert);
    }
    row.append(timeCell, actionCell, statusCell, undoCell);
    return row;
  }));
}

async function refresh() {
  const [stats, health, metrics, models, conversations, reviewCandidates, appliedMemories, agentActivity, timeseries] = await Promise.allSettled([
    fetchJson("/api/dashboard/stats"),
    fetchJson("/health"),
    fetchJson("/metrics"),
    fetchJson("/models"),
    fetchJson("/conversations"),
    fetchJson("/api/memory-review/candidates"),
    fetchJson("/api/memory-review/applied"),
    fetchJson("/agent/activity"),
    fetchJson("/api/dashboard/timeseries"),
  ]).then((results) => results.map((result) => (result.status === "fulfilled" ? result.value : null)));
  renderReview(reviewCandidates);
  renderApplied(appliedMemories);
  renderActivity(agentActivity);
  renderTimeseries(timeseries);
  refreshBotStatus();

  // Banner hiện khi BẤT KỲ nguồn cốt lõi nào lỗi; render luôn chạy để
  // skeleton được thay bằng trạng thái lỗi thay vì nhấp nháy mãi.
  const anyCoreDown = !stats || !health || !metrics;
  $("dash-error").hidden = !anyCoreDown;
  render(stats, health, metrics, models, conversations);
  $("dash-updated").textContent =
    !stats && !health && !metrics
      ? "Mất kết nối"
      : anyCoreDown
        ? "Một phần dữ liệu lỗi"
        : `Cập nhật ${new Date().toLocaleTimeString("vi-VN")}`;
}

$("dash-refresh").onclick = refresh;
$("dash-retry").onclick = refresh;
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 20000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
