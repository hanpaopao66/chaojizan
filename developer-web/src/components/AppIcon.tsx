/** 应用图标:图片地址画图,一个汉字画衬线字块(和 App 里同一个画法) */
export default function AppIcon({ icon, name, size = 40 }: { icon: string; name: string; size?: number }) {
  const isImg = icon.startsWith('/img/') || icon.startsWith('https://')
  const glyph = [...(icon.trim())].length === 1 ? icon.trim() : ([...name.trim()][0] || '·')
  return (
    <div style={{
      width: size, height: size, borderRadius: size * 0.24, border: '1px solid var(--sz-line)',
      background: 'var(--sz-surface)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      overflow: 'hidden', flex: 'none',
      fontFamily: '"Songti SC", "Noto Serif CJK SC", serif', fontSize: size * 0.42, color: 'var(--sz-ink-muted)',
    }}>
      {isImg ? <img src={icon} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : glyph}
    </div>
  )
}
