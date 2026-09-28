/* ══════════════════════════════════════════════════════════════════
   /ui/views/models.js — màn hình "Model & phiên bản" (#/models, chỉ quản
   trị viên — router tự chặn thành viên).

   Một IIFE, không tên top-level. Gồm:
     - thanh trạng thái: chấm Ollama từ /health.ollama (Shell.onHealth, shell
       poll 60 giây), số vai trò trong registry và số vai trò chưa cấu hình,
       tên tệp registry, nút "Kiểm tra registry" (F6 GET /models/check);
     - lưới card một card mỗi vai trò: extractor + verifier gộp một card vì
       chúng luôn bật/tắt cùng nhau; condenser có trong registry thật nhưng
       thiếu trong README nên vẫn được vẽ (không giấu vai trò máy chủ trả về);
     - mỗi card: pill trạng thái, ô "ĐANG PHỤC VỤ" (bản ĐANG NẠP, không phải
       con trỏ active), danh sách version (F6 registry[role].versions; máy chủ
       chưa có thì suy ra từ active/requested/loaded), ghi chú, và các nút
       Promote / Revert / "Chi tiết →".

   Hợp đồng API: research/api-core.md §8 (/models: models + registry, status,
   reason, 8 vai trò) và §7 (/health.ollama, model_fallback); spec F6
   (POST /models/{role}/promote {version}, POST /models/{role}/revert,
   GET /models/check). Hành vi cũ: old-chat 107, old-secondary 64-66.
   Promote/Revert CHỈ đổi con trỏ trong model_versions.yaml — máy chủ vẫn chạy
   bản cũ tới khi khởi động lại, mọi lời trong UI phải nói đúng như vậy.
   Gọi mạng: chỉ Shell.api. V là DOM + dữ liệu của lần mount đang sống, null khi
   đã rời view — mọi việc bất đồng bộ kiểm tra live(v) trước khi vẽ.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  const JSON_HEADERS = { "Content-Type": "application/json" };

  /* Câu nói khi máy chủ chưa có endpoint F6 (404/405/501 không mã lỗi). */
  const MISSING_SWITCH = "Máy chủ chưa hỗ trợ đổi phiên bản — sửa model_versions.yaml rồi khởi động lại.";
  const MISSING_CHECK = "Máy chủ chưa hỗ trợ kiểm tra registry — chạy python -m app.config.model_registry --check trên máy chủ.";

  /* Một card = một hoặc nhiều vai trò của registry. Thứ tự theo README mục 7,
     thêm condenser ở cuối (có thật trong registry, README bỏ sót).
     icon: tên <symbol> trong sprite của index.html. */
  const CARDS = [
    { roles: ["general"], title: "Trò chuyện & RAG", icon: "chat" },
    { roles: ["embedding"], title: "Embedding", icon: "list" },
    { roles: ["ocr"], title: "OCR", icon: "scan-frame" },
    { roles: ["reranker"], title: "Reranker", icon: "zap" },
    { roles: ["extractor", "verifier"], title: "Extractor / Verifier ghi nhớ", icon: "bulb" },
    { roles: ["vision"], title: "Vision", icon: "spark" },
    { roles: ["condenser"], title: "Tóm tắt hội thoại", icon: "chat" },
  ];

  /* registry[role].status (api-core §8). rank = mức "đáng chú ý" để gộp card
     nhiều vai trò: card lấy trạng thái nặng nhất. */
  const STATUS = {
    active: { label: "active", tone: "ok", rank: 0 },
    fallback: { label: "fallback", tone: "warn", warn: true, rank: 5 },
    missing: { label: "fallback", tone: "warn", warn: true, rank: 5 },
    degraded: { label: "fallback", tone: "warn", warn: true, rank: 5 },
    incomplete: { label: "fallback", tone: "warn", warn: true, rank: 5 },
    disabled: { label: "fallback", tone: "warn", warn: true, rank: 5 },
    unverified: { label: "chờ kiểm", tone: "warn", rank: 4 },
    pending: { label: "chờ kiểm", tone: "warn", rank: 4 },
    unconfigured: { label: "chưa cấu hình", tone: "muted", muted: true, rank: 2 },
    off: { label: "tắt", tone: "muted", muted: true, rank: 1 },
  };

  /* versions[].status → nhãn phải + màu chấm (P:754). Prototype chỉ có ba bộ ba:
     accent + accent + nền, warn + warn + nền, hoặc mờ + mờ + trong suốt — chấm, chữ và
     nền luôn cùng một màu, không có dòng nửa sáng nửa mờ.
     warn (is-serving) DÀNH RIÊNG cho vai trò thật sự đang lùi về bản khác; bản đang chạy
     của một vai trò lành (ghim env) dùng serving_ok, màu accent như pill "active" của nó. */
  const VERSION_KINDS = {
    active: { label: "active", dot: "is-active", tone: "is-active", fill: true },
    serving: { label: "đang phục vụ", dot: "is-serving", tone: "is-serving", fill: true },
    serving_ok: { label: "đang phục vụ", dot: "is-active", tone: "is-active", fill: true },
    failed: { label: "lỗi nạp", dot: "", tone: "" },
    candidate: { label: "ứng viên", dot: "", tone: "" },
    pending: { label: "chờ khởi động lại", dot: "", tone: "" },
    unverified: { label: "chờ kiểm", dot: "", tone: "" },
    off: { label: "off", dot: "", tone: "" },
  };

  let V = null;

  /* ── tiện ích ────────────────────────────────────────────────── */

  const isAbort = (error) => Boolean(error) && error.name === "AbortError";
  const live = (v) => Boolean(v) && V === v && !v.ctx.signal.aborted;

  /* null / undefined / "" → null, còn lại → chuỗi. */
  function str(value) {
    return value === null || value === undefined || value === "" ? null : String(value);
  }

  /* sendJson đã dịch mã lỗi quen (ERROR_HINTS) và lỗi mạng; các mã riêng của F6 thì máy chủ
     trả câu tiếng Anh ("Unknown model role nope") — dịch ở đây, đừng để lọt vào toast. */
  function errText(error, fallback = "Đã xảy ra lỗi không xác định.") {
    const code = error && error.code;
    if (code === "INTERNAL_ERROR") return "Máy chủ gặp lỗi không mong muốn (500). Thử lại sau.";
    if (code === "MODEL_ROLE_NOT_FOUND") return "Máy chủ không biết vai trò này.";
    if (code === "MODEL_VERSION_NOT_FOUND") return "Phiên bản này không có trong registry.";
    return (error && error.message) || fallback;
  }

  /* 401 cuối cùng: Shell.api đã dựng màn đăng nhập kèm đúng câu "Phiên đăng nhập đã hết hạn…".
     Thêm toast nữa là nói hai lần cùng một chuyện, chồng lên màn đăng nhập (toast z 90 > 70). */
  function handledByShell(error) {
    return Boolean(error) && error.status === 401 && Shell.authEnabled;
  }

  function statusInfo(key) {
    return STATUS[key] || { label: str(key) || "không rõ", tone: "muted", rank: 3 };
  }

  function versionKind(key) {
    return VERSION_KINDS[key] || { label: str(key) || "", dot: "", tone: "" };
  }

  /* Bỏ trùng, giữ thứ tự. */
  function uniq(list) {
    return [...new Set(list.filter((item) => item !== null && item !== undefined && item !== ""))];
  }

  /* ── đọc registry ────────────────────────────────────────────── */

  /* Vai trò có ĐANG LÙI VỀ BẢN KHÁC vì sự cố hay không. Chỉ khi đó màu warn mới đúng:
     con trỏ bị biến môi trường ghi đè, hay bản vừa promote chờ khởi động lại, đều là
     chuyện bình thường (registry.fallback = status ∈ 5 trạng thái nhóm fallback, api-core §8). */
  function isFallbackRole(row) {
    return row.fallback === true || Boolean(statusInfo(str(row.status)).warn);
  }

  /* Embedding: prototype ghi kèm cặp collection sau tên model ("qwen3-embedding:0.6b ·
     documents/memories"); registry.embedding.collections có sẵn dữ liệu đó. */
  function versionName(role, row, name) {
    const col = role === "embedding" && row.collections && typeof row.collections === "object" ? row.collections : null;
    const pair = col && str(col.documents) && str(col.memories) ? `${col.documents}/${col.memories}` : null;
    if (!pair) return name;
    return name ? `${name} · ${pair}` : pair;
  }

  /* Máy chủ đã có F6 → dùng nguyên danh sách nó trả (thứ tự của model_versions.yaml).
     Chưa có → suy ra từ active / loaded / requested, bỏ trùng, active đứng trước. */
  function versionRows(role, row) {
    const list = Array.isArray(row.versions) ? row.versions : null;
    const active = str(row.active);
    const loaded = str(row.loaded);
    const requested = str(row.requested);
    const status = str(row.status);
    const warnRole = isFallbackRole(row);
    if (list) {
      return list.map((item) => {
        const id = str(item && item.id) || "—";
        const kind = str(item && item.status) || "candidate";
        return {
          role, fromServer: true, id,
          name: versionName(id === active ? role : null, row, str(item && item.name)),
          // Máy chủ nói "serving" cho bản đang chạy dù vai trò lành hay hỏng: warn chỉ khi hỏng.
          kind: kind === "serving" && !warnRole ? "serving_ok" : kind,
        };
      });
    }
    const named = loaded || requested;   // registry.name là tên của bản đang nạp/được yêu cầu
    const out = [];
    const seen = new Set();
    const push = (id, kind) => {
      if (!id || seen.has(id)) return;
      seen.add(id);
      out.push({ role, fromServer: false, id, name: id === named ? versionName(role, row, str(row.name)) : null, kind });
    };
    /* Hai con trỏ, hai dòng: `active` là con trỏ trong model_versions.yaml, `loaded` là bản
       backend thật sự đang chạy.
       - tắt: cả hai dòng đều "off";
       - đang chạy đúng con trỏ: một dòng "active";
       - vai trò hỏng: con trỏ "lỗi nạp", bản đang chạy "đang phục vụ" (warn);
       - con trỏ lành nhưng bản đang chạy khác (ghim env): con trỏ VẪN là "active" — nó không
         hỏng, chỉ bị biến môi trường ghi đè, và ghi chú của card nói rõ điều đó;
       - chưa nạp gì: "chờ kiểm" nếu registry chưa xác minh, còn lại là "ứng viên". */
    let activeKind;
    let loadedKind;
    if (status === "off") {
      activeKind = "off";
      loadedKind = "off";
    } else if (loaded && loaded === active) {
      activeKind = "active";
      loadedKind = "active";
    } else if (warnRole) {
      activeKind = "failed";
      loadedKind = "serving";
    } else if (loaded) {
      activeKind = "active";
      loadedKind = "serving_ok";
    } else {
      activeKind = status === "unverified" || status === "pending" ? "unverified" : "candidate";
      loadedKind = "candidate";
    }
    push(active, activeKind);
    push(loaded, loadedKind);
    push(requested, "candidate");
    return out;
  }

  /* Dòng thứ hai của ô "ĐANG PHỤC VỤ": bản ĐANG NẠP (không phải con trỏ active).
     Vai trò không nạp gì → nói thẳng con trỏ active là gì ("active: null" khi trống). */
  function servingIds(rows) {
    if (rows.every((r) => !str(r.row.loaded))) {
      return `active: ${rows.map((r) => str(r.row.active) || "null").join(" · ")}`;
    }
    return rows.map((r) => str(r.row.loaded) || `active: ${str(r.row.active) || "null"}`).join(" · ");
  }

  /* ── ghi chú của card ────────────────────────────────────────── */

  /* Ghi chú: {text, tone}. warn-soft (cam) CHỈ dành cho chuyện thật sự hỏng — câu "hỏng lúc
     khởi động" chỉ đúng với fallback/missing, còn degraded/incomplete/disabled thì đọc nguyên
     `reason` của máy chủ thay vì đoán nguyên nhân. Vai trò tắt hoặc bị env ghi đè là cấu hình
     có chủ ý, ghi chú mờ, không phải báo động.
     README bảo đưa `reason` vào tooltip (vẫn còn ở ô "đang phục vụ"), nhưng tooltip thì bàn
     phím, cảm ứng và trình đọc màn hình không với tới, nên câu đó nằm luôn trong ghi chú. */
  function cardNotes(spec, rows) {
    const notes = [];
    const seen = new Set();
    const many = rows.length > 1;
    const add = (role, line, tone) => {
      const text = role && many ? `${role}: ${line}` : line;
      if (!text || seen.has(text)) return;
      seen.add(text);
      notes.push({ text, tone });
    };
    for (const { role, row } of rows) {
      const status = str(row.status);
      const info = statusInfo(status);
      const loaded = str(row.loaded);
      const reason = str(row.reason);
      if (status === "fallback" || status === "missing") {
        add(role, loaded
          ? `Bản active hỏng lúc khởi động, hệ tự lùi về ${loaded}. Xem data/logs/ATTENTION_model_fallback.txt.`
          : "Bản active hỏng lúc khởi động và không còn bản nào để lùi về. Xem data/logs/ATTENTION_model_fallback.txt.", "warn");
      } else if (info.warn) {
        add(role, reason || `Registry báo trạng thái "${status}" cho vai trò này.`, "warn");
      } else if (reason) {
        // Vai trò tắt: reason là cờ môi trường đã tắt nó (api-core §8 — có thể null).
        add(role, reason, "muted");
      }
      if (role === "embedding") add(null, "Embedding không bao giờ tự lùi phiên bản. Đổi model = rebuild collection.", "warn");
      if (role === "vision" && status === "unconfigured") add(null, "/vision/chat trả 501 cho tới khi có con trỏ active.", "warn");
      // Con trỏ đến từ MODEL_VERSION_<ROLE> / tag env chứ không phải tệp registry.
      const source = str(row.source);
      if (source && source !== "registry") {
        add(role, `Con trỏ đến từ biến môi trường (source: ${source}), không phải model_versions.yaml.`, "muted");
      }
    }
    return notes;
  }

  /* ── dựng card ───────────────────────────────────────────────── */

  function buildCard(spec, registry, models, v) {
    const rows = spec.roles
      .filter((role) => registry[role] && typeof registry[role] === "object")
      .map((role) => ({ role, row: registry[role], cfg: models[role] && typeof models[role] === "object" ? models[role] : null }));
    if (!rows.length) return null;

    const worst = rows.reduce((acc, r) => {
      const info = statusInfo(str(r.row.status));
      return info.rank > acc.rank ? info : acc;
    }, statusInfo(str(rows[0].row.status)));

    const versions = rows.flatMap(({ role, row }) => versionRows(role, row));
    const hasServerList = rows.some(({ row }) => Array.isArray(row.versions));
    const reasons = uniq(rows.map(({ role, row }) => {
      const reason = str(row.reason);
      return reason && rows.length > 1 ? `${role}: ${reason}` : reason;
    }));

    /* Tên model: /models (bản đang chạy) trước, không có thì tên trong registry. */
    const names = uniq(rows.map(({ row, cfg }) => (cfg && str(cfg.name)) || str(row.name)));
    /* provider CHỈ có trong /models.models[role]. reranker không bao giờ có ở đó và vision
       cũng vắng khi active = null (api-core §8), nên với các vai trò đó không nguồn nào nói
       provider là gì — bỏ hẳn đoạn "· <provider>" thay vì mặc định "ollama": reranker là
       cross-encoder sentence-transformers chạy trong tiến trình, nói "ollama" là chỉ sai chỗ. */
    const providers = uniq(rows.map(({ cfg }) => cfg && str(cfg.provider)));

    const head = h("div", { class: "mdl-head" },
      h("span", { class: ["icon-tile", "icon-tile-36", worst.muted ? "tone-muted-3" : "tone-accent"] }, icon(spec.icon, { size: 17, sw: 1.9 })),
      h("div", { class: "mdl-head-main" },
        h("div", { class: "mdl-role" }, spec.title),
        h("div", { class: "mdl-key", title: spec.roles.join(" · ") }, spec.roles.join(" · "))),
      pill(worst.label, worst.tone, { dot: false, size: "sm", bold: true }));

    const serving = h("div", { class: "serving-box", title: reasons.join(" · ") || null },
      h("div", { class: "mdl-serving-label" }, "Đang phục vụ"),
      h("div", { class: "mdl-serving-name" }, names.join(" · ") || "—"),
      h("div", { class: "mdl-serving-sub" }, providers.length ? `${servingIds(rows)} · ${providers.join(" · ")}` : servingIds(rows)));

    /* Khối version luôn có mặt, kể cả rỗng (vision): prototype cũng vậy, nên khoảng
       cách giữa ô "ĐANG PHỤC VỤ" và ghi chú giống hệt các card khác. */
    const versionList = h("div", { class: "mdl-versions" }, versions.map((item) => {
      const kind = versionKind(item.kind);
      return h("div", { class: ["version-row", kind.fill && "mdl-vrow-fill"] },
        h("span", { class: ["mdl-vdot", kind.dot] }),
        h("span", { class: "mdl-vid", title: item.id }, item.id),
        h("span", { class: "mdl-vname", title: item.name || null }, item.name || ""),
        h("span", { class: ["mdl-vlabel", kind.tone] }, kind.label));
    }));

    const notes = cardNotes(spec, rows);
    const noteBox = notes.length
      ? h("div", { class: "mdl-notes" }, notes.map((note) =>
        h("div", { class: ["note", note.tone === "warn" ? "tone-warn" : "tone-muted"] }, note.text)))
      : null;

    const admin = Shell.isAdmin();
    const noVersions = versions.length === 0;
    /* Ứng viên = mọi version không phải con trỏ active hiện tại. Nút Promote vẫn bấm được khi
       danh sách rỗng (lead chốt: chỉ khóa khi KHÔNG BIẾT vai trò có phiên bản nào) — cú bấm
       mở menu nói "Không còn phiên bản nào khác", hoặc câu "máy chủ chưa hỗ trợ" khi chưa có F6. */
    const activeIds = new Set(rows.map(({ row }) => str(row.active)).filter(Boolean));
    const candidates = versions.filter((item) => !activeIds.has(item.id));
    // Máy chủ chưa có F6+: các dòng version là do UI suy ra, không phải danh sách thật — nói rõ ở tooltip.
    const derived = !hasServerList ? "Danh sách dưới đây do UI suy ra: GET /models chưa trả registry.versions. " : "";
    const promoteBtn = admin ? h("button", {
      type: "button", class: "btn btn-30 btn-outline", disabled: noVersions,
      title: noVersions ? "Máy chủ không cho biết vai trò này có phiên bản nào"
        : `${derived}Đổi con trỏ active trong model_versions.yaml`,
      onClick: (event) => promote(v, spec, candidates, hasServerList, event.currentTarget),
    }, "Promote") : null;
    const revertBtn = admin ? h("button", {
      type: "button", class: "btn btn-30 btn-outline", disabled: noVersions,
      title: noVersions ? "Máy chủ không cho biết vai trò này có phiên bản nào" : `${derived}Quay lại con trỏ active trước đó`,
      onClick: (event) => revert(v, rows, event.currentTarget),
    }, "Revert") : null;
    const detailBtn = h("button", {
      type: "button", class: "btn btn-30 btn-ghost-accent",
      onClick: () => detailDialog(v, spec, rows),
    }, "Chi tiết →");

    return h("section", {
      class: ["card", "card-p", "card-hover", "mdl-card", worst.warn && "is-warn"],
      "aria-label": `${spec.title} — ${worst.label}`, dataset: { card: spec.roles.join(" ") },
    }, head, serving, versionList, noteBox,
    h("div", { class: "mdl-actions" }, promoteBtn, revertBtn, h("span", { class: "spacer" }), detailBtn));
  }

  function skelCard() {
    return h("section", { class: "card card-p mdl-card mdl-skel", "aria-hidden": "true" },
      h("div", { class: "mdl-head" }, skeleton({ w: 36, h: 36, r: 10 }),
        h("div", { class: "mdl-head-main" }, skeleton({ w: "58%", h: 12 }), skeleton({ w: "34%", h: 10 }))),
      h("div", { class: "serving-box" }, skeleton({ w: "40%", h: 9 }), skeleton({ w: "64%", h: 13 }), skeleton({ w: "48%", h: 11 })),
      h("div", { class: "mdl-versions" }, skeleton({ w: "100%", h: 24, r: 7 }), skeleton({ w: "100%", h: 24, r: 7 })));
  }

  /* ── Promote / Revert ────────────────────────────────────────── */

  /* Máy chủ chưa trả registry[role].versions → không có danh sách ứng viên nào để chọn:
     nói thật ngay, không gửi request đoán mò. */
  function promote(v, spec, candidates, hasServerList, anchor) {
    if (!live(v)) return;
    if (!hasServerList) { toast(MISSING_SWITCH, "danger"); return; }
    // Card gộp: nói luôn version này thuộc vai trò nào, id hai vai trò có thể trông giống nhau.
    const many = spec.roles.length > 1;
    const items = candidates.map((item) => ({
      label: item.id,
      hint: [many ? item.role : null, item.name || versionKind(item.kind).label].filter(Boolean).join(" · "),
      onSelect: () => confirmPromote(v, item),
    }));
    dropdown(anchor, items.length ? items : [{ label: "Không còn phiên bản nào khác.", disabled: true }],
      { align: "start", className: "mdl-menu" });
  }

  async function confirmPromote(v, item) {
    if (!live(v)) return;
    const ok = await confirmDialog({
      title: `Đặt ${item.id} làm active?`,
      body: `Vai trò ${item.role}. Con trỏ active trong model_versions.yaml đổi sang ${item.id}; backend vẫn chạy bản hiện tại cho tới khi khởi động lại.`,
      confirmLabel: "Đặt làm active", tone: "accent", icon: "check-circle", signal: v.ctx.signal,
    });
    if (!ok || !live(v)) return;
    try {
      await Shell.api(`/models/${encodeURIComponent(item.role)}/promote`, {
        method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ version: item.id }), signal: v.ctx.signal,
      });
    } catch (error) {
      if (isAbort(error) || !live(v) || handledByShell(error)) return;
      // isMissingApi = 404/405/501 không mã lỗi (spec.md "API chưa có"). Giả định: F6 thật khi có
      // sẽ trả mã lỗi riêng cho "không có vai trò/phiên bản" (mock trả MODEL_*_NOT_FOUND); nếu nó
      // ném HTTPException(404) trơn thì câu dưới đây sẽ đổ cho máy chủ là chưa hỗ trợ đổi phiên bản.
      toast(isMissingApi(error) ? MISSING_SWITCH : errText(error, "Không đổi được phiên bản."), "danger");
      return;
    }
    toast(`Đã đặt ${item.id} làm active — có hiệu lực sau khi khởi động lại backend.`);
    load(v, { focusRole: item.role });
  }

  /* Card gộp (extractor + verifier) không có "con trỏ trước đó" chung: hỏi vai trò trước. */
  function revert(v, rows, anchor) {
    if (!live(v)) return;
    if (rows.length === 1) { confirmRevert(v, rows[0].role); return; }
    dropdown(anchor, rows.map(({ role }) => ({ label: role, onSelect: () => confirmRevert(v, role) })),
      { align: "start", className: "mdl-menu" });
  }

  async function confirmRevert(v, role) {
    if (!live(v)) return;
    const ok = await confirmDialog({
      title: `Quay lại phiên bản trước của ${role}?`,
      body: "Con trỏ active trở về giá trị trước đó trong model_versions.yaml; backend vẫn chạy bản hiện tại cho tới khi khởi động lại.",
      confirmLabel: "Quay lại", tone: "warn", icon: "retry", signal: v.ctx.signal,
    });
    if (!ok || !live(v)) return;
    try {
      await Shell.api(`/models/${encodeURIComponent(role)}/revert`, { method: "POST", headers: JSON_HEADERS, signal: v.ctx.signal });
    } catch (error) {
      if (isAbort(error) || !live(v) || handledByShell(error)) return;
      toast(isMissingApi(error) ? MISSING_SWITCH : errText(error, "Không quay lại được phiên bản trước."), "danger");
      return;
    }
    toast(`Đã trả con trỏ active của ${role} về bản trước — có hiệu lực sau khi khởi động lại backend.`);
    load(v, { focusRole: role });
  }

  /* ── Chi tiết → ──────────────────────────────────────────────── */

  function kvValue(value) {
    if (value === null) return "null";
    if (value === undefined) return "—";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function kvList(source) {
    const entries = Object.entries(source || {});
    if (!entries.length) return h("div", { class: "mdl-kv-empty" }, "Không có trường nào.");
    return h("div", { class: "mdl-kv" }, entries.map(([key, value]) => h("div", { class: "mdl-kv-row" },
      h("span", { class: "mdl-kv-key" }, key),
      h("span", { class: "mdl-kv-val" }, kvValue(value)))));
  }

  function detailDialog(v, spec, rows) {
    if (!live(v)) return;
    const sheet = h("div", { class: "mdl-sheet" }, rows.flatMap(({ role, row, cfg }) => [
      h("div", { class: "mdl-sheet-sec" },
        h("div", { class: "section-label" }, `registry · ${role}`),
        kvList(row)),
      h("div", { class: "mdl-sheet-sec" },
        h("div", { class: "section-label" }, `models · ${role}`),
        cfg ? kvList(cfg)
          : h("div", { class: "mdl-kv-empty" }, "Vai trò này không có cấu hình trong /models.models (chỉ registry biết nó).")),
    ]));
    // content (không phải body): khối này là <div>/<pre>, không phải một câu mô tả.
    dialog({
      tone: "accent", icon: "cpu", title: spec.title, content: sheet, cancelLabel: "Đóng", signal: v.ctx.signal,
    });
  }

  /* ── Kiểm tra registry (F6 GET /models/check) ────────────────── */

  /* KHÔNG dùng btn.disabled để chặn bấm hai lần: nút đang giữ focus mà bị disabled thì Chrome
     nhả focus về <body>, và dialog() ghi lại <body> làm chỗ trả focus khi đóng — người dùng bàn
     phím bị ném về đầu trang. Chặn bằng cờ riêng, aria-busy để trình đọc màn hình biết đang chạy. */
  async function runCheck(v, btn) {
    if (!live(v) || btn.dataset.busy === "1") return;
    btn.dataset.busy = "1";
    btn.setAttribute("aria-busy", "true");
    let data = null;
    try {
      data = await Shell.api("/models/check", { signal: v.ctx.signal });
    } catch (error) {
      if (isAbort(error) || !live(v) || handledByShell(error)) return;
      toast(isMissingApi(error) ? MISSING_CHECK : errText(error, "Không kiểm tra được registry."), "danger");
      return;
    } finally {
      if (btn.isConnected) {
        delete btn.dataset.busy;
        btn.removeAttribute("aria-busy");
      }
    }
    if (!live(v)) return;
    const problems = Array.isArray(data && data.problems) ? data.problems.map((line) => String(line)) : [];
    const ok = Boolean(data && data.ok) && !problems.length;
    const output = str(data && data.output);
    dialog({
      tone: ok ? "ok" : "warn", icon: ok ? "check-circle" : "alert",
      title: ok ? "Registry hợp lệ" : `Registry có ${problems.length || "vài"} vấn đề`,
      content: h("div", { class: "mdl-sheet" },
        problems.length ? h("div", { class: "mdl-problems" }, problems.map((line) => h("div", { class: "mdl-problem" }, line))) : null,
        output ? h("pre", { class: "log mdl-out" }, output) : h("div", { class: "mdl-kv-empty" }, "Máy chủ không trả phần output.")),
      cancelLabel: "Đóng", signal: v.ctx.signal,
    });
  }

  /* ── vẽ ──────────────────────────────────────────────────────── */

  /* Chấm Ollama đi theo /health của shell (poll 60 giây), không gọi thêm request. */
  function paintHealth(v) {
    const health = Shell.health;
    // Chưa poll lần nào → chấm xám, không vu cho Ollama là hỏng. /health gọi không được
    // (status "down") thì Ollama chắc chắn cũng không tới được → chấm đỏ.
    const down = Boolean(health) && health.status === "down";
    const ok = Boolean(health) && !down && health.ollama === "ok";
    v.bar.dot.className = `mdl-dot${!health ? " is-unknown" : ok ? "" : " is-bad"}`;
    v.bar.ollama.textContent = !health ? "Đang kiểm tra Ollama…" : ok ? "Ollama đang phục vụ" : "Ollama không phản hồi";
    v.bar.dot.title = !health || ok ? ""
      : down ? "Không gọi được /health" : `/health.ollama = ${str(health.ollama) || "(không có khóa ollama)"}`;
  }

  /* failed: GET /models hỏng — thanh trạng thái là một dòng tóm tắt, không được kẹt ở câu
     "đang đọc" khi đã biết là không đọc được (câu đó cũng chính là câu lúc đang tải). */
  function paintRoles(v, registry, { failed = false } = {}) {
    if (!registry) { v.bar.roles.textContent = failed ? "không đọc được registry" : "đang đọc registry…"; return; }
    const roles = Object.keys(registry);
    // registry[role] có thể là null nếu máy chủ trả dòng hỏng: đừng để nó làm chết cả màn hình.
    const blank = roles.filter((role) => str(registry[role] && registry[role].status) === "unconfigured").length;
    v.bar.roles.textContent = `${roles.length} vai trò, ${blank ? `${blank} vai trò chưa cấu hình` : "mọi vai trò đã cấu hình"}`;
  }

  function paint(v, data) {
    const registry = data && data.registry && typeof data.registry === "object" ? data.registry : {};
    const models = data && data.models && typeof data.models === "object" ? data.models : {};
    paintRoles(v, registry);

    const known = new Set(CARDS.flatMap((spec) => spec.roles));
    // Vai trò máy chủ trả mà bảng CARDS chưa biết (registry đổi sau này): vẫn hiện, icon chung.
    const specs = [...CARDS, ...Object.keys(registry).filter((role) => !known.has(role))
      .map((role) => ({ roles: [role], title: role, icon: "cpu" }))];
    const cards = specs.map((spec) => buildCard(spec, registry, models, v)).filter(Boolean);

    v.body.replaceChildren(cards.length
      ? h("div", { class: "mdl-grid" }, cards)
      : emptyState({
        icon: "cpu", title: "Registry chưa có vai trò nào",
        text: "GET /models trả về registry rỗng — kiểm tra backend/app/config/model_versions.yaml trên máy chủ.",
      }));
  }

  /* ── tải dữ liệu ─────────────────────────────────────────────── */

  /* focusRole: sau promote/revert lưới được dựng lại, nút vừa bấm biến mất — trả focus
     về nút Promote của đúng card đó để người dùng bàn phím không rơi về <body>. */
  async function load(v, { first = false, focusRole = null } = {}) {
    if (!live(v)) return;
    v.seq += 1;
    const my = v.seq;
    if (first) v.body.replaceChildren(h("div", { class: "mdl-grid" }, CARDS.map(() => skelCard())));
    let data;
    try {
      data = await Shell.api("/models", { signal: v.ctx.signal });
    } catch (error) {
      if (isAbort(error) || !live(v) || my !== v.seq) return;
      paintRoles(v, null, { failed: true });
      const shown = new Error(errText(error, "Không đọc được /models."));
      shown.status = error && error.status;
      v.body.replaceChildren(errorState(shown, () => load(v, { first: true })));
      return;
    }
    if (!live(v) || my !== v.seq) return;
    v.data = data;
    paint(v, data);
    if (!focusRole) return;
    const card = [...v.body.querySelectorAll(".mdl-card")]
      .find((node) => String(node.dataset.card || "").split(" ").includes(focusRole));
    const btn = card && card.querySelector(".mdl-actions button:not(:disabled)");
    if (btn) btn.focus({ preventScroll: true });
  }

  /* ── vòng đời ────────────────────────────────────────────────── */

  function mount(ctx) {
    ctx.setHeader("Model & phiên bản", "Registry model_versions.yaml · con trỏ active mỗi vai trò");

    const dot = h("span", { class: "mdl-dot is-unknown" });
    const ollama = h("span", null, "Đang kiểm tra Ollama…");
    const roles = h("span", null, "đang đọc registry…");
    const checkBtn = h("button", {
      // hover-bg: prototype chỉ đổi nền khi rê chuột, chữ giữ nguyên --text-2 (P:516).
      type: "button", class: "btn btn-32 btn-outline hover-bg mdl-bar-btn",
      title: "Chạy kiểm tra registry trên máy chủ (python -m app.config.model_registry --check)",
    }, icon("retry", { size: 13 }), "Kiểm tra registry");
    // role="status" (aria-live) chỉ bọc phần CHỮ tự đổi; nút không nằm trong vùng đọc lại.
    const bar = h("div", { class: "status-bar" },
      dot,
      h("span", { class: "mdl-bar-text", role: "status" },
        ollama, " · ", roles, " · ", "registry ", h("code", { class: "code" }, "model_versions.yaml")),
      h("span", { class: "spacer" }),
      checkBtn);

    const body = h("div");
    ctx.root.append(h("div", { class: "page" }, h("div", { class: "page-inner w-1080" }, bar, body)));

    const v = { ctx, bar: { dot, ollama, roles }, body, data: null, seq: 0 };
    V = v;
    checkBtn.addEventListener("click", () => runCheck(v, checkBtn));

    paintHealth(v);
    Shell.onHealth(() => { if (live(v)) paintHealth(v); }, { signal: ctx.signal });
    load(v, { first: true });
  }

  /* Router.go lại đúng #/models (cùng hash) → đọc lại /models, không dựng lại. */
  function update(ctx, info) {
    if (!V || V.ctx !== ctx) return false;
    if (info && info.same) load(V);
    return true;
  }

  function unmount() {
    V = null;
  }

  Router.register("models", { admin: true, mount, update, unmount });
})();
