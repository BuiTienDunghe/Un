/* ══════════════════════════════════════════════════════════════════
   /ui/views/labels.js — màn hình "Duyệt phân loại" (#/labels, chỉ quản trị viên).
   Model decided đề xuất mỗi tin nhắn thuộc ngăn nào; người quyết định. Không có
   gì tự vào trí nhớ. Gọi mạng: chỉ Shell.api.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  "use strict";

  const JSON_HEADERS = { "Content-Type": "application/json" };
  const NAMES = { fact: "Sự thật", decision: "Quyết định", joke: "Câu đùa", ignore: "Bỏ qua" };
  const TABS = [["pending", "Chờ duyệt"], ["joke", "Câu đùa"], ["fact", "Sự thật"], ["decision", "Quyết định"]];
  let V = null;

  const live = (v) => Boolean(v) && V === v && !v.ctx.signal.aborted;

  async function act(v, row, action, label) {
    try {
      await Shell.api(`/api/message-labels/${encodeURIComponent(row.id)}/${action}`, {
        method: "POST", headers: JSON_HEADERS, body: JSON.stringify(label ? { label } : {}), signal: v.ctx.signal,
      });
    } catch (error) {
      if (live(v) && error.name !== "AbortError") toast(error.message || "Không lưu được.", "danger");
      return;
    }
    if (live(v)) load(v);
  }

  function card(v, row) {
    const percent = `${Math.round(Number(row.confidence) * 100)}%`;
    const reviewing = row.status === "pending";
    const buttons = reviewing
      ? Object.keys(NAMES).map((key) => h("button", {
        type: "button", class: ["btn", "btn-30", key === row.suggested_label ? "btn-primary" : "btn-outline"],
        onClick: () => (key === "ignore" ? act(v, row, "reject") : act(v, row, "approve", key)),
      }, NAMES[key]))
      : [h("button", { type: "button", class: "btn btn-30 btn-outline", onClick: () => act(v, row, "reopen") }, "Bỏ duyệt")];
    return h("section", { class: "card card-p lbl-card" },
      h("div", { class: "lbl-text" }, row.text),
      h("div", { class: "lbl-meta" }, `${row.author} · decided đề xuất: ${NAMES[row.suggested_label] || row.suggested_label} (${percent})${row.stable ? "" : " · chưa chắc: đổi đáp án khi đảo lựa chọn"}`),
      h("div", { class: "lbl-actions" }, buttons));
  }

  function statsLine(stats) {
    const status = (stats && stats.status) || {};
    const reviewed = Object.values((stats && stats.agreement) || {});
    const total = reviewed.reduce((sum, item) => sum + item.reviewed, 0);
    const agreed = reviewed.reduce((sum, item) => sum + item.agreed, 0);
    const agreement = total ? `Bạn đồng ý với decided ${agreed}/${total} lần.` : "Chưa duyệt câu nào.";
    return `Chờ duyệt ${status.pending || 0} · đã duyệt ${status.approved || 0} · đã bỏ ${status.rejected || 0} · decided tự bỏ qua ${status.skipped || 0}. ${agreement}`;
  }

  async function load(v) {
    if (!live(v)) return;
    const path = v.tab === "pending" ? "/api/message-labels?limit=100" : `/api/message-labels/approved?label=${v.tab}`;
    let rows;
    let stats;
    try {
      [rows, stats] = await Promise.all([Shell.api(path, { signal: v.ctx.signal }), Shell.api("/api/message-labels/stats", { signal: v.ctx.signal })]);
    } catch (error) {
      if (live(v) && error.name !== "AbortError") v.body.replaceChildren(errorState(error, () => load(v)));
      return;
    }
    if (!live(v)) return;
    v.stats.textContent = statsLine(stats);
    v.tabs.replaceChildren(...TABS.map(([key, name]) => h("button", {
      type: "button", class: ["btn", "btn-30", key === v.tab ? "btn-primary" : "btn-outline"],
      onClick: () => { v.tab = key; load(v); },
    }, name)));
    v.body.replaceChildren(rows.length
      ? h("div", null, rows.map((row) => card(v, row)))
      : emptyState({ icon: "check", title: "Không có gì ở đây.", text: "Tin mới trong kênh đang nghe sẽ được decided đề xuất và hiện ở đây." }));
  }

  function mount(ctx) {
    ctx.setHeader("Duyệt phân loại", "Decided đề xuất, bạn quyết định. Không có gì tự vào trí nhớ.");
    const stats = h("div", { class: "lbl-stats", role: "status" }, "Đang tải…");
    const tabs = h("div", { class: "lbl-tabs" });
    const body = h("div");
    ctx.root.append(h("div", { class: "page" }, h("div", { class: "page-inner w-1080" }, stats, tabs, body)));
    V = { ctx, stats, tabs, body, tab: "pending" };
    load(V);
  }

  function unmount() {
    V = null;
  }

  Router.register("labels", { admin: true, mount, unmount });
})();
