/* Bảng điều khiển quản lý agent — chỉ đọc, tự làm mới mỗi 20 giây. */
"use strict";

const $ = (id) => document.getElementById(id);

/* Theme đồng bộ với app chat (cùng key lac.prefs) */
const prefs = (() => {
  try { return { theme: "system", ...JSON.parse(localStorage.getItem("lac.prefs") || "{}") }; }
  catch { return { theme: "system" }; }
})();
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  const resolved = prefs.theme === "system" ? (systemDark.matches ? "dark" : "light") : prefs.theme;
  document.documentElement.dataset.theme = resolved;
}
systemDark.addEventListener("change", applyTheme);
applyTheme();

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

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

async function fetchJson(path) {
  // Cùng khóa với trang chat (lac.apikey): khi LOCAL_AI_PROTECT_READS bật,
  // dashboard cũng phải trình khóa, nếu không mọi panel sẽ 401.
  const key = localStorage.getItem("lac.apikey") || "";
  const response = await fetch(path, key ? { headers: { "X-API-Key": key } } : undefined);
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
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
    const componentLabels = {
      postgres: "PostgreSQL", redis: "Redis", qdrant: "Qdrant", ollama: "Ollama",
      worker_ocr: "Worker OCR", worker_index: "Worker Index", worker_memory: "Worker Memory",
      outbox_dispatcher: "Outbox", cleanup_worker: "Cleanup",
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

async function refresh() {
  const [stats, health, metrics, models, conversations] = await Promise.allSettled([
    fetchJson("/api/dashboard/stats"),
    fetchJson("/health"),
    fetchJson("/metrics"),
    fetchJson("/models"),
    fetchJson("/conversations"),
  ]).then((results) => results.map((result) => (result.status === "fulfilled" ? result.value : null)));

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
