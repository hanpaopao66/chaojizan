// 网页见证(server/static/nodes.html)的核账算法,按四个见证实现共用的用例跑一遍:
// witness/testdata/verify_rows_cases.json(Python / Go / App 跑的是同一份)。
//
// 不另抄一份算法来测 —— 抄的会分叉。nodes.html 里 witness-verify:start 到
// witness-verify:end 那一段原样截出来执行;标记丢了、截出来的跑不起来,都算失败。
//
// 零依赖:node scripts/test_witness_web.mjs(make unit 里跑)
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(root, 'server/static/nodes.html'), 'utf8');
const block = html.match(
  /\/\* witness-verify:start[\s\S]*?\*\/([\s\S]*?)\/\* witness-verify:end \*\//);
if (!block) {
  console.error('✗ nodes.html 里找不到 witness-verify:start … witness-verify:end 那一段');
  process.exit(1);
}
const web = new Function(`${block[1]}\nreturn { canonical, sha256, verifyRows };`)();
const doc = JSON.parse(
  readFileSync(join(root, 'witness/testdata/verify_rows_cases.json'), 'utf8'));
if (!doc.cases?.length || !doc.hash_vectors?.length) {
  console.error('✗ 共用用例是空的');
  process.exit(1);
}

// 问题的种类:问题文本第一个空格前的那个词(合计类的问题整句没有空格,就是整句)
const tagOf = (p) => p.split(' ')[0];
let failed = 0;
for (const c of doc.cases) {
  const problems = web.verifyRows(c.payload);
  const got = JSON.stringify(problems.map(tagOf).sort());
  const want = JSON.stringify([...c.expect].sort());
  if (got !== want) {
    failed++;
    console.error(`✗ ${c.name}\n  报出 ${got}\n  应为 ${want}\n  原文 ${problems.join(' | ')}`);
  }
}
for (const v of doc.hash_vectors) {
  const canon = web.canonical(v.payload);
  const ph = await web.sha256(canon);
  const ch = await web.sha256(v.prev + ph);
  if (canon !== v.canonical || ph !== v.payload_hash || ch !== v.chain_hash) {
    failed++;
    console.error(`✗ 哈希向量 ${v.name} 对不上(payload_hash ${ph},chain_hash ${ch})`);
  }
}
if (failed) {
  console.error(`网页见证:${failed} 条没过`);
  process.exit(1);
}
console.log(`== 网页见证核账 ✓(${doc.cases.length} 条共用用例 + ${doc.hash_vectors.length} 组哈希向量)`);
