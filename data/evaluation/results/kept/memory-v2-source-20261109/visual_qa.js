const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = process.argv[2] || require('path').join(process.cwd(), 'data/evaluation/results/kept/memory-v2-source-20261109/pipeline.html');
const html = fs.readFileSync(path, 'utf8');
assert(html.length < 1000000);
assert(!/<!doctype|<html|<head|<body|fetch\(|XMLHttpRequest|WebSocket/.test(html));
const nodes = {};
for (const match of html.matchAll(/id="([^"]+)"/g)) nodes[match[1]] = {
  children: [], attrs: {}, replaceChildren(...args) { this.children = args; },
  setAttribute(k, v) { this.attrs[k] = v; }, querySelector(id) { return nodes[id.slice(1)]; }
};
const listeners = {}, states = [];
const window = {openai: {setWidgetState(state) {states.push(state); return Promise.resolve();}},
  addEventListener(name, callback) {listeners[name] = callback;}};
vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], {document: {
  getElementById(id) {assert(nodes[id]); return nodes[id];},
  createElement() {return {attrs:{},setAttribute(k,v){this.attrs[k]=v;}};}
}, window});
assert.equal(states.length, 0);
for(let i=0;i<6;i++) {
  nodes['source-memory-case'].value = String(i);
  nodes['source-memory-case'].onchange();
  for(let j=0;j<6;j++) {
    assert.equal(nodes['source-memory-position'].textContent, `${j+1} / 6`);
    assert(nodes['source-memory-data'].textContent.length > 10);
    assert.equal(nodes['source-memory-path'].children[j].attrs['aria-current'], 'step');
    assert.equal(nodes['source-memory-path'].children.length, 6);
    if(j<5) nodes['source-memory-next'].onclick();
  }
  assert(nodes['source-memory-next'].disabled);
  nodes['source-memory-prev'].onclick();
  assert.equal(nodes['source-memory-position'].textContent, '5 / 6');
}
listeners['openai:set_globals']({detail:{globals:{widgetState:{privateContent:{selected:0,step:2}}}}});
assert.equal(nodes['source-memory-position'].textContent, '3 / 6');
assert.equal(nodes['source-memory-case'].value, '0');
console.log('PASS: 36 scenario states, previous/next, active stage and state restore. DOM logic only; no browser layout claim.');
