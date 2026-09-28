/* ══════════════════════════════════════════════════════════════════
   /ui/views/bot.js — màn hình Bot Discord (#/bot, chỉ quản trị viên —
   router tự chặn thành viên).

   Một IIFE, không tên top-level. Gồm:
     - banner gradient: trạng thái container bot (GET /api/bot/status — mỗi lần
       là một `docker compose ps` trên máy chủ, tự hết giờ ở 20 giây) và nút
       Bật / Tắt / Khởi động lại;
     - 4 thẻ số từ /api/dashboard/stats: phiên active, lượt hoàn tất, tin đã gửi;
       "Độ trễ p50" không có nguồn riêng cho Discord → nói thật là chưa đo;
     - "Phiên gần đây": 8 phiên mới nhất máy chủ trả (chỉ có ID, không có tên kênh);
     - "Lượt theo trạng thái" (turn_counts) và "Lệnh & cấu hình": 3 công tắc CHỈ ĐỂ XEM
       đọc từ F7 GET /api/bot/config; máy chủ chưa có thì khóa, riêng «Nạp ghi nhớ»
       vẫn suy ra được từ /health (memory_ingestion khác "disabled").
   Hợp đồng API: research/api-admin.md §3, §1.1, §6.1; spec F7 (restart, uptime,
   số server / thành viên, cấu hình). Làm mới 20 giây/lần như bảng điều khiển cũ
   (bỏ qua khi tab ẩn, làm ngay khi tab hiện lại) và ngay sau mỗi lệnh.
   Bật / tắt chặn request tới 180 / 60 giây: lệnh đang chạy nằm trong S (sống qua
   các lần mount) nên rời trang rồi quay lại vẫn thấy nút đang bận, không gửi trùng
   (parity 58); kết quả về khi đã rời trang thì báo bằng toast.
   Gọi mạng: chỉ Shell.api. V là DOM + dữ liệu của lần mount đang sống, null khi đã
   rời view — mọi việc bất đồng bộ kiểm tra V / số thứ tự trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  /* ── hằng số ─────────────────────────────────────────────────── */
  const REFRESH_MS = 20000;        // nhịp làm mới của bảng điều khiển cũ (parity 59)
  const STATUS_WAIT_MS = 30000;    // máy chủ tự bỏ `docker compose ps` sau 20 giây; chờ thêm một chút
  const GRACE_MS = 20000;          // chờ thêm sau hạn của máy chủ rồi mới coi là mất liên lạc

  /* Hạn của máy chủ (api-admin §3): start 180 giây (lần đầu còn dựng image), stop 60 giây;
     restart (F7) = stop + start. */
  const ACTIONS = {
    start: {
      path: "/api/bot/start", wait: 180000, label: "Bật bot", busy: "Đang bật…", progress: "đang bật bot…",
      hint: "lần đầu có thể mất vài phút để dựng image", done: "Đã bật bot.", fail: "Không bật được bot",
    },
    stop: {
      path: "/api/bot/stop", wait: 60000, label: "Tắt bot", busy: "Đang tắt…", progress: "đang tắt bot…",
      done: "Đã tắt bot.", fail: "Không tắt được bot",
    },
    restart: {
      path: "/api/bot/restart", wait: 240000, label: "Khởi động lại", busy: "Đang khởi động lại…",
      progress: "đang khởi động lại bot…", done: "Đã khởi động lại bot.", fail: "Không khởi động lại được bot",
    },
  };
  const RESTART_MISSING = "Máy chủ chưa hỗ trợ khởi động lại bot.";

  /* Lệnh thật của bot (discord_bot/main.py: /ping, /ask, /docs + mention). */
  const COMMANDS = [
    ["/ping", "kiểm tra bot phản hồi"],
    ["/ask", "hỏi backend Local AI Core"],
    ["/docs", "hỏi đáp theo tài liệu, có nguồn"],
    ["@Ún", "mention để chat tự nhiên"],
  ];

  /* turn_counts chỉ có khóa của trạng thái đang tồn tại (queued|running|completed|failed|cancelled).
     "đang chạy" gộp running + queued (tooltip tách riêng); khóa lạ hiện thêm một thanh, nhãn thô. */
  const TURN_BARS = [
    { label: "hoàn tất", keys: ["completed"], color: "var(--accent)" },
    { label: "thất bại", keys: ["failed"], color: "var(--danger)" },
    { label: "đã hủy", keys: ["cancelled"], color: "var(--border-2)" },
    { label: "đang chạy", keys: ["running", "queued"], color: "var(--warn)" },
  ];
  const KNOWN_TURNS = new Set(TURN_BARS.flatMap((bar) => bar.keys));

  /* Trạng thái phiên thật chỉ có active | orphaned (api-admin §1.1); còn lại hiện nguyên chữ, màu mờ. */
  const SESSION_STATUS = {
    active: { label: "active", tone: "ok", hint: "Phiên đang dùng cho kênh này" },
    orphaned: {
      label: "mồ côi", tone: "warn",
      hint: "Hội thoại backend của phiên này không còn — lần nhắc @Ún kế tiếp ở kênh này sẽ mở phiên mới",
    },
  };

  /* ── trạng thái sống qua các lần mount ───────────────────────── */
  const S = {
    action: null,         // {kind, started}: lệnh bật / tắt / khởi động lại đang chờ máy chủ
    restart: null,        // F7 POST /api/bot/restart: null = chưa biết, false = máy chủ chưa có (biết sau lần bấm đầu)
  };
  let V = null;

  /* ── tiện ích ────────────────────────────────────────────────── */
  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const live = (v) => Boolean(v) && V === v && !v.ctx.signal.aborted;

  function num(value) {
    const n = Number(value);
    return value === null || value === undefined || value === "" || typeof value === "boolean" || !Number.isFinite(n) ? null : n;
  }

  /* ID Discord (snowflake) → "…6 số cuối"; ID không phải snowflake (dữ liệu thử) → nguyên văn. */
  function shortId(id) {
    const text = String(id ?? "").trim();
    if (!text) return "?";
    return /^\d{7,}$/.test(text) ? `…${text.slice(-6)}` : text;
  }

  /* signal của view + hạn chờ riêng. timedOut() cho biết lỗi là do hết giờ (Shell.api khi đó ném
     lỗi "Không kết nối…" chung chung của sendJson). */
  function timed(signal, ms) {
    const timer = typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(ms) : null;
    let merged = signal || timer || undefined;
    if (signal && timer && typeof AbortSignal.any === "function") merged = AbortSignal.any([signal, timer]);
    return { signal: merged, timedOut: () => Boolean(timer && timer.aborted) };
  }

  /* Lời lỗi để hiện: sendJson đã dịch mã quen (ERROR_HINTS) và lỗi mạng; 500 thì nói bằng tiếng Việt. */
  function errText(error, fallback = "Đã xảy ra lỗi không xác định.") {
    if (error && error.code === "INTERNAL_ERROR") return "Máy chủ gặp lỗi không mong muốn (500). Thử lại sau.";
    return (error && error.message) || fallback;
  }

  function normalizeStatus(data) {
    if (!data || typeof data !== "object") return null;
    const state = ["running", "stopped", "unknown"].includes(data.state) ? data.state : "unknown";
    const detail = data.detail == null || data.detail === "" ? null : String(data.detail);
    return { ...data, state, detail };
  }

  /* Mốc thời gian → ms. Hợp đồng F7 không chốt khuôn started_at, mà backend này có chỗ trả epoch
     (created_at của OCR, api-admin §2.2), nên đọc cả ISO lẫn epoch giây/mili — đúng như fmtDate. */
  function timeMs(value) {
    if (typeof value === "number") return Number.isFinite(value) ? (Math.abs(value) < 1e12 ? value * 1000 : value) : NaN;
    return value ? Date.parse(value) : NaN;
  }

  /* Uptime (ms): ưu tiên uptime_seconds của máy chủ (+ thời gian từ lúc nhận), không có thì từ started_at. */
  function uptimeMs(status, receivedAt) {
    const up = num(status.uptime_seconds);
    if (up !== null && up >= 0) return up * 1000 + Math.max(0, Date.now() - receivedAt);
    const started = timeMs(status.started_at);
    return Number.isFinite(started) ? Math.max(0, Date.now() - started) : null;
  }

  /* ── dòng trạng thái + nút của banner ────────────────────────── */
  function statusLine(v) {
    if (S.action) {
      const cfg = ACTIONS[S.action.kind];
      const sec = Math.floor((Date.now() - S.action.started) / 1000);
      // Đồng hồ giây để ngoài vùng aria-live: nếu không, trình đọc màn hình đọc lại mỗi giây.
      return { dot: "busy", text: [cfg.progress, cfg.hint].filter(Boolean).join(" · "), clock: sec >= 1 ? ` · ${sec} giây` : "" };
    }
    const st = v.status;
    // Chưa từng đọc được trạng thái lần nào: đây mới là "lỗi" thật, banner chỉ còn nút thử lại.
    if (!st) {
      if (v.statusError) return { dot: "error", text: `không đọc được trạng thái · ${errText(v.statusError)}` };
      return { dot: "loading", text: "đang kiểm tra trạng thái…" };
    }
    // Còn trạng thái cũ mà lần đọc mới hỏng: giữ nguyên trạng thái + nút, chỉ ghi chú là số đã cũ.
    // /api/bot/status là một `docker compose ps` đồng bộ (api-admin §3): máy chủ chậm không được
    // làm biến mất nút Tắt bot đúng lúc người trực cần nó nhất (parity 56 của bảng điều khiển cũ).
    const line = stateLine(st, v.statusAt);
    if (v.statusError) line.stale = errText(v.statusError);
    return line;
  }

  function stateLine(st, statusAt) {
    if (st.state === "running") {
      const parts = ["đang chạy"];
      const up = uptimeMs(st, statusAt);
      // Dưới một phút: fmtDuration ra "0ms"/"8.0s" — vô nghĩa cho uptime, nói "vừa bật".
      if (up !== null) parts.push(up < 60000 ? "vừa bật" : fmtDuration(up));
      const guilds = num(st.guild_count);
      const members = num(st.member_count);
      if (guilds !== null) parts.push(`${fmtNumber(guilds)} server`);
      if (members !== null) parts.push(`${fmtNumber(members)} thành viên`);
      const started = st.started_at ? fmtDate(st.started_at, { time: true }) : null;
      return { dot: "running", text: parts.join(" · "), title: started && started !== "—" ? `Chạy từ ${started}` : null };
    }
    if (st.state === "stopped") {
      // detail thường là null (compose ps không liệt kê container đã thoát); có thì là State thô ("exited"…).
      const extra = st.detail && st.detail !== "stopped" ? ` · ${st.detail}` : "";
      return { dot: "stopped", text: `đã dừng${extra}` };
    }
    return { dot: "unknown", text: `không rõ trạng thái${st.detail ? ` · ${st.detail}` : ""}` };
  }

  function renderStatusLine(v) {
    const line = statusLine(v);
    if (v.dot.dataset.state !== line.dot) v.dot.dataset.state = line.dot;
    // Chỉ ghi khi đổi chữ: vùng này là aria-live, ghi lại cùng chữ mỗi 20 giây là đọc lặp.
    if (v.statusText.textContent !== line.text) v.statusText.textContent = line.text;
    const clock = line.clock || "";
    if (v.statusClock.textContent !== clock) v.statusClock.textContent = clock;
    const stale = line.stale ? " · không đọc được trạng thái mới nhất" : "";
    if (v.statusStale.textContent !== stale) v.statusStale.textContent = stale;
    const title = line.stale
      ? `${line.text} — không đọc được trạng thái mới nhất: ${line.stale}`
      : line.title || `${line.text}${clock}`;
    if (v.statusBox.title !== title) v.statusBox.title = title;
  }

  /* Nút trên nền gradient (P:482): viền trắng mờ hoặc nền trắng chữ accent. */
  function brandButton({ solid = false, iconName, fill = false, label, busyLabel, busy = false, disabled = false, locked = false, title, onClick }) {
    const lead = busy
      ? icon("refresh", { size: 13, cls: "bot-spin" })
      : locked ? icon("lock", { size: 13 })
        : iconName ? icon(iconName, { size: 13, cls: fill ? "bot-ico-fill" : null }) : null;
    return h("button", {
      type: "button", class: ["btn", "btn-38", solid ? "btn-on-brand-solid" : "btn-on-brand", locked && "is-locked", busy && "is-busy"],
      // Nút khóa vẫn bấm được (để hiện lời giải thích) nhưng phải tự giới thiệu là đang khóa.
      disabled: busy || disabled, "aria-busy": busy, "aria-disabled": locked || undefined, title, onClick,
    }, lead, busy ? busyLabel : label);
  }

  /* Cả hàng nút bị dựng lại mỗi lần đổi trạng thái. Nếu người dùng đang đứng bằng bàn phím ở đó thì
     focus sẽ rơi xuống <body>; nhớ lại vị trí và trả về nút thay thế (nút đang bận không nhận focus
     nên giữ ý định tới lần vẽ kế tiếp). Không giành focus nếu người dùng đã chuyển đi chỗ khác. */
  function restoreActionFocus(v, nodes) {
    if (v.refocus === null) return;
    const parked = document.activeElement;
    if (parked && parked !== document.body && !v.actions.contains(parked)) { v.refocus = null; return; }
    const usable = nodes.filter((node) => node && node.tagName === "BUTTON" && !node.disabled);
    if (!usable.length) return;
    const pick = usable[Math.min(v.refocus, usable.length - 1)];
    v.refocus = null;
    try { pick.focus({ preventScroll: true }); } catch { /* phần tử không nhận focus */ }
  }

  function renderActions(v) {
    const kind = S.action ? S.action.kind : null;
    // Lỗi đọc trạng thái chỉ là ghi chú khi đã từng đọc được: trạng thái (và bộ nút) vẫn là cái cũ.
    const state = v.status ? v.status.state : v.statusError ? "error" : "loading";
    const key = `${kind}|${state}|${S.restart}|${v.checking}`;
    if (key === v.actionsKey) return;   // giữ nguyên nút (focus, dialog đang mở từ nút) khi không có gì đổi
    v.actionsKey = key;
    const restartBtn = (busy, disabled) => {
      const locked = S.restart === false;
      return brandButton({
        label: ACTIONS.restart.label, busyLabel: ACTIONS.restart.busy, busy, disabled, locked,
        title: locked ? `${RESTART_MISSING} (POST /api/bot/restart)` : "Tắt rồi bật lại container discord-bot",
        onClick: () => runAction("restart"),
      });
    };
    const stopBtn = (busy, disabled) => brandButton({
      solid: true, iconName: "stop", label: ACTIONS.stop.label, busyLabel: ACTIONS.stop.busy, busy, disabled,
      onClick: () => confirmStop(v),
    });
    const startBtn = (busy) => brandButton({
      solid: true, iconName: "play", fill: true, label: ACTIONS.start.label, busyLabel: ACTIONS.start.busy, busy,
      onClick: () => runAction("start"),
    });
    const checkBtn = (label) => brandButton({
      iconName: "refresh", label, busyLabel: "Đang kiểm tra…", busy: v.checking,
      onClick: () => recheck(v),
    });
    let nodes = [];
    if (kind === "start") nodes = [startBtn(true)];
    else if (kind === "stop" || kind === "restart") nodes = [restartBtn(kind === "restart", true), stopBtn(kind === "stop", true)];
    else if (state === "running") nodes = [restartBtn(false, false), stopBtn(false, false)];
    else if (state === "stopped") nodes = [startBtn(false)];
    else if (state === "unknown") nodes = [checkBtn("Kiểm tra lại"), startBtn(false)];
    else if (state === "error") nodes = [checkBtn("Thử lại")];
    // Lần đọc đầu (docker compose ps tới 20 giây): chỗ nút không được sập xuống rỗng — hiện khung chờ
    // đúng kích thước như mọi khối khác trên màn hình.
    else nodes = [skeleton({ w: 136, h: 38, r: 10 }), skeleton({ w: 104, h: 38, r: 10 })];
    if (v.actions.contains(document.activeElement)) {
      v.refocus = Math.max(0, [...v.actions.children].indexOf(document.activeElement));
    }
    v.actions.replaceChildren(...nodes);
    restoreActionFocus(v, nodes);
  }

  function renderBanner(v) {
    renderStatusLine(v);
    renderActions(v);
  }

  function renderNotice(v) {
    const notice = v.notice;
    v.noticeEl.hidden = !notice;
    if (!notice) { v.noticeEl.replaceChildren(); return; }
    v.noticeEl.className = `bot-notice tone-${notice.tone === "warn" ? "warn" : "danger"}`;
    v.noticeEl.replaceChildren(
      icon("alert", { size: 16 }),
      h("div", { class: "bot-notice-body" },
        h("div", { class: "bot-notice-title" }, notice.title),
        notice.detail ? h("div", { class: "bot-notice-detail" }, notice.detail) : null),
      h("button", {
        type: "button", class: "icon-btn icon-btn-28 bot-notice-close", title: "Đóng", "aria-label": "Đóng thông báo",
        // Nút tự xóa chính mình: đưa focus về nút lệnh gần nhất, đừng thả xuống <body>.
        onClick: () => {
          const byKeyboard = v.noticeEl.contains(document.activeElement);
          v.notice = null;
          renderNotice(v);
          const next = byKeyboard ? v.actions.querySelector("button:not(:disabled)") : null;
          if (next) next.focus({ preventScroll: true });
        },
      }, icon("x", { size: 14 })));
  }

  /* ── thẻ số ──────────────────────────────────────────────────── */
  function renderStats(v) {
    const d = v.stats;
    const { active, done, sent, latency } = v.statEls;
    if (!d) {
      for (const card of [active, done, sent]) {
        if (v.statsError) {
          countUp(card.value, null);
          card.sub.textContent = "không tải được";
        } else {
          card.value.replaceChildren(skeleton({ w: 46, h: 22, r: 6 }));
          card.sub.replaceChildren(skeleton({ w: 84, h: 10, r: 5 }));
        }
      }
    } else {
      const counts = d.turn_counts && typeof d.turn_counts === "object" ? d.turn_counts : {};
      countUp(active.value, num(d.active_session_count) ?? 0);
      active.sub.textContent = `trên ${fmtNumber(num(d.session_count) ?? 0)} phiên`;
      countUp(done.value, num(counts.completed) ?? 0);
      done.sub.textContent = `${fmtNumber(num(counts.failed) ?? 0)} thất bại · ${fmtNumber(num(counts.cancelled) ?? 0)} hủy`;
      countUp(sent.value, num(d.delivery_count) ?? 0);
      sent.sub.textContent = "lên Discord";
    }
    // Không có nguồn: độ trễ ở /api/dashboard/timeseries gộp web + Discord (api-admin §1.2).
    latency.value.textContent = "—";
    latency.sub.textContent = "chưa đo riêng cho Discord";
  }

  /* ── phiên gần đây ───────────────────────────────────────────── */
  function sessionRow(s) {
    const thread = s.thread_id != null && String(s.thread_id).trim() !== "";
    const place = thread ? `thread ${shortId(s.thread_id)}` : `#${shortId(s.channel_id)}`;
    const meta = SESSION_STATUS[s.status] || { label: String(s.status || "?"), tone: "muted" };
    const turns = num(s.turn_count);
    const ids = [thread ? `thread ${s.thread_id}` : null, `kênh ${s.channel_id ?? "?"}`, `guild ${s.guild_id ?? "?"}`, `phiên ${s.session_id ?? "?"}`]
      .filter(Boolean).join("\n");
    const statusPill = pill(meta.label, meta.tone, { dot: false, size: "sm" });
    if (meta.hint) statusPill.title = meta.hint;
    const when = s.last_active_at ? fmtDate(s.last_active_at, { time: true }) : null;
    return h("div", { class: "bot-session", role: "listitem" },
      h("span", { class: "bot-session-tile", "aria-hidden": "true" }, "#"),
      h("div", { class: "bot-session-body" },
        h("div", { class: "bot-session-place", title: ids }, place),
        h("div", { class: "bot-session-sub" }, `guild ${shortId(s.guild_id)} · ${turns === null ? "?" : fmtNumber(turns)} lượt`)),
      statusPill,
      h("span", { class: "bot-session-time", title: when && when !== "—" ? when : null }, fmtRelative(s.last_active_at)));
  }

  function skeletonSession() {
    return h("div", { class: "bot-session is-skeleton", "aria-hidden": "true" },
      skeleton({ w: 32, h: 32, r: 9 }),
      h("div", { class: "bot-session-body bot-skel-lines" }, skeleton({ w: "38%", h: 12 }), skeleton({ w: "26%", h: 10 })),
      skeleton({ w: 52, h: 22, r: 999 }),
      skeleton({ w: 70, h: 11 }));
  }

  function renderSessions(v) {
    const d = v.stats;
    const list = v.sessionList;
    if (!d) {
      v.sessionMeta.textContent = "";
      v.sessionMeta.classList.remove("is-error");
      // Không phải danh sách nữa (khung chờ / lỗi / rỗng) nhưng vẫn phải là một vùng có tên:
      // aria-label trên <div> trơn thì trình đọc màn hình bỏ qua.
      list.setAttribute("role", "group");
      if (v.statsError) list.replaceChildren(errorState({ message: errText(v.statsError) }, () => loadStats(v, { force: true })));
      else list.replaceChildren(...[0, 1, 2, 3].map(skeletonSession));
      return;
    }
    // Lần làm mới hỏng mà vẫn còn số cũ: giữ danh sách, báo nhỏ ở góc thẻ.
    if (v.statsError) {
      v.sessionMeta.textContent = "không làm mới được";
      v.sessionMeta.title = errText(v.statsError);
      v.sessionMeta.classList.add("is-error");
    } else {
      v.sessionMeta.textContent = `${fmtNumber(num(d.active_session_count) ?? 0)} active / ${fmtNumber(num(d.session_count) ?? 0)}`;
      v.sessionMeta.removeAttribute("title");
      v.sessionMeta.classList.remove("is-error");
    }
    const rows = Array.isArray(d.recent_sessions) ? d.recent_sessions.filter((row) => row && typeof row === "object") : [];
    if (!rows.length) {
      list.setAttribute("role", "group");
      list.replaceChildren(emptyState({
        icon: "bot", title: "Bot chưa có phiên nào.",
        text: "Chạy run-discord-bot.bat (hoặc bấm Bật bot) rồi nhắc @Ún trong một kênh Discord để mở phiên đầu tiên.",
      }));
      return;
    }
    list.setAttribute("role", "list");
    list.replaceChildren(...rows.map(sessionRow));
  }

  /* ── lượt theo trạng thái ────────────────────────────────────── */
  function renderTurns(v) {
    const box = v.bars;
    const d = v.stats;
    v.barsNote.hidden = true;
    if (!d) {
      v.barsKey = null;
      if (v.statsError) {
        box.replaceChildren(h("div", { class: "bot-muted" }, "Không tải được số lượt."));
      } else {
        box.replaceChildren(...TURN_BARS.map((bar) => h("div", { class: "bot-bar-row", "aria-hidden": "true" },
          h("span", { class: "bot-bar-label" }, bar.label), h("div", { class: "bot-bar-track" }),
          h("span", { class: "bot-bar-count" }, "—"))));
      }
      return;
    }
    const counts = d.turn_counts && typeof d.turn_counts === "object" ? d.turn_counts : {};
    const val = (key) => Math.max(0, num(counts[key]) ?? 0);
    const rows = TURN_BARS.map((bar) => ({
      label: bar.label, color: bar.color, n: bar.keys.reduce((sum, key) => sum + val(key), 0),
      title: bar.keys.length > 1 ? `đang chạy ${fmtNumber(val("running"))} · đang chờ ${fmtNumber(val("queued"))}` : null,
    }));
    for (const key of Object.keys(counts)) {
      // Trạng thái lạ (DB nới CHECK): hiện nguyên tên khóa; cột nhãn rộng 72px nên tên dài bị cắt,
      // giữ nguyên văn trong tooltip.
      if (!KNOWN_TURNS.has(key)) rows.push({ label: key, color: "var(--text-3)", n: val(key), title: key });
    }
    const total = rows.reduce((sum, row) => sum + row.n, 0);
    const width = (n) => (total > 0 ? `${((n / total) * 100).toFixed(2)}%` : "0%");
    const key = rows.map((row) => row.label).join("|");
    // Cùng bộ thanh: chỉ đổi độ rộng + số (chuyển động mượt), không dựng lại để khỏi chạy lại hiệu ứng.
    if (key === v.barsKey && box.children.length === rows.length) {
      rows.forEach((row, i) => {
        const el = box.children[i];
        const track = el.querySelector(".bot-bar-track");
        const fill = el.querySelector(".bot-bar-fill");
        fill.style.width = width(row.n);
        fill.classList.toggle("is-nonzero", row.n > 0);
        el.querySelector(".bot-bar-count").textContent = fmtNumber(row.n);
        track.setAttribute("aria-valuemax", String(total));
        track.setAttribute("aria-valuenow", String(row.n));
        if (row.title) el.title = row.title;
      });
    } else {
      v.barsKey = key;
      box.replaceChildren(...rows.map((row) => h("div", { class: "bot-bar-row", title: row.title },
        h("span", { class: "bot-bar-label" }, row.label),
        h("div", {
          class: "bot-bar-track", role: "meter", "aria-label": `Lượt ${row.label}`,
          "aria-valuemin": "0", "aria-valuemax": String(total), "aria-valuenow": String(row.n),
        }, h("div", { class: ["bot-bar-fill", row.n > 0 && "is-nonzero"], style: { width: width(row.n), background: row.color } })),
        h("span", { class: "bot-bar-count" }, fmtNumber(row.n)))));
    }
    if (total === 0) {
      v.barsNote.textContent = "Chưa có lượt nào.";
      v.barsNote.hidden = false;
    }
  }

  /* ── lệnh & cấu hình ─────────────────────────────────────────── */
  /* «Nạp ghi nhớ đề xuất»: cấu hình F7 nếu có, không thì /health (tắt hẳn → "disabled";
     "unavailable" nghĩa là bật nhưng worker hỏng — vẫn là bật). */
  function memoryFlag(v) {
    if (v.configState === "ok" && typeof v.config.memory_ingestion === "boolean") {
      return { on: v.config.memory_ingestion, from: "config", warn: null };
    }
    const health = v.health;
    const value = health && health.status !== "down" ? health.memory_ingestion : undefined;
    if (typeof value === "string" && value) {
      // "ok" = đang nạp, "disabled" = tắt hẳn. Giá trị khác ("unavailable"…) vẫn là bật theo cấu hình,
      // nhưng thực tế không nạp được gì — nói ra thay vì để công tắc xanh nói dối.
      return { on: value !== "disabled", from: "health", warn: value === "ok" || value === "disabled" ? null : value };
    }
    return { on: null, from: null, warn: null };
  }

  /* Công tắc chỉ để xem (README: "đọc từ cấu hình, chỉ hiển thị"): <span>, không phải nút.
     "không rõ" phải nhìn ra được là không rõ: núm nằm giữa, viền nét đứt — công tắc mờ mà núm ở
     bên trái trông hệt như "tắt", tức là màn hình khẳng định một điều nó không biết. */
  function flagSwitch(on, label, warn) {
    const stateText = on === null ? "không rõ" : on ? "bật" : "tắt";
    return h("span", {
      class: ["switch", "switch-sm", "bot-switch", on === true && "is-on", on === null && "is-unknown"],
      role: "img", "aria-label": `${label}: ${stateText}${warn ? ` (/health báo "${warn}")` : ""} (chỉ xem)`,
    });
  }

  function renderConfig(v) {
    if (v.configState === null) {
      v.flags.replaceChildren(...["Phiên bền (PostgreSQL)", "Nạp ghi nhớ đề xuất", "Ngữ cảnh thành viên"].map((label) =>
        h("div", { class: "bot-flag" }, h("span", { class: "bot-flag-label" }, label), skeleton({ w: 34, h: 20, r: 10 }))));
      return;
    }
    const ok = v.configState === "ok";
    const c = ok ? v.config : {};
    const limit = num(c.member_context_limit);
    const mem = memoryFlag(v);
    const flags = [
      {
        label: "Phiên bền (PostgreSQL)", on: ok && typeof c.persistent_sessions === "boolean" ? c.persistent_sessions : null,
        hint: "Bot giữ phiên hội thoại trong PostgreSQL qua các lần khởi động (DISCORD_PERSISTENT_SESSIONS_ENABLED)",
      },
      {
        label: "Nạp ghi nhớ đề xuất", on: mem.on, warn: mem.warn,
        hint: mem.warn
          ? `Tin nhắn Discord được trích thành đề xuất ghi nhớ chờ duyệt ở màn Ghi nhớ — nhưng /health báo memory_ingestion "${mem.warn}", tức hiện không nạp được`
          : "Tin nhắn Discord được trích thành đề xuất ghi nhớ chờ duyệt ở màn Ghi nhớ",
      },
      {
        label: limit !== null && limit > 0 ? `Ngữ cảnh thành viên (≤${fmtNumber(limit)})` : "Ngữ cảnh thành viên",
        on: ok && limit !== null ? limit > 0 : null,
        hint: "Số thành viên gần đây bot đưa vào ngữ cảnh khi trả lời (DISCORD_MEMBER_CONTEXT_LIMIT)",
      },
    ];
    const nodes = flags.map((flag) => h("div", { class: "bot-flag", title: flag.hint },
      h("span", { class: "bot-flag-label" }, flag.label),
      flag.warn ? h("span", { class: "bot-flag-note" }, `/health: ${flag.warn}`) : null,
      flagSwitch(flag.on, flag.label, flag.warn)));
    if (!ok) {
      const fromHealth = mem.from === "health" ? " «Nạp ghi nhớ đề xuất» lấy từ /health." : "";
      // "chưa hỗ trợ" (404/405/501) khác hẳn "đọc hỏng": câu chữ phải nói đúng chuyện nào đang xảy ra.
      nodes.push(v.configState === "missing"
        ? h("div", { class: "bot-flags-note" }, "Máy chủ chưa hỗ trợ đọc cấu hình bot (", h("span", { class: "mono" }, "GET /api/bot/config"), ").", fromHealth)
        : h("div", { class: "bot-flags-note" }, `Không đọc được cấu hình bot: ${errText(v.configError)}`, fromHealth));
    }
    v.flags.replaceChildren(...nodes);
  }

  function renderAll(v) {
    renderBanner(v);
    renderNotice(v);
    renderStats(v);
    renderSessions(v);
    renderTurns(v);
    renderConfig(v);
  }

  /* ── nạp dữ liệu ─────────────────────────────────────────────── */
  async function loadStatus(v, { force = false, check = false } = {}) {
    if (!live(v)) return;
    if (!force && (S.action || v.statusInflight)) return;   // lệnh đang chạy: trạng thái giữa chừng chỉ gây nhiễu
    const seq = ++v.statusSeq;
    if (check) {                       // người dùng tự bấm: nút hiện "Đang kiểm tra…" cho tới khi CHÍNH lần này xong
      v.checking = true;
      v.checkSeq = seq;
      renderActions(v);
    }
    const wait = timed(v.ctx.signal, STATUS_WAIT_MS);
    const request = Shell.api("/api/bot/status", { signal: wait.signal });
    v.statusInflight = request;
    try {
      const data = await request;
      if (!live(v) || seq !== v.statusSeq) return;
      const status = normalizeStatus(data);
      if (!status) throw new Error("Máy chủ trả trạng thái bot không đọc được.");
      v.status = status;
      v.statusAt = Date.now();
      v.statusError = null;
    } catch (error) {
      if (!live(v) || seq !== v.statusSeq) return;
      if (isAbort(error) && v.ctx.signal.aborted) return;
      v.statusError = wait.timedOut()
        ? new Error(`máy chủ không trả lời sau ${Math.round(STATUS_WAIT_MS / 1000)} giây`)
        : error;
    } finally {
      // Cờ "đang kiểm tra" do chính lần hỏi đã bật nó xóa đi — kể cả khi hàm thoát sớm ở các nhánh
      // trên (reportSuccess tăng statusSeq giữa chừng thì nút "Đang kiểm tra…" sẽ kẹt mãi).
      if (v.statusInflight === request) v.statusInflight = null;
      if (v.checkSeq === seq) { v.checking = false; v.checkSeq = 0; }
      if (live(v)) renderBanner(v);
    }
  }

  async function loadStats(v, { force = false } = {}) {
    if (!live(v)) return;
    if (!force && v.statsInflight) return;
    const seq = ++v.statsSeq;
    const request = Shell.api("/api/dashboard/stats", { signal: v.ctx.signal });
    v.statsInflight = request;
    try {
      const data = await request;
      if (!live(v) || seq !== v.statsSeq) return;
      const discord = data && typeof data === "object" ? data.discord : null;
      if (!discord || typeof discord !== "object") throw new Error("Máy chủ không trả số liệu Discord.");
      v.stats = discord;
      v.statsError = null;
    } catch (error) {
      if (!live(v) || seq !== v.statsSeq) return;
      if (isAbort(error) && v.ctx.signal.aborted) return;
      v.statsError = error;
    } finally {
      if (v.statsInflight === request) v.statsInflight = null;
    }
    renderStats(v);
    renderSessions(v);
    renderTurns(v);
  }

  async function loadConfig(v) {
    if (!live(v)) return;
    const seq = ++v.configSeq;
    try {
      const data = await Shell.api("/api/bot/config", { signal: v.ctx.signal });
      if (!live(v) || seq !== v.configSeq) return;
      v.config = data && typeof data === "object" ? data : {};
      v.configState = "ok";
      v.configError = null;
    } catch (error) {
      if (!live(v) || seq !== v.configSeq) return;
      if (isAbort(error) && v.ctx.signal.aborted) return;
      v.configState = isMissingApi(error) ? "missing" : "error";
      v.configError = error;
    }
    renderConfig(v);
  }

  function refresh(v, { force = false } = {}) {
    if (!live(v)) return;
    v.refreshedAt = Date.now();
    loadStatus(v, { force });
    loadStats(v, { force });
    // Cấu hình chỉ đọc một lần lúc vào màn hình: một lần hỏng vì mạng chớp không được để ba công tắc
    // "không rõ" suốt buổi. "missing" (404/405/501) thì thôi — hỏi lại cũng vẫn thiếu.
    if (v.configState === "error") loadConfig(v);
  }

  function recheck(v) {
    if (!live(v) || v.checking) return;
    loadStatus(v, { force: true, check: true });
  }

  /* ── lệnh bật / tắt / khởi động lại ──────────────────────────── */
  async function confirmStop(v) {
    // S.action còn null trong lúc hộp thoại mở, nên phải có chốt riêng: mỗi lúc chỉ một hộp xác nhận.
    if (S.action || v.confirming || !live(v)) return;
    v.confirming = true;
    let ok = false;
    try {
      ok = await confirmDialog({
        title: "Tắt bot Discord?",
        body: "Ún sẽ ngừng trả lời trên Discord cho tới khi bật lại. Lượt đang chờ hoặc đang chạy không bị hủy.",
        confirmLabel: "Tắt bot", tone: "danger", icon: "power", signal: v.ctx.signal,
      });
    } finally {
      v.confirming = false;
    }
    // Nhịp 20 giây có thể đã báo bot dừng trong lúc hộp thoại mở: đừng gửi lệnh tắt cho thứ đã tắt.
    if (!ok || !live(v)) return;
    if (!v.status || v.status.state !== "running") {
      toast("Bot không còn chạy — không gửi lệnh tắt.", "danger");
      return;
    }
    runAction("stop");
  }

  /* Không gắn signal của view: rời trang không bỏ dở lệnh (máy chủ vẫn chạy compose tới cùng) — chỉ
     có hạn chờ riêng = hạn của máy chủ + GRACE_MS. Kết quả vẽ vào lần mount đang sống lúc đó (có thể
     khác lần đã bấm), hoặc toast nếu người dùng đã rời màn hình. */
  async function runAction(kind) {
    if (S.action) return;
    const cfg = ACTIONS[kind];
    if (kind === "restart" && S.restart === false) {
      toast(RESTART_MISSING, "danger");
      return;
    }
    const wait = timed(null, cfg.wait + GRACE_MS);
    S.action = { kind, started: Date.now() };
    const opener = live(V) ? V : null;
    if (opener) {
      opener.notice = null;
      renderNotice(opener);
      renderBanner(opener);
    }
    let result = null;
    let failure = null;
    try {
      result = await Shell.api(cfg.path, { method: "POST", signal: wait.signal });
    } catch (error) {
      failure = error || new Error("Đã xảy ra lỗi không xác định.");
    }
    S.action = null;
    const v = live(V) ? V : null;
    if (failure) reportFailure(kind, failure, wait.timedOut(), v);
    else reportSuccess(kind, result, v);
    if (v) {
      renderBanner(v);
      refresh(v, { force: true });
      if (kind !== "stop") loadConfig(v);
    }
  }

  function showNotice(v, notice) {
    if (v) {
      v.notice = notice;
      renderNotice(v);
    } else {
      toast(notice.detail ? `${notice.title} ${notice.detail}` : notice.title, "danger", { duration: 6000 });
    }
  }

  function reportSuccess(kind, result, v) {
    const cfg = ACTIONS[kind];
    const status = normalizeStatus(result);
    if (v && status) {
      v.statusSeq++;                 // bỏ kết quả của lần hỏi trạng thái cũ còn đang bay
      v.status = status;
      v.statusAt = Date.now();
      v.statusError = null;
    }
    const want = kind === "stop" ? "stopped" : "running";
    if (status && status.state !== want) {
      showNotice(v, {
        tone: "warn",
        title: kind === "stop" ? "Đã gửi lệnh tắt nhưng bot vẫn chạy." : "Đã gửi lệnh bật nhưng bot chưa chạy.",
        detail: status.detail
          ? `Trạng thái máy chủ báo: ${status.detail}.`
          : "Xem log của container: docker compose --profile discord logs discord-bot.",
      });
      return;
    }
    toast(cfg.done);
  }

  function reportFailure(kind, error, timedOut, v) {
    const cfg = ACTIONS[kind];
    if (kind === "restart" && isMissingApi(error)) {
      S.restart = false;
      toast(RESTART_MISSING, "danger");
      return;
    }
    let detail = errText(error);
    if (timedOut) {
      detail = `Máy chủ chưa trả lời sau ${Math.round((cfg.wait + GRACE_MS) / 1000)} giây. Lệnh có thể vẫn đang chạy — trạng thái thật hiện ở lần kiểm tra kế tiếp.`;
    } else if (error.code === "DISCORD_TOKEN_MISSING") {
      const said = String(error.message || "").trim();
      // Tên nút phải là nút vừa bấm: sau một lần "Khởi động lại" hỏng thì "Bật bot" không có trên màn hình.
      detail = `${said}${/[.!?…]$/.test(said) ? "" : "."} Điền DISCORD_TOKEN trong .env ở thư mục gốc của repo rồi bấm «${cfg.label}» lần nữa.`;
    } else if (error.code === "BOT_CONTROL_FAILED") {
      detail = `docker compose báo lỗi: ${error.message}`;
    }
    showNotice(v, { tone: "danger", title: `${cfg.fail}.`, detail });
  }

  /* ── dựng màn hình ───────────────────────────────────────────── */
  function statCard(label, title) {
    const value = h("div", { class: "stat-value" });
    const sub = h("div", { class: "stat-delta" });
    const card = h("div", { class: "stat stat-bot", title }, h("div", { class: "stat-label" }, label), value, sub);
    return { card, value, sub };
  }

  function build(ctx) {
    const dot = h("span", { class: "bot-dot", dataset: { state: "loading" }, "aria-hidden": "true" });
    const statusText = h("span", { class: "bot-banner-status-live", role: "status" });
    const statusClock = h("span", { "aria-hidden": "true" });
    // Ghi chú "số đã cũ" để ngoài vùng aria-live: nó đổi theo mỗi nhịp hỏng, không phải tin cần đọc lại.
    const statusStale = h("span", { class: "bot-status-stale" });
    const statusBox = h("div", { class: "bot-banner-status-text" }, statusText, statusClock, statusStale);
    const actions = h("div", { class: "bot-banner-actions" });
    const banner = h("section", { class: "banner-brand bot-banner", "aria-label": "Trạng thái bot Discord" },
      h("span", { class: "bot-banner-deco", "aria-hidden": "true" }),
      h("span", { class: "icon-tile icon-tile-56" }, icon("bot", { size: 28, sw: 1.8 })),
      h("div", { class: "bot-banner-main" },
        h("div", { class: "bot-banner-kicker" }, "Bot Discord"),
        h("div", { class: "bot-banner-name" }, "Ún"),
        h("div", { class: "bot-banner-status" }, dot, statusBox)),
      actions);
    const noticeEl = h("div", { class: "bot-notice", role: "alert", hidden: true });

    const statEls = {
      active: statCard("Phiên active"),
      done: statCard("Lượt hoàn tất"),
      sent: statCard("Tin đã gửi", "Số tin bot đã đăng lên Discord (câu trả lời dài được chia thành nhiều tin)"),
      latency: statCard("Độ trễ p50", "Độ trễ ở Bảng điều khiển gộp cả web và Discord; máy chủ chưa tách riêng cho bot"),
    };
    const stats = h("div", { class: "bot-stats" }, statEls.active.card, statEls.done.card, statEls.sent.card, statEls.latency.card);

    const sessionMeta = h("span", { class: "card-meta" });
    const sessionList = h("div", { class: "bot-session-list", "aria-label": "Phiên gần đây" });
    const sessions = h("section", { class: "card card-flush bot-sessions" },
      h("div", { class: "card-head" }, h("strong", { class: "card-title" }, "Phiên gần đây"), sessionMeta),
      sessionList);

    const bars = h("div", { class: "bot-bars" });
    const barsNote = h("div", { class: "bot-muted bot-bars-note", hidden: true });
    const turns = h("section", { class: "card card-p bot-turns" },
      h("strong", { class: "bot-card-title" }, "Lượt theo trạng thái"), bars, barsNote);

    const flags = h("div", { class: "bot-flags" });
    const config = h("section", { class: "card card-p bot-config" },
      h("strong", { class: "bot-card-title" }, "Lệnh & cấu hình"),
      h("div", { class: "bot-cmds" }, COMMANDS.map(([cmd, desc]) => h("div", { class: "bot-cmd" },
        h("code", { class: "code code-accent" }, cmd), h("span", { class: "bot-cmd-desc" }, desc)))),
      flags);

    const page = h("div", { class: "page bot-page" },
      h("div", { class: "page-inner w-1080" },
        banner, noticeEl, stats,
        h("div", { class: "bot-grid" }, sessions, h("div", { class: "bot-side" }, turns, config))));

    return {
      ctx, page, dot, statusText, statusClock, statusStale, statusBox, actions, noticeEl, statEls, sessionMeta, sessionList,
      bars, barsNote, flags,
      status: null, statusAt: 0, statusError: null, statusSeq: 0, statusInflight: null, checking: false, checkSeq: 0,
      actionsKey: null, refocus: null, confirming: false,
      stats: null, statsError: null, statsSeq: 0, statsInflight: null, barsKey: null,
      config: null, configState: null, configError: null, configSeq: 0,
      health: Shell.health, notice: null, refreshedAt: 0,
    };
  }

  function mount(ctx) {
    ctx.setHeader("Bot Discord — Ún", "Điều khiển và theo dõi bot dùng chung backend");
    const v = build(ctx);
    V = v;
    ctx.root.append(v.page);
    renderAll(v);

    Shell.onHealth((health) => {
      if (!live(v)) return;
      v.health = health;
      renderConfig(v);
    }, { signal: ctx.signal });
    // 20 giây/lần khi đang xem (như bảng điều khiển cũ); tab ẩn thì thôi, hiện lại thì làm ngay.
    ctx.every(() => { if (!document.hidden) refresh(v); }, REFRESH_MS);
    ctx.on(document, "visibilitychange", () => {
      if (!document.hidden && Date.now() - v.refreshedAt >= REFRESH_MS) refresh(v);
    });
    // Đồng hồ "đang bật bot… N giây" khi có lệnh đang chạy.
    ctx.every(() => { if (S.action && live(v)) renderStatusLine(v); }, 1000);

    refresh(v, { force: true });
    loadConfig(v);
  }

  /* Cùng hash (Router.go lại #/bot) → làm mới tại chỗ, không dựng lại. */
  function update(ctx) {
    if (!V || V.ctx !== ctx) return false;
    refresh(V, { force: true });
    return true;
  }

  function unmount() {
    V = null;
  }

  Router.register("bot", { admin: true, mount, update, unmount });
})();
