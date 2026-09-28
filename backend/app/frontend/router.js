/* ══════════════════════════════════════════════════════════════════
   /ui/router.js — hash router (global duy nhất: Router).

   Route: #/<tên>[/<tham số>…][?query]
     #/chat  #/chat/<id>  #/documents?doc=<id>  #/memory?tab=…  #/dashboard
     #/ocr?job=<id>  #/bot  #/models  #/users  #/settings  #/chunks/<documentId>
   '', '#', '#/' và route lạ → #/chat (replaceState, không thêm lịch sử).
   Link cũ #c=<id> → #/chat/<id> (replaceState). Nghe hashchange (sửa D2).

   Router.register(name, {admin, mount(ctx), update(ctx, {same, signal}), unmount(ctx)})
   ctx = {root, name, params, query, signal, every, after, on, setHeader, setActions}
   Rời view: signal abort, mọi every/after/on tự gỡ, unmount() được gọi, root bị tháo.
   Gọi every/after/on trên ctx đã rời (tiếp nối async của mount) = không làm gì.
   Lỗi trong mount (kể cả Promise bị reject) → errorState + "Thử lại", không để trang trắng.
   update() chỉ chạy khi mount() đã xong (mount async còn dở → mount lại); info.signal
   abort khi có lần định tuyến mới, để update chậm biết kết quả của mình đã cũ.
   Mỗi lần đổi route phát sự kiện window "lac:route" (detail = Router.current).
   Router.pause()/resume(): Shell gọi quanh màn đăng nhập — lúc dừng, hashchange bị bỏ
   qua, every() của view không chạy, after() dồn lại tới khi chạy tiếp.
   ══════════════════════════════════════════════════════════════════ */
"use strict";

const Router = (() => {
  const routes = new Map();
  let started = false;
  let paused = false;
  let remountOnResume = false;
  let current = null;   // {name, params, query (chuỗi), hash}
  let active = null;    // {name, def, ctx, controller, cleanups, pending, updateController}
  let seq = 0;
  const deferred = new Set();   // after() đến hạn lúc đang dừng → chạy ở resume()

  const HOME = "#/chat";

  function decode(part) {
    try { return decodeURIComponent(part); } catch { return part; }
  }

  function parse(hash) {
    const raw = hash.startsWith("#") ? hash.slice(1) : hash;
    const body = raw.startsWith("/") ? raw.slice(1) : raw;
    const qAt = body.indexOf("?");
    const path = qAt === -1 ? body : body.slice(0, qAt);
    const query = qAt === -1 ? "" : body.slice(qAt + 1);
    const segments = path.split("/").filter(Boolean);
    return { name: segments[0] ? decode(segments[0]) : "", params: segments.slice(1).map(decode), query };
  }

  function normalize(target) {
    let hash = String(target ?? "").trim();
    if (!hash.startsWith("#")) hash = hash.startsWith("/") ? `#${hash}` : `#/${hash}`;
    // "#documents" → "#/documents"; giữ nguyên "#", "#/…" và link cũ "#c=…"
    else if (hash.length > 1 && !hash.startsWith("#/") && !hash.startsWith("#c=")) hash = `#/${hash.slice(1)}`;
    return hash;
  }

  /* Hash đúng như trình duyệt sẽ ghi (khoảng trắng → %20…), để so với location.hash. */
  function resolved(hash) {
    try { return new URL(hash, location.href).hash; } catch { return hash; }
  }

  /* Đưa hash hiện tại về dạng hợp lệ. Trả về hash cần replaceState, hoặc null nếu giữ nguyên. */
  function canonical(hash) {
    if (hash === "" || hash === "#" || hash === "#/") return HOME;
    const legacy = /^#c=(.*)$/.exec(hash);
    if (legacy) {
      let id = null;
      try { id = decodeURIComponent(legacy[1]); } catch { id = null; }
      return id ? `#/chat/${encodeURIComponent(id)}` : HOME;
    }
    /* "#settings" (gõ tay, hoặc link cũ thiếu dấu /) → "#/settings" nếu đó là một route
       có thật; còn lại mới về HOME. Router.go() cũng chuẩn hóa như vậy. */
    if (!hash.startsWith("#/")) {
      const body = hash.slice(1);
      const first = decode(body.split(/[/?]/)[0] || "");
      return first && routes.has(first) ? `#/${body}` : HOME;
    }
    return null;
  }

  function replaceHash(hash) {
    history.replaceState(history.state, "", `${location.pathname}${location.search}${hash}`);
  }

  function shell() {
    return typeof Shell !== "undefined" ? Shell : null;
  }

  function isAdmin() {
    const s = shell();
    return s && typeof s.isAdmin === "function" ? s.isAdmin() : true;
  }

  function makeCtx(route, def, controller, cleanups, root) {
    // ctx đã rời màn hình: đăng ký mới không được sống sót (trước đây lọt vào mảng cleanups đã dọn).
    const dead = () => controller.signal.aborted;
    const ctx = {
      root,
      name: route.name,
      params: route.params.slice(),
      query: new URLSearchParams(route.query),
      signal: controller.signal,
      every(fn, ms) {
        if (dead()) return () => {};
        const id = setInterval(() => { if (!paused) guard(fn, route.name); }, ms);
        const stop = () => clearInterval(id);
        cleanups.push(stop);
        return stop;
      },
      after(fn, ms) {
        if (dead()) return () => {};
        let done = false;
        const run = () => {
          if (done || dead()) return;
          if (paused) { deferred.add(run); return; }
          done = true;
          guard(fn, route.name);
        };
        const id = setTimeout(run, ms);
        const stop = () => { done = true; clearTimeout(id); deferred.delete(run); };
        cleanups.push(stop);
        return stop;
      },
      on(target, type, fn, opts) {
        if (dead() || !target || typeof target.addEventListener !== "function") return () => {};
        target.addEventListener(type, fn, opts);
        const capture = typeof opts === "boolean" ? opts : Boolean(opts && opts.capture);
        const off = () => target.removeEventListener(type, fn, capture);
        cleanups.push(off);
        return off;
      },
      setHeader(title, sub) {
        if (isLive(ctx)) shell()?.setHeader(title, sub);
      },
      setActions(nodes) {
        if (isLive(ctx)) shell()?.setHeaderActions(nodes);
      },
    };
    return ctx;
  }

  /* Hàm của every/after: lỗi (kể cả Promise reject) chỉ ghi console, không làm treo view. */
  function guard(fn, name) {
    try {
      const out = fn();
      if (out && typeof out.catch === "function") out.catch((error) => report(error, name));
    } catch (error) {
      report(error, name);
    }
  }

  function report(error, name) {
    if (error && error.name === "AbortError") return;
    console.error(`[router] view "${name}":`, error);
  }

  function isLive(ctx) {
    return Boolean(active && active.ctx === ctx);
  }

  function teardown() {
    if (!active) return;
    const { def, ctx, controller, cleanups, updateController } = active;
    active = null;
    try { controller.abort(); } catch { /* ignore */ }
    if (updateController) {
      try { updateController.abort(); } catch { /* ignore */ }
    }
    for (const stop of cleanups.splice(0)) {
      try { stop(); } catch (error) { console.error(error); }
    }
    if (typeof def.unmount === "function") {
      try { def.unmount(ctx); } catch (error) { report(error, ctx.name); }
    }
    ctx.root.remove();
  }

  function renderFailure(ctx, error) {
    if (!isLive(ctx)) return;
    if (error && error.name === "AbortError" && ctx.signal.aborted) return;
    report(error, ctx.name);
    ctx.root.replaceChildren(h("div", { class: "page" },
      h("div", { class: "page-inner w-800" }, errorState(error, () => handle({ force: true })))));
  }

  function mount(route, def) {
    teardown();
    const viewEl = document.getElementById("view");
    viewEl.replaceChildren();
    const s = shell();
    if (s) {
      s.setHeader("", "");
      s.setHeaderActions([]);
      s._beginMount?.();
    }
    const controller = new AbortController();
    const cleanups = [];
    const root = h("div", { class: "view-root", dataset: { view: route.name } });
    viewEl.append(root);
    const ctx = makeCtx(route, def, controller, cleanups, root);
    const rec = { name: route.name, def, ctx, controller, cleanups, pending: false, updateController: null };
    active = rec;
    try {
      const out = def.mount(ctx);
      if (out && typeof out.then === "function") {
        // mount async còn dở thì không gọi update() chồng lên (xem handle)
        rec.pending = true;
        out.then(() => { rec.pending = false; }, (error) => { rec.pending = false; renderFailure(ctx, error); });
      }
    } catch (error) {
      renderFailure(ctx, error);
    }
    s?._endMount?.();
  }

  /* Route lạ / thành viên vào route admin → #/chat. Nếu Chat đang là view trên màn hình thì
     chỉ trả lại hash của nó, không chạy lại route (không cắt luồng trả lời, không mất chữ đang gõ). */
  function redirectHome(force) {
    const home = parse(HOME).name;
    if (!force && active && active.name === home && current && current.name === home) {
      replaceHash(current.hash);
      return undefined;
    }
    replaceHash(HOME);
    return handle({ force });
  }

  async function handle({ force = false } = {}) {
    if (paused) return;
    const my = ++seq;
    if (active && active.updateController) {
      active.updateController.abort();
      active.updateController = null;
    }
    const fixed = canonical(location.hash);
    if (fixed) replaceHash(fixed);
    const hash = location.hash;
    const route = parse(hash);
    const def = routes.get(route.name);
    if (!def) {
      if (parse(HOME).name === route.name || !routes.has(parse(HOME).name)) {
        // Không có cả màn hình mặc định (script view không nạp được): báo lỗi thay vì lặp vô hạn.
        teardown();
        current = { name: route.name, params: route.params, query: route.query, hash };
        document.getElementById("view").replaceChildren(h("div", { class: "page" },
          h("div", { class: "page-inner w-800" }, errorState(new Error(`Không nạp được màn hình "${route.name || "chat"}". Tải lại trang để thử lại.`)))));
        return;
      }
      if (route.name) console.warn(`[router] không có route "${route.name}" → ${HOME}`);
      return redirectHome(force);
    }
    if (def.admin && !isAdmin()) {
      toast("Chỉ quản trị viên xem được trang này.", "danger");
      return redirectHome(force);
    }

    const previous = current;
    current = { name: route.name, params: route.params, query: route.query, hash };
    window.dispatchEvent(new CustomEvent("lac:route", { detail: Router.current }));

    if (!force && active && active.name === route.name && typeof def.update === "function" && !active.pending) {
      const rec = active;
      const sameState = Boolean(previous && previous.hash === hash);
      const updateController = new AbortController();
      rec.updateController = updateController;
      rec.ctx.params = route.params.slice();
      rec.ctx.query = new URLSearchParams(route.query);
      let handled = false;
      try {
        handled = await def.update(rec.ctx, { same: sameState, signal: updateController.signal });
      } catch (error) {
        report(error, route.name);
        handled = false;
      }
      if (rec.updateController === updateController) rec.updateController = null;
      if (my !== seq) return;
      if (handled) return;
    }
    if (my !== seq) return;
    // Chỉ tới đây khi đã qua một await: nếu vừa bị pause() thì để resume() mount lại.
    if (paused) { remountOnResume = true; return; }
    mount(route, def);
  }

  return {
    /* Đăng ký một view. def = {admin?, mount(ctx), update?(ctx, {same, signal}) → bool, unmount?(ctx)}. */
    register(name, def) {
      if (!name || !def || typeof def.mount !== "function") throw new Error(`Router.register("${name}"): thiếu mount()`);
      if (routes.has(name)) console.warn(`[router] route "${name}" bị đăng ký lại`);
      routes.set(name, def);
    },
    /* Gọi một lần sau khi Shell biết vai trò người dùng. */
    start() {
      if (started) { handle(); return; }
      started = true;
      window.addEventListener("hashchange", () => {
        // Nhiều hashchange dồn lại cho CÙNG hash đang hiển thị (gán location.hash liên tiếp) → bỏ qua.
        if (active && current && location.hash === current.hash) return;
        handle();
      });
      handle();
    },
    /* Điều hướng có lịch sử. Cùng hash hiện tại → chạy lại route (view.update quyết định). */
    go(target) {
      const hash = normalize(target);
      if (resolved(hash) === location.hash) handle();
      else location.hash = hash;
    },
    /* Điều hướng thay thế mục lịch sử hiện tại.
       {silent: true} (bổ sung 16/09 cho chat): view tự ghi lại URL của CHÍNH nó (vd. nhận id hội thoại
       giữa luồng trả lời) → chỉ đổi hash + Router.current + ctx.params, không update()/mount, không phát
       "lac:route" (shell không đóng sidebar di động). Hash thuộc route khác → như thường. */
    replace(target, { silent = false } = {}) {
      const hash = normalize(target);
      if (silent && started && !paused && active && current) {
        const route = parse(resolved(hash));
        if (route.name === active.name && !canonical(resolved(hash))) {
          replaceHash(hash);
          current = { name: route.name, params: route.params, query: route.query, hash: location.hash };
          active.ctx.params = route.params.slice();
          active.ctx.query = new URLSearchParams(route.query);
          return;
        }
      }
      replaceHash(hash);
      if (started) handle();
    },
    /* {name, params: string[], query: URLSearchParams, hash} của route đang hiển thị, hoặc null. */
    get current() {
      if (!current) return null;
      return { name: current.name, params: current.params.slice(), query: new URLSearchParams(current.query), hash: current.hash };
    },
    /* Mount lại view hiện tại (bỏ qua update). */
    reload() {
      if (started) handle({ force: true });
    },
    has(name) {
      return routes.has(name);
    },
    /* Màn đăng nhập hiện: dừng định tuyến. unmount=true (đăng xuất) → gỡ luôn view đang mở;
       mặc định giữ view (phiên hết hạn: không mất chữ đang gõ) nhưng every/after của nó ngừng. */
    pause({ unmount = false } = {}) {
      paused = true;
      if (unmount) {
        teardown();
        document.getElementById("view")?.replaceChildren();
      }
    },
    /* Đăng nhập lại: chạy tiếp. force, view đã bị gỡ, hoặc hash đổi trong lúc dừng → định tuyến lại. */
    resume({ force = false } = {}) {
      paused = false;
      if (!started) return;
      const late = [...deferred];
      deferred.clear();
      const again = force || remountOnResume;
      remountOnResume = false;
      if (again || !active || !current || location.hash !== current.hash) handle({ force: again });
      for (const run of late) run();
    },
    get paused() {
      return paused;
    },
  };
})();
