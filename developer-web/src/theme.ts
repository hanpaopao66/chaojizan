// 由 scripts/gen_tokens.py 生成,**不要手改**。
// 改 packages/shared/lib/src/brand.dart 再跑 `python3 scripts/gen_tokens.py`。
import type { ThemeConfig } from 'antd'

/** 浅色态。语义与 App 对齐:clay=行动色,earn=钱的正向,hold=被抽走 */
export const szLight: ThemeConfig = {
  token: {
    colorPrimary: '#C15F3C',
    colorSuccess: '#4E6B4F',
    colorWarning: '#A6763E',
    colorError: '#D03030',
    colorLink: '#2C5F87',
    colorText: '#141413',
    colorTextSecondary: '#6B6862',
    // ⚠️ 不要把 inkFaint 映射成 colorTextTertiary 之类会承载正文的角色:
    // 它对比度不到 3.0,只能做装饰(见 brand.dart 里那段说明)
    colorBorder: '#E2DED2',
    colorBgLayout: '#F0EEE6',
    colorBgContainer: '#FBFAF6',
    borderRadius: 8,
  },
}

/** 深色态 */
export const szDark: ThemeConfig = {
  token: {
    colorPrimary: '#E08A6B',
    colorSuccess: '#8FB08D',
    colorWarning: '#D2A86C',
    colorError: '#E06B6B',
    colorLink: '#7FB2D9',
    colorText: '#F2F0E8',
    colorTextSecondary: '#A8A49A',
    colorBorder: '#37342D',
    colorBgLayout: '#1B1A17',
    colorBgContainer: '#24231F',
    borderRadius: 8,
  },
}
