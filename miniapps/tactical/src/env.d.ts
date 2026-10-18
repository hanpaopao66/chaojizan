// Vite 在构建时把 import.meta.env.DEV 换成常量(开发服务器 true、生产构建 false);这里只声明用到的这一项
interface ImportMeta {
  readonly env: { readonly DEV: boolean }
}
