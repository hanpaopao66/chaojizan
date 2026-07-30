# 演示数据用的真实照片

**这些图只用于演示数据(demo_seed),真实商家不传图时绝不能套用。**

给一家没传图的店配一张不属于它的诱人照片,是平台替商家做虚假宣传:
用户点进去发现不是那样,差评和退款算谁的?这跟我们反对的大数据杀熟是同一类事。
真实商家缺图时走客户端的品类占位图(店名首字 + 品类符号),
一眼看得出是图形不是实拍 —— 这是特性,不是缺陷。

## 来源与许可

全部来自 [Wikimedia Commons](https://commons.wikimedia.org/),
且**只收 Public domain 与 CC0** —— 这两类没有署名义务。
CC BY 要署名、CC BY-SA 还要求衍生作品同样方式共享,
对一个商用 App 是长期负担,为几张演示图背这个包袱不划算。

每张图的来源页、许可、作者见 `manifest.json`。虽然没有法律上的署名义务,
仍然逐张留痕 —— 用了别人的东西就该说得清出处。

## 怎么更新

```bash
python scripts/fetch_demo_photos.py              # 全部品类
python scripts/fetch_demo_photos.py malatang     # 指定品类
```

抓完**必须人眼过一遍**。公有领域里有大量古画、铜版画、细密画和手稿,
它们许可最干净所以最容易被搜出来 —— 实测翻车样本包括:
铜版画建筑进了卤味、波斯细密画进了品质正餐、黑白军舰照进了小吃、
水里的活小龙虾进了龙虾烧烤。脚本已按标题过滤掉一批特征词,
但过滤是粗筛,剩下的只能靠看。

筛掉的写进 `blocklist.txt`(按 Commons 条目名记,文件名会变条目名不会),
重抓时自动跳过。

## 为什么放在 seed_assets 而不是 uploads

`server/uploads/` 既被 `.gitignore` 忽略,也被 `scripts/deploy_server.sh`
的 rsync 排除 —— 图放那儿等于既不进仓库也上不了生产。
这里存一份源,`demo_seed.py` 运行时复制到 `uploads/demo/photos/` 供 HTTP 访问。
