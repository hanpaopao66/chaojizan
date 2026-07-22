import * as echarts from 'echarts'
import React, { useEffect, useRef } from 'react'

/* 系列色经 CVD 校验(深底 #0B0E14 下六项检查全过):
   橙/蓝/绿/琥珀/紫/玫红,固定顺序按实体分配,不轮转 */
export const PALETTE = {
  orange: '#F04E12', blue: '#3E8EE0', green: '#1FA878',
  amber: '#C9801C', purple: '#9B7BE8', rose: '#C05A87',
  muted: '#5A6D96', ink: '#C6CEDF', inkDim: '#66708A',
  grid: 'rgba(77,130,220,.12)',
}
const P = PALETTE

const yuan = c => (c ?? 0) / 100
export const fmtWan = v => (v >= 1e8 ? `${(v / 1e8).toFixed(1)}亿`
  : v >= 1e4 ? `${(v / 1e4).toFixed(1)}万` : `${Math.round(v)}`)

/* ECharts 挂载:option 变化增量更新,面板尺寸变化自动 resize */
export function Chart({ option }) {
  const ref = useRef(null)
  const inst = useRef(null)
  useEffect(() => {
    inst.current = echarts.init(ref.current, null, { devicePixelRatio: 2 })
    const ro = new ResizeObserver(() => inst.current?.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); inst.current?.dispose(); inst.current = null }
  }, [])
  useEffect(() => { option && inst.current?.setOption(option) }, [option])
  return <div ref={ref} style={{ position: 'absolute', inset: 0 }} />
}

const axisBase = {
  axisLine: { lineStyle: { color: P.grid } },
  axisTick: { show: false },
  axisLabel: { color: P.inkDim, fontSize: 11 },
  splitLine: { lineStyle: { color: P.grid } },
}
const tooltipBase = {
  backgroundColor: 'rgba(12,18,32,.92)', borderColor: 'rgba(77,130,220,.4)',
  textStyle: { color: '#E8ECF4', fontSize: 12 }, confine: true,
}

/* 近 7 天订单趋势:单系列面积线 */
export function trendOption(trend) {
  return {
    animationDuration: 600,
    grid: { left: 8, right: 14, top: 26, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', ...tooltipBase,
      axisPointer: { lineStyle: { color: 'rgba(240,78,18,.5)' } } },
    xAxis: { type: 'category', data: trend.map(t => t.day),
      boundaryGap: false, ...axisBase, splitLine: { show: false } },
    yAxis: { type: 'value', ...axisBase, minInterval: 1 },
    series: [{
      name: '订单量', type: 'line', data: trend.map(t => t.orders),
      smooth: true, symbol: 'circle', symbolSize: 7,
      lineStyle: { width: 2, color: P.orange },
      itemStyle: { color: P.orange, borderColor: '#0B0E14', borderWidth: 2 },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: 'rgba(240,78,18,.32)' },
        { offset: 1, color: 'rgba(240,78,18,0)' }]) },
      label: { show: true, position: 'top', color: P.ink, fontSize: 11,
        formatter: ({ dataIndex, value }) =>
          dataIndex === trend.length - 1 || value === Math.max(...trend.map(t => t.orders))
            ? fmtWan(value) : '' },
    }],
  }
}

/* 今日 vs 昨日分时:双系列线,图例 + 端点直标 */
export function hourlyOption(hourly) {
  const hours = Array.from({ length: 24 }, (_, h) => `${h}时`)
  return {
    animationDuration: 600,
    legend: { top: 0, right: 4, textStyle: { color: P.ink, fontSize: 11 },
      itemWidth: 14, itemHeight: 8 },
    grid: { left: 8, right: 14, top: 28, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', ...tooltipBase },
    xAxis: { type: 'category', data: hours, boundaryGap: false,
      ...axisBase, splitLine: { show: false },
      axisLabel: { ...axisBase.axisLabel, interval: 5 } },
    yAxis: { type: 'value', ...axisBase, minInterval: 1 },
    series: [
      { name: '今日', type: 'line', data: hourly.today, smooth: true,
        symbol: 'none', lineStyle: { width: 2, color: P.orange },
        itemStyle: { color: P.orange },
        areaStyle: { color: 'rgba(240,78,18,.10)' } },
      { name: '昨日', type: 'line', data: hourly.yesterday, smooth: true,
        symbol: 'none', lineStyle: { width: 2, color: P.muted, type: [4, 4] },
        itemStyle: { color: P.muted } },
    ],
  }
}

/* 今日订单状态分布:环图,切片直标"状态 数量",身份不只靠颜色 */
const STATUS_COLORS = {
  paid: P.blue, accepted: P.amber, ready: P.purple,
  picked_up: P.orange, delivered: P.rose, completed: P.green,
}
export function statusOption(dist) {
  const data = dist.filter(d => d.count > 0)
  const empty = data.length === 0
  return {
    animationDuration: 600,
    tooltip: { ...tooltipBase },
    series: [{
      type: 'pie', radius: ['42%', '62%'], center: ['50%', '52%'],
      data: empty
        ? [{ name: '今日暂无订单', value: 1,
            itemStyle: { color: 'rgba(90,109,150,.25)' } }]
        : data.map(d => ({
            name: d.label, value: d.count,
            itemStyle: { color: STATUS_COLORS[d.status] || P.muted } })),
      itemStyle: { borderColor: '#0B0E14', borderWidth: 2 },
      label: { color: P.ink, fontSize: 12,
        formatter: empty ? '{b}' : '{b} {c}' },
      labelLine: { lineStyle: { color: P.grid } },
      emphasis: { scaleSize: 4 },
    }],
  }
}

/* 城市累计订单 TOP10:横向条形,量级用单一橙色(顺序型),条端直标 */
export function cityOption(cities) {
  const rows = [...cities].reverse()  // ECharts y 轴从下往上
  return {
    animationDuration: 600,
    grid: { left: 8, right: 52, top: 4, bottom: 0, containLabel: true },
    tooltip: { ...tooltipBase },
    xAxis: { type: 'value', show: false },
    yAxis: { type: 'category', data: rows.map(c => c.city),
      ...axisBase, splitLine: { show: false },
      axisLine: { show: false },
      axisLabel: { color: P.ink, fontSize: 12 } },
    series: [{
      type: 'bar', data: rows.map(c => c.orders),
      barWidth: 12,
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: 'rgba(240,78,18,.35)' },
          { offset: 1, color: P.orange }]),
      },
      label: { show: true, position: 'right', color: P.ink, fontSize: 12,
        formatter: ({ value }) => fmtWan(value) },
    }],
  }
}

/* 近 7 天配送时长分布:单系列迷你柱(量级单色) */
export function timingOption(buckets) {
  return {
    animationDuration: 600,
    grid: { left: 4, right: 8, top: 18, bottom: 2, containLabel: true },
    tooltip: { ...tooltipBase },
    xAxis: { type: 'category', data: ['<15分', '15-30', '30-45', '45+'],
      ...axisBase, splitLine: { show: false },
      axisLabel: { ...axisBase.axisLabel, fontSize: 10 } },
    yAxis: { type: 'value', show: false },
    series: [{
      name: '配送单量', type: 'bar', data: buckets, barWidth: 14,
      itemStyle: { borderRadius: [3, 3, 0, 0], color: P.green },
      label: { show: true, position: 'top', color: P.ink, fontSize: 10,
        formatter: ({ value }) => (value > 0 ? fmtWan(value) : '') },
    }],
  }
}

/* 近 7 天交易额:单系列柱(GMV 展示开关打开时才渲染) */
export function gmvOption(trend) {
  return {
    animationDuration: 600,
    grid: { left: 8, right: 14, top: 26, bottom: 4, containLabel: true },
    tooltip: { trigger: 'axis', ...tooltipBase,
      valueFormatter: v => `¥${fmtWan(v)}` },
    xAxis: { type: 'category', data: trend.map(t => t.day),
      ...axisBase, splitLine: { show: false } },
    yAxis: { type: 'value', ...axisBase,
      axisLabel: { ...axisBase.axisLabel, formatter: v => fmtWan(v) } },
    series: [{
      name: '交易额', type: 'bar',
      data: trend.map(t => yuan(t.gmv_cents)),
      barWidth: 16,
      itemStyle: { borderRadius: [4, 4, 0, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#FFB84D' },
          { offset: 1, color: 'rgba(201,128,28,.25)' }]) },
      label: { show: true, position: 'top', color: P.ink, fontSize: 11,
        formatter: ({ dataIndex, value }) =>
          dataIndex === trend.length - 1 ? `¥${fmtWan(value)}` : '' },
    }],
  }
}
