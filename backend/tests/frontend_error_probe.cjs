/* Real UI functions, fake fetch/DOM: no browser, service or model is started. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const [frontend, scenario] = process.argv.slice(2);
const context = vm.createContext({
  console,
  window: { matchMedia: () => ({ matches: false, addEventListener() {} }) },
  navigator: { platform: "Linux" },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  document: { documentElement: { dataset: {} }, createTextNode: (text) => String(text) },
});
const load = (file) => vm.runInContext(fs.readFileSync(path.join(frontend, file), "utf8"), context, { filename: file });
const evaluate = (code) => vm.runInContext(code, context);
load("common.js");
let requests = 0;
async function apiError(code, status, detail) {
  context.fetch = async () => {
    requests += 1;
    return { ok: false, status, json: async () => ({ error_code: code, message: "private server details", detail }) };
  };
  return await evaluate(`(async () => {
    try { await requestJson("/fake"); throw new Error("request should fail"); }
    catch (error) { return { message: error.message, code: error.code, status: error.status, errorId: error.errorId, retryable: error.retryable }; }
  })()`);
}

function nodes(tree) {
  return tree && typeof tree === "object" ? [tree, ...(tree.children || []).flatMap(nodes)] : [];
}
function text(tree) {
  return tree && typeof tree === "object" ? (tree.children || []).map(text).join(" ") : String(tree || "");
}
function hasRetry(tree) {
  return nodes(tree).some((node) => node.tag === "button" && text(node).includes("Thử lại"));
}

async function run() {
  if (scenario === "provider") {
    const error = await apiError("RESEARCH_PROVIDER_UNSUPPORTED", 409, null);
    assert.equal(requests, 1);
    assert.equal(error.code, "RESEARCH_PROVIDER_UNSUPPORTED");
    assert.equal(error.status, 409);
    assert.equal(error.retryable, false);
    assert.match(error.message, /Ollama/);
    assert.match(error.message, /tải lại trang/);
    assert.doesNotMatch(error.message, /private/);
  } else if (scenario === "index_receipt") {
    const receipt = "0123456789abcdef0123456789abcdef";
    const error = await apiError("DOCUMENT_INDEX_REQUEST_FAILED", 500, { error_id: receipt });
    assert.equal(error.errorId, receipt);
    assert.equal(error.retryable, false);
    assert.match(error.message, /Kiểm tra trạng thái/);
    assert.ok(error.message.includes(receipt));
    assert.doesNotMatch(error.message, /private/);
    const malformed = await apiError("DOCUMENT_INDEX_REQUEST_FAILED", 500, { error_id: "<script>untrusted</script>" });
    assert.equal(malformed.errorId, null);
    assert.doesNotMatch(malformed.message, /script|untrusted/);
    assert.equal(requests, 2);
  } else if (scenario === "retry_rendering") {
    load("components.js");
    // Use the actual errorState/emptyState and research builders, replacing
    // only DOM primitives with a tiny tree representation.
    evaluate(`
      globalThis.Node = class {
        constructor(tag, props, children) { this.tag = tag; this.props = props || {}; this.children = children.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false); this.classList = {add() {}}; }
        append(...children) { this.children.push(...children); }
        setAttribute(name, value) { this.props[name] = value; }
      };
      h = (tag, props, ...children) => new Node(tag, props, children);
      icon = (name) => h("svg", {name});
      globalThis.Router = {register() {}};
      globalThis.Shell = {api() { throw new Error("unexpected API call"); }};
    `);
    const marker = '  Router.register("research",';
    const research = fs.readFileSync(path.join(frontend, "views/research.js"), "utf8");
    assert.equal(research.split(marker).length, 2);
    vm.runInContext(research.replace(marker,
      '  globalThis.researchProbe = {S, detailOf, buildSummaryPanel, buildOverview, generateSummary, generateInsights};\n' + marker), context);
    evaluate(`
      globalThis.blocked = {code: "RESEARCH_PROVIDER_UNSUPPORTED", message: ERROR_HINTS.RESEARCH_PROVIDER_UNSUPPORTED};
      researchProbe.S.pid = "project";
      researchProbe.S.project = {name: "Project", papers: [], clusters: [], edges: []};
      researchProbe.S.insightsError = blocked;
      const detail = researchProbe.detailOf("paper");
      detail.data = {summary: null}; detail.sumError = blocked; detail.sumTried = true;
    `);
    assert.equal(hasRetry(evaluate("errorState(blocked, () => {})")), false);
    assert.equal(hasRetry(evaluate('errorState({code: "MODEL_TIMEOUT", message: "temporary"}, () => {})')), true);
    assert.equal(hasRetry(evaluate('researchProbe.buildSummaryPanel({id: "paper", indexed: true}).el')), false);
    assert.equal(hasRetry(evaluate("researchProbe.buildOverview()")), false);
    await evaluate('Promise.all([researchProbe.generateSummary("paper"), researchProbe.generateInsights()])');
    assert.equal(requests, 0);

    evaluate('researchProbe.S.project.insights = {overview: "Saved analysis"}; researchProbe.detailOf("paper").data.summary = {brief: "Saved summary"};');
    const overview = evaluate("researchProbe.buildOverview()");
    const summary = evaluate('researchProbe.buildSummaryPanel({id: "paper", indexed: true}).el');
    for (const [tree, label] of [[overview, "Phân tích lại"], [summary, "Tạo lại"]]) {
      assert.match(text(tree), /Ollama/);
      const button = nodes(tree).find((node) => node.tag === "button" && text(node) === label);
      assert.ok(button, label);
      assert.equal(button.props.disabled, true);
    }
  } else {
    throw new Error("unknown scenario");
  }
}
run().catch((error) => { console.error(error); process.exitCode = 1; });
