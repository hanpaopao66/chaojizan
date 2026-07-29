# 设计令牌与组件走查页

第八辑三端视觉重构用的走查页（见 `docs/DEV-PROMPTS-8.md`）。**不随三端发布**，
只用来核对令牌与组件、出验收截图。

```bash
# 交互着看
cd packages/shared/example && flutter run -d chrome

# 出验收截图(浅色 + 深色两张,落到 marketing/design/screens/)
packages/shared/example/tool/shot.sh design_tokens 560 2300
packages/shared/example/tool/shot.sh component_gallery 560 3400
```

`?dark=1` 直接以深色启动，截图脚本靠它一条命令出两张图。

只 import `package:superz_shared/design.dart` 这个轻入口——`superz_shared.dart`
会带出 jpush 等平台插件，web 编不过。
