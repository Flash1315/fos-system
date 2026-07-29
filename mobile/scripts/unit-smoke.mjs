import assert from "node:assert/strict";

// Keep these dependency-free copies in sync with src/format.ts and src/listUtil.ts.
function asUtcInput(iso) {
  const s = iso.trim();
  if (/Z$/i.test(s) || /[+-]\d{2}:\d{2}$/.test(s) || /[+-]\d{4}$/.test(s)) {
    return s;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  return s + "Z";
}

function mergeById(prev, more) {
  if (!more.length) return prev;
  const seen = new Set(prev.map((row) => row.id));
  const extra = more.filter((row) => !seen.has(row.id));
  return extra.length ? [...prev, ...extra] : prev;
}

assert.equal(asUtcInput("2026-07-28T15:00:00"), "2026-07-28T15:00:00Z");
assert.equal(asUtcInput("2026-07-28T15:00:00+03:00"), "2026-07-28T15:00:00+03:00");
assert.equal(asUtcInput("2026-07-28"), "2026-07-28");

const firstPage = [{ id: 1, label: "one" }, { id: 2, label: "two" }];
assert.deepEqual(
  mergeById(firstPage, [{ id: 2, label: "duplicate" }, { id: 3, label: "three" }]),
  [{ id: 1, label: "one" }, { id: 2, label: "two" }, { id: 3, label: "three" }],
);
assert.equal(mergeById(firstPage, []), firstPage);
assert.equal(mergeById(firstPage, [{ id: 2, label: "duplicate" }]), firstPage);

console.log("mobile unit smoke ok");
// non-finite money
function formatMoneySmoke(amount, currency) {
  if (!Number.isFinite(amount)) return `— ${currency}`;
  return `${amount.toFixed(2)} ${currency}`;
}
if (formatMoneySmoke(Number.NaN, 'IDR') !== '— IDR') throw new Error('NaN money');
if (formatMoneySmoke(1, 'IDR') !== '1.00 IDR') throw new Error('finite money');
// fresher merge
function mergeByIdSmoke(prev, more) {
  const byId = new Map(); const order = [];
  for (const r of prev) { byId.set(r.id, r); order.push(r.id); }
  for (const r of more) { if (!byId.has(r.id)) order.push(r.id); byId.set(r.id, r); }
  return order.map((id) => byId.get(id));
}
const merged = mergeByIdSmoke([{id:1,v:1}], [{id:1,v:2}]);
if (merged[0].v !== 2) throw new Error('fresher merge');

