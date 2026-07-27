import { Empty } from 'antd'

/** 模块占位页(骨架期用,后续提示词逐个替换成真页面)。 */
export default function PlaceholderPage({ title, note }: { title: string; note: string }) {
  return (
    <div style={{ paddingTop: 80 }}>
      <Empty description={`${title} 即将就绪 · ${note}`} />
    </div>
  )
}
