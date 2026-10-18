// 背包:挖到加、放掉减、没货不能放、有上限。
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { BEDROCK, BRICK, DIRT, GRASS, HOTBAR, LEAVES, LOG, PLANKS, SAND, STONE, WATER, GLASS } from '../src/blocks'
import { addBlock, countOf, newInventory, slotOfBlock, takeBlock, totalBlocks } from '../src/inventory'
import { MAX_STACK } from '../src/save'

test('快捷栏和方块对应:九种可放置方块,基岩/水不在里面', () => {
  assert.equal(HOTBAR.length, 9)
  assert.equal(new Set(HOTBAR).size, 9)
  assert.equal(slotOfBlock(GRASS), 0)
  assert.equal(slotOfBlock(DIRT), 1)
  assert.equal(slotOfBlock(STONE), 2)
  assert.equal(slotOfBlock(SAND), 3)
  assert.equal(slotOfBlock(LOG), 4)
  assert.equal(slotOfBlock(LEAVES), 5)
  assert.equal(slotOfBlock(PLANKS), 6)
  assert.equal(slotOfBlock(GLASS), 7)
  assert.equal(slotOfBlock(BRICK), 8)
  assert.equal(slotOfBlock(BEDROCK), -1)
  assert.equal(slotOfBlock(WATER), -1)
})

test('新背包有初始物资;挖一块加一,放一块减一', () => {
  const inv = newInventory()
  assert.equal(inv.length, 9)
  const before = countOf(inv, slotOfBlock(SAND))
  assert.equal(addBlock(inv, SAND), true)
  assert.equal(countOf(inv, slotOfBlock(SAND)), before + 1)
  assert.equal(takeBlock(inv, slotOfBlock(SAND)), true)
  assert.equal(countOf(inv, slotOfBlock(SAND)), before)
  assert.equal(addBlock(inv, BEDROCK), false, '基岩不进背包')
})

test('数量不够时放不出去;数量不会减成负数', () => {
  const inv = newInventory()
  inv.fill(0)
  assert.equal(takeBlock(inv, 0), false)
  assert.equal(inv[0], 0)
  inv[0] = 2
  assert.equal(takeBlock(inv, 0), true)
  assert.equal(takeBlock(inv, 0), true)
  assert.equal(takeBlock(inv, 0), false)
  assert.equal(inv[0], 0)
  assert.equal(takeBlock(inv, 99), false)
  // 堆叠上限、总数统计
  const stack = newInventory()
  stack[2] = MAX_STACK
  assert.equal(addBlock(stack, STONE), false)
  assert.equal(stack[2], MAX_STACK)
  stack.fill(0)
  stack[0] = 3
  stack[1] = 4
  assert.equal(totalBlocks(stack), 7)
})
