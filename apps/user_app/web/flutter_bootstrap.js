{{flutter_js}}
{{flutter_build_config}}

// 用户端网页版的启动脚本(官网 /web/,发版构建见 .github/workflows/release.yml 的 web job)。
//
// 和 Flutter 缺省的启动脚本只差两处:
//
// 1. 字体回落改成同源。引擎遇到打包字体里没有的字(正文里的汉字、emoji、符号),
//    缺省去 fonts.gstatic.com 下 Noto 字体 —— 国内打不开,中文整片变成方块。
//    发版构建带 --web-define=SZ_FONT_FALLBACK_BASE=fontfallback/,
//    scripts/pack_user_web.py 把引擎要的那批字体从 gstatic 原样镜像进构建产物。
//    本地直接 flutter build web 没带这个参数时,下面的占位符原样留着(构建时会有一行
//    Missing web-define 的提示,不影响),这里认出来就走引擎缺省 —— 开发机能连 gstatic。
//    CanvasKit 另由 --no-web-resources-cdn 从本地 canvaskit/ 加载,也不走 gstatic。
//
// 2. 不注册 service worker。Flutter 自己标了弃用;而且离线缓存会让刚发的新版
//    要多刷一两次才出来。缓存交给 nginx(入口文件每次回源确认,见 deploy/nginx)。
const szFontBase = '{{SZ_FONT_FALLBACK_BASE}}';
const szConfig = {};
if (szFontBase.indexOf('{' + '{') !== 0) {
  szConfig.fontFallbackBaseUrl = new URL(szFontBase, document.baseURI).href;
}
_flutter.loader.load({ config: szConfig });
