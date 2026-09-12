// 小程序开发者文档(docs/miniapp/*.md)→ 官网 /developers 的页面数据(DEV-PROMPTS-39 #333)。
//
// **构建时**转换:浏览器里不带 Markdown 解析器,拿到的是转好的 HTML 和标题目录。
// 文档源头仍然是仓库里的 Markdown,和代码一起评审、一起留痕。
//
// 只实现这些文档真用到的语法:# 到 ####、段落、**粗体**、`代码`、[链接](…)、
// - / 1. 列表(续行缩进)、> 引用、| 表格 |、``` 围栏代码 ```。
// **不透传任何原始 HTML** —— 文档里写的 <script> 一律按文字转义。
//
// 锚点的 slug() 也给 scripts/check_sdk_docs.mjs 的站内链接检查用:两边同一个函数,
// 检查过的锚点就是页面上真有的 id。这个文件只能用 node 内置模块(检查脚本不装 web 的依赖)。
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

export const REPO = 'https://github.com/hanpaopao66/chaojizan'
export const DOCS_DIR = 'docs/miniapp'

/** 标题 → 锚点:小写,去掉 ` 和 *,只留字母(含汉字)、数字、空白和 -,空白换成 - */
export const slug = (h) => h.trim().toLowerCase().replace(/[`*]/g, '')
  .replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s+/g, '-')

/** README.md 是概览页;其余按文件名 */
export const pageSlug = (file) => (file === 'README.md' ? 'overview' : file.replace(/\.md$/, ''))

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

// 中文和中文之间的软换行不能变成空格(「平台托管、\n审核」会读成「托管、 审核」);
// 两边都是西文时才补一个空格
const CJKISH = /[—…　-〿㐀-鿿＀-￯]/
function joinLines(parts) {
  let out = ''
  for (const p of parts) {
    if (!out) { out = p; continue }
    out += (CJKISH.test(out[out.length - 1]) || CJKISH.test(p[0]) ? '' : ' ') + p
  }
  return out
}

// ---------------------------------------------------------------- 行内

/** 从 from 起找 needle,跳过 `代码` 里的 */
function findOutsideCode(s, needle, from) {
  for (let i = from; i < s.length; i++) {
    if (s[i] === '`') {
      const j = s.indexOf('`', i + 1)
      if (j < 0) return -1
      i = j
      continue
    }
    if (s.startsWith(needle, i)) return i
  }
  return -1
}

/** [文字](地址):文字里可以有 `代码` 和嵌套方括号 */
function matchLink(s, at) {
  let depth = 0
  for (let i = at; i < s.length; i++) {
    const c = s[i]
    if (c === '`') {
      const j = s.indexOf('`', i + 1)
      if (j < 0) return null
      i = j
    } else if (c === '[') depth++
    else if (c === ']' && --depth === 0) {
      if (s[i + 1] !== '(') return null
      const close = s.indexOf(')', i + 2)
      if (close < 0) return null
      const href = s.slice(i + 2, close).trim()
      if (!href || /\s/.test(href)) return null
      return { text: s.slice(at + 1, i), href, end: close + 1 }
    }
  }
  return null
}

/** 文档里的链接 → 官网上的地址。外链新窗口打开 */
export function mapHref(href) {
  if (/^https?:\/\//.test(href)) return { href, external: true }
  if (href.startsWith('#') || href.startsWith('/')) return { href, external: false }
  const m = /^([\w-]+\.md)(#.*)?$/.exec(href)
  if (m) return { href: `/developers/${pageSlug(m[1])}${m[2] || ''}`, external: false }
  // 其余相对路径(examples/verify.py 这类):指到开源仓里的那个文件
  return { href: `${REPO}/blob/main/${DOCS_DIR}/${href}`, external: true }
}

function inline(s) {
  let out = ''
  for (let i = 0; i < s.length;) {
    const c = s[i]
    if (c === '\\' && /[\\`*_[\]()#|<>!-]/.test(s[i + 1] || '')) {
      out += esc(s[i + 1])
      i += 2
      continue
    }
    if (c === '`') {
      const j = s.indexOf('`', i + 1)
      if (j > i) {
        out += `<code>${esc(s.slice(i + 1, j))}</code>`
        i = j + 1
        continue
      }
    }
    if (c === '*' && s[i + 1] === '*') {
      const j = findOutsideCode(s, '**', i + 2)
      if (j > i + 2) {
        out += `<strong>${inline(s.slice(i + 2, j))}</strong>`
        i = j + 2
        continue
      }
    }
    if (c === '[') {
      const m = matchLink(s, i)
      if (m) {
        const { href, external } = mapHref(m.href)
        const attrs = external ? ' target="_blank" rel="noreferrer"' : ''
        out += `<a href="${esc(href)}"${attrs}>${inline(m.text)}</a>`
        i = m.end
        continue
      }
    }
    out += esc(c)
    i++
  }
  return out
}

/** 行内标记 → 纯文字(目录、页面标题用) */
export const plain = (s) => s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\*\*|`/g, '')

// ---------------------------------------------------------------- 块

/** 表格一行 → 单元格。`代码` 里的 | 和 \| 不算分隔 */
function cells(line) {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1)
  const out = []
  let cur = ''
  for (let i = 0; i < s.length; i++) {
    const c = s[i]
    if (c === '\\' && s[i + 1] === '|') { cur += '|'; i++; continue }
    if (c === '`') {
      const j = s.indexOf('`', i + 1)
      if (j > i) { cur += s.slice(i, j + 1); i = j; continue }
    }
    if (c === '|') { out.push(cur.trim()); cur = ''; continue }
    cur += c
  }
  out.push(cur.trim())
  return out
}

const TABLE_RULE = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/
const LIST_ITEM = /^([-*]|\d+\.) +/

function codeBlock(code, lang) {
  const label = lang && lang !== 'text' ? `<span class="lang">${esc(lang)}</span>` : '<span class="lang"></span>'
  return `<div class="dv-code">${label}<button type="button" class="dv-copy">复制</button>`
    + `<pre><code>${esc(code)}</code></pre></div>`
}

function renderBlocks(lines, ctx) {
  let html = ''
  const para = []
  const flush = () => {
    if (para.length) html += `<p>${inline(joinLines(para))}</p>`
    para.length = 0
  }
  for (let i = 0; i < lines.length;) {
    const line = lines[i]
    let m
    if ((m = /^```([\w-]*)\s*$/.exec(line))) {
      flush()
      const buf = []
      for (i++; i < lines.length && !/^```\s*$/.test(lines[i]); i++) buf.push(lines[i])
      if (i >= lines.length) throw new Error(`${ctx.file}:代码块没有闭合`)
      i++
      html += codeBlock(buf.join('\n'), m[1])
      continue
    }
    if ((m = /^(#{1,4}) +(.+?)\s*$/.exec(line))) {
      flush()
      const level = m[1].length
      const raw = m[2]
      const base = slug(raw)
      // 同一页里重名的标题照 GitHub 的办法加 -1、-2
      const n = ctx.ids.get(base) || 0
      ctx.ids.set(base, n + 1)
      const id = n ? `${base}-${n}` : base
      const text = plain(raw)
      if (level === 1 && !ctx.title) ctx.title = text
      else ctx.headings.push({ level, id, text })
      html += `<h${level} id="${esc(id)}">${inline(raw)}`
        + (level > 1 ? `<a class="dv-anchor" href="#${esc(id)}" aria-label="这一节的链接"></a>` : '')
        + `</h${level}>`
      i++
      continue
    }
    if (line.startsWith('|') && TABLE_RULE.test(lines[i + 1] || '')) {
      flush()
      const head = cells(line)
      const align = cells(lines[i + 1]).map((c) => (c.endsWith(':') ? (c.startsWith(':') ? 'center' : 'right') : ''))
      const td = (tag, c, k) => `<${tag}${align[k] ? ` style="text-align:${align[k]}"` : ''}>${inline(c)}</${tag}>`
      let t = `<div class="dv-table"><table><thead><tr>${head.map((c, k) => td('th', c, k)).join('')}</tr></thead><tbody>`
      for (i += 2; i < lines.length && lines[i].startsWith('|'); i++) {
        t += `<tr>${cells(lines[i]).map((c, k) => td('td', c, k)).join('')}</tr>`
      }
      html += `${t}</tbody></table></div>`
      continue
    }
    if (/^>/.test(line)) {
      flush()
      const inner = []
      for (; i < lines.length && /^>/.test(lines[i]); i++) inner.push(lines[i].replace(/^> ?/, ''))
      html += `<blockquote>${renderBlocks(inner, ctx)}</blockquote>`
      continue
    }
    if (LIST_ITEM.test(line)) {
      flush()
      const ordered = /^\d/.test(line)
      const itemRe = ordered ? /^(\d+)\. +(.*)$/ : /^[-*] +(.*)$/
      const first = itemRe.exec(line)
      const items = []
      while (i < lines.length) {
        const l = lines[i]
        const mm = itemRe.exec(l)
        if (mm) { items.push([ordered ? mm[2] : mm[1]]); i++; continue }
        if (/^\s+\S/.test(l) && items.length) { items[items.length - 1].push(l.trim()); i++; continue }
        if (!l.trim()) {
          // 空行后面紧跟同类条目:还是这一个列表
          let k = i + 1
          while (k < lines.length && !lines[k].trim()) k++
          if (k < lines.length && itemRe.test(lines[k])) { i = k; continue }
        }
        break
      }
      const tag = ordered ? 'ol' : 'ul'
      const start = ordered && first[1] !== '1' ? ` start="${Number(first[1])}"` : ''
      html += `<${tag}${start}>${items.map((p) => `<li>${inline(joinLines(p))}</li>`).join('')}</${tag}>`
      continue
    }
    if (!line.trim()) { flush(); i++; continue }
    para.push(line.trim())
    i++
  }
  flush()
  return html
}

/** 一页 Markdown → { title, html, headings } */
export function renderDoc(src, file = '') {
  const ctx = { file, ids: new Map(), headings: [], title: '' }
  const html = renderBlocks(src.replace(/\r\n/g, '\n').split('\n'), ctx)
  return { title: ctx.title, html, headings: ctx.headings }
}

/** README 的「目录」列表 → 页面顺序、侧栏名称、一句话说明 */
export function readToc(readme) {
  const out = []
  for (const line of readme.split('\n')) {
    const m = /^\d+\. \[([^\]]+)\]\(([\w-]+\.md)\)(.*)$/.exec(line.trim())
    if (m) out.push({ file: m[2], label: plain(m[1]), desc: m[3].replace(/^\s*——\s*/, '').trim() })
  }
  return out
}

/** 全部页面,按 README 目录的顺序;README 自己是第一页「概览」 */
export function loadDocs(root) {
  const dir = join(root, DOCS_DIR)
  const files = readdirSync(dir).filter((f) => f.endsWith('.md'))
  const read = (f) => readFileSync(join(dir, f), 'utf8')
  const toc = readToc(read('README.md'))
  const order = [{ file: 'README.md', label: '概览', desc: '平台是什么、原则、能做与不能做、费用' }, ...toc]
  // 目录里漏了的页也照样出(排在最后);漏没漏由 check_sdk_docs.mjs 拦
  for (const f of files.sort()) if (!order.some((o) => o.file === f)) order.push({ file: f, label: f, desc: '' })
  return order.filter((o) => files.includes(o.file)).map((o) => {
    const doc = renderDoc(read(o.file), o.file)
    return { slug: pageSlug(o.file), file: o.file, label: o.label, desc: o.desc, ...doc }
  })
}

/** vite 插件:`import docs from 'virtual:miniapp-docs'` */
export function miniappDocs(root) {
  const id = 'virtual:miniapp-docs'
  const resolved = `\0${id}`
  const dir = join(root, DOCS_DIR)
  return {
    name: 'superz-miniapp-docs',
    resolveId: (x) => (x === id ? resolved : null),
    load(x) {
      if (x !== resolved) return null
      const docs = loadDocs(root)
      for (const d of docs) this.addWatchFile(join(dir, d.file))
      return `export default ${JSON.stringify(docs)}`
    },
    handleHotUpdate({ file, server }) {
      if (!file.startsWith(dir) || !file.endsWith('.md')) return undefined
      const mod = server.moduleGraph.getModuleById(resolved)
      if (mod) server.moduleGraph.invalidateModule(mod)
      server.ws.send({ type: 'full-reload' })
      return []
    },
  }
}
