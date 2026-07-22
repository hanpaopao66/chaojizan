import React from 'react'

/* 品牌矢量标(与 marketing/brand/icon_A.svg 同源):
   导航用小图标 + hero 用横版字标,矢量渲染任何分辨率都利落。 */

const Grad = ({ id }) => (
  <defs>
    <linearGradient id={id} x1="0" y1="0" x2="512" y2="512" gradientUnits="userSpaceOnUse">
      <stop offset="0" stopColor="#FF7A45" />
      <stop offset="1" stopColor="#E1251B" />
    </linearGradient>
  </defs>
)

const Mark = ({ grad }) => (
  <g>
    <rect x="108" y="246" width="64" height="168" rx="22" fill="#FFD34D" />
    <path d="M 244 300 C 239 258 237 234 233 212 C 229 190 224 174 215 154"
      fill="none" stroke="#FFFFFF" strokeWidth="68"
      strokeLinecap="round" strokeLinejoin="round" />
    <rect x="190" y="246" width="204" height="168" rx="36" fill="#FFFFFF" />
    <rect x="262" y="288" width="106" height="14" rx="7" fill={`url(#${grad})`} />
    <rect x="262" y="326" width="106" height="14" rx="7" fill={`url(#${grad})`} />
    <rect x="262" y="364" width="106" height="14" rx="7" fill={`url(#${grad})`} />
  </g>
)

export function BrandIcon({ size = 34 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" aria-hidden="true">
      <Grad id="bi-g" />
      <rect width="512" height="512" rx="116" fill="url(#bi-g)" />
      <Mark grad="bi-g" />
    </svg>
  )
}

export function BrandWordmark({ width = 360 }) {
  return (
    <svg width={width} viewBox="0 0 1560 512" role="img"
      aria-label="超级赞 · 群众帮群众 · SUPER-Z">
      <Grad id="bw-g" />
      <g transform="translate(24,36) scale(0.86)">
        <rect width="512" height="512" rx="116" fill="url(#bw-g)" />
        <Mark grad="bw-g" />
      </g>
      <text x="520" y="238" fontFamily="'Noto Sans CJK SC','PingFang SC',sans-serif"
        fontWeight="900" fontSize="210" fill="#FFFFFF"
        dominantBaseline="central">超级赞</text>
      <text x="528" y="415" fontFamily="'Noto Sans CJK SC','PingFang SC',sans-serif"
        fontWeight="700" fontSize="62" letterSpacing="6"
        fill="#FFD34D">群众帮群众 · SUPER-Z</text>
    </svg>
  )
}
