#!/usr/bin/env node
// 小程序文档的三道自动检查(DEV-PROMPTS-39 #323 #333):
//
// 1. SDK 参考页(docs/miniapp/sdk-reference.md)的方法清单和 SDK 真正导出的东西**一一对上** ——
//    SDK 加了方法没写文档、文档写了 SDK 没有的方法,都红;
// 2. 服务端文档里贴的 Python / Node 验签代码和 docs/miniapp/examples/ 下被测试跑过的文件**一字不差**,
//    并且 Node 那份现场拿测试向量跑一遍(Python 那份由 server/tests/unit/test_miniapp_docs_examples.py 跑);
// 3. 文档之间的站内链接(xxx.md、xxx.md#锚点)都指得到;每一页都在 README 的目录里
//    (官网 /developers 的侧栏按那个目录排),官网上转出来的 /developers/… 链接也都指得到。
//
// 锚点的算法和官网转换共用 web/scripts/miniapp-docs.mjs 的 slug() —— 检查过的锚点就是页面上的 id。
// 先要有 SDK 的构建产物:cd packages/miniapp-sdk && npm test(会先 build)。
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { loadDocs, readToc, slug } from '../web/scripts/miniapp-docs.mjs'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const docs = join(root, 'docs/miniapp')
const problems = []

// ---------------------------------------------------------------- 1. SDK ⇄ 参考页

const dist = join(root, 'packages/miniapp-sdk/dist/sz-webapp.mjs')
if (!existsSync(dist)) {
  console.error('缺 SDK 构建产物,先跑 cd packages/miniapp-sdk && npm test')
  process.exit(1)
}
const { WebApp } = await import(pathToFileURL(dist).href)

const exported = new Set()
const GROUPS = { MainButton: 'MainButton', SecondaryButton: 'MainButton', BackButton: 'BackButton', SettingsButton: 'BackButton', HapticFeedback: 'HapticFeedback', CloudStorage: 'CloudStorage' }
for (const key of Object.keys(WebApp)) {
  exported.add(key)
  const group = GROUPS[key]
  if (!group || group !== key) continue // SecondaryButton / SettingsButton 的方法和兄弟共用一节文档
  const obj = WebApp[key]
  const proto = Object.getPrototypeOf(obj)
  const names = new Set([...Object.keys(obj), ...(proto === Object.prototype ? [] : Object.getOwnPropertyNames(proto))])
  for (const n of names) {
    if (n === 'constructor' || n.startsWith('_') || typeof obj[n] !== 'function') continue
    exported.add(`${key}.${n}`)
  }
}

const ref = readFileSync(join(docs, 'sdk-reference.md'), 'utf8')
const documented = new Set()
for (const line of ref.split('\n')) {
  const m = /^### ([A-Za-z][\w.]*)/.exec(line)
  if (m) documented.add(m[1])
}
for (const n of exported) if (!documented.has(n)) problems.push(`SDK 导出了 ${n},sdk-reference.md 里没有「### ${n}」`)
for (const n of documented) if (!exported.has(n)) problems.push(`sdk-reference.md 写了「### ${n}」,SDK 里没有`)

// ---------------------------------------------------------------- 2. 验签示例

const server = readFileSync(join(docs, 'server.md'), 'utf8')
for (const [file, lang] of [['verify.py', 'python'], ['verify.mjs', 'js']]) {
  const code = readFileSync(join(docs, 'examples', file), 'utf8')
  if (!server.includes('```' + lang + '\n' + code + '```')) {
    problems.push(`server.md 里的 ${lang} 验签代码和 examples/${file} 不一致(文档示例必须是跑过测试的那份)`)
  }
}
const VECTOR = 'app_id=sz0123456789abcdef&auth_date=1790000000&launch_id=AAAAAAAAAAAAAAAAAAAAAA&sig_kid=56475aa7' +
  '&start_param=note42&user=%7B%22language_code%22%3A%22zh-CN%22%2C%22open_id%22%3A%22o_testvectoropenid000000000%22%7D' +
  '&hash=797f9baf84dafc57c34179e83285670329947fc09314d2093bec14d1a975515a' +
  '&signature=Yd_TNpAvseblIJL5TPzdFhcduSLDXZJnqYovzx8nFNNH3UGqHp-sxmmJRiK6wvdS57vdAo7hEdGmzE621rQICQ'
if (!server.includes(VECTOR)) problems.push('server.md 里的测试向量和平台单测里的不一致')
const node = await import(pathToFileURL(join(docs, 'examples/verify.mjs')).href)
const APP = 'sz0123456789abcdef'
const SECRET = 'SuperZTestVectorAppSecret0123456789abcdefgh'
const PUB = 'A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg'
const T = 1790000005
if (!node.verifyHash(VECTOR, APP, SECRET, T)) problems.push('Node 示例:测试向量的 hash 验不过')
if (!node.verifySignature(VECTOR, APP, PUB, T)) problems.push('Node 示例:测试向量的 signature 验不过')
if (node.verifyHash(VECTOR.replace('note42', 'note43'), APP, SECRET, T)) problems.push('Node 示例:改过的包 hash 竟然验过了')
if (node.verifySignature(VECTOR, 'sz0000000000000000', PUB, T)) problems.push('Node 示例:app_id 不符竟然验过了')
if (node.verifyHash(VECTOR, APP, SECRET, 1790000601)) problems.push('Node 示例:过期的包竟然验过了')

// ---------------------------------------------------------------- 3. 站内链接

const anchors = {}
const files = readdirSync(docs).filter((f) => f.endsWith('.md'))
for (const f of files) {
  anchors[f] = new Set(readFileSync(join(docs, f), 'utf8').split('\n')
    .filter((l) => /^#{1,4} /.test(l)).map((l) => slug(l.replace(/^#+ /, ''))))
}
for (const f of files) {
  const text = readFileSync(join(docs, f), 'utf8')
  for (const m of text.matchAll(/\]\(([\w-]+\.md)(#[^)]+)?\)/g)) {
    const [, target, hash] = m
    if (!anchors[target]) problems.push(`${f}:链接到不存在的 ${target}`)
    else if (hash && !anchors[target].has(decodeURIComponent(hash.slice(1)))) {
      problems.push(`${f}:${target}${hash} 找不到这个标题`)
    }
  }
}
const listed = new Set(readToc(readFileSync(join(docs, 'README.md'), 'utf8')).map((t) => t.file))
for (const f of files) {
  if (f !== 'README.md' && !listed.has(f)) problems.push(`${f} 不在 README.md 的目录里(官网侧栏按那个目录排)`)
}

// 官网上转出来的页面:/developers/<页>#<锚点> 都要指得到(rules 是官网自己的规则页)
const site = loadDocs(root)
const pages = new Map(site.map((d) => [d.slug, new Set(d.headings.map((h) => h.id).concat(slug(d.title)))]))
for (const d of site) {
  for (const m of d.html.matchAll(/href="\/developers\/([\w-]+)(#[^"]*)?"/g)) {
    const [, page, hash] = m
    if (page === 'rules') continue
    if (!pages.has(page)) problems.push(`官网 ${d.slug} 页:链接到不存在的 /developers/${page}`)
    else if (hash && !pages.get(page).has(hash.slice(1))) problems.push(`官网 ${d.slug} 页:/developers/${page}${hash} 找不到这个标题`)
  }
}

if (problems.length) {
  console.error('✗ 小程序文档检查没过:\n  - ' + problems.join('\n  - '))
  process.exit(1)
}
console.log(`✓ 小程序文档:SDK ${exported.size} 项与参考页一致,验签示例跑过测试向量,${files.length} 页站内链接都指得到`)
