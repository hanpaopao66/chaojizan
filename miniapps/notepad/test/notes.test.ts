import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  MAX_CHARS, charCount, conflictCopyText, daysLeft, decode, encode, expired, highlight, newId,
  newNote, search, snippetOf, sortNotes, timeLabel, titleOf, tooLong, trashNotes,
} from '../src/notes'

const T = new Date(2026, 8, 12, 15, 30).getTime()
const DAY = 86400000

test('首行即标题,摘要是后面的正文压成一行', () => {
  const n = newNote('\n  周末采购  \n鸡蛋\n\n牛奶  面包')
  assert.equal(titleOf(n), '周末采购')
  assert.equal(snippetOf(n), '鸡蛋 牛奶 面包')
  assert.equal(titleOf(newNote('   ')), '无标题')
})

test('时间文案:今天 HH:mm / 昨天 / M月D日 / 跨年带年份', () => {
  assert.equal(timeLabel(new Date(2026, 8, 12, 9, 5).getTime(), T), '今天 09:05')
  assert.equal(timeLabel(new Date(2026, 8, 11, 23, 0).getTime(), T), '昨天')
  assert.equal(timeLabel(new Date(2026, 2, 3).getTime(), T), '3月3日')
  assert.equal(timeLabel(new Date(2025, 11, 31).getTime(), T), '2025年12月31日')
})

test('排序:置顶在前,其余按更新时间倒序;回收站里的不在列表', () => {
  const a = { ...newNote('a', T - 3 * DAY), updated_at: T - 3 * DAY }
  const b = { ...newNote('b', T - DAY), updated_at: T - DAY }
  const c = { ...newNote('c', T - 5 * DAY), pinned: true, updated_at: T - 5 * DAY }
  const d = { ...newNote('d', T), deleted_at: T }
  assert.deepEqual(sortNotes([a, b, c, d]).map((n) => n.text), ['c', 'b', 'a'])
  assert.deepEqual(trashNotes([a, d], T).map((n) => n.text), ['d'])
})

test('回收站保留 30 天', () => {
  const n = { ...newNote('x', T), deleted_at: T - 29 * DAY }
  assert.equal(expired(n, T), false)
  assert.equal(daysLeft(n, T), 1)
  assert.equal(expired({ ...n, deleted_at: T - 31 * DAY }, T), true)
})

test('搜索不区分大小写,高亮切段', () => {
  const notes = [newNote('Shopping list\n牛奶'), newNote('会议纪要'), newNote('买牛奶')]
  assert.deepEqual(search(notes, '牛奶').map((n) => n.text).sort(), ['Shopping list\n牛奶', '买牛奶'].sort())
  assert.equal(search(notes, 'SHOPPING').length, 1)
  assert.deepEqual(highlight('买牛奶和牛奶糖', '牛奶'), [
    { text: '买', hit: false }, { text: '牛奶', hit: true }, { text: '和', hit: false },
    { text: '牛奶', hit: true }, { text: '糖', hit: false }])
})

test('上限:2 万字,按字符数算(emoji 算一个)', () => {
  assert.equal(tooLong('字'.repeat(MAX_CHARS)), null)
  assert.match(tooLong('字'.repeat(MAX_CHARS + 1)) || '', /20,000/)
  assert.equal(charCount('😀😀'), 2)
})

test('编码解码往返;认不出的值返回 null 而不是抛', () => {
  const n = { ...newNote('你好\n世界', T), pinned: true }
  assert.deepEqual(decode(encode(n)), n)
  assert.equal(decode('not json'), null)
  assert.equal(decode(JSON.stringify({ v: 2, id: 'x', text: '' })), null)
  assert.equal(decode(null), null)
})

test('冲突副本:标题前加「(冲突副本)」,正文一字不少', () => {
  assert.equal(conflictCopyText('标题\n正文'), '(冲突副本)标题\n正文')
  assert.equal(conflictCopyText(''), '(冲突副本)')
})

test('id 按时间可排序、定长', () => {
  const a = newId(1000, () => 0)
  const b = newId(2000, () => 0.99)
  assert.equal(a.length, 13)
  assert.ok(a < b)
})
