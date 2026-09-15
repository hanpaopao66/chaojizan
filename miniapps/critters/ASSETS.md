# 萌兽三路的美术和音效来源

全部来自 Kenney(<https://kenney.nl>)的公开素材包,**CC0 1.0 公有领域**授权
(<https://creativecommons.org/publicdomain/zero/1.0/>):可以商用、可以改,不要求署名。
游戏的「关于」里还是写了一句来源。

- 只从作者官网下载:每个包的页面上点「Continue without donating」拿到的 zip(地址见下表);
- 每个包解压后都看过里面的 License 文件,原文写的就是 CC0(下表「许可证原文」一栏照抄);
- 原始 zip 不进仓库;仓库里只有挑出来、处理过的产物(`public/art`、`public/sfx`)和处理脚本(`tools/build_assets.py`);
- 游戏的名字、规则、关卡、卡牌数值、界面都是原创;没有用任何商业游戏的素材、角色或界面。

## 用到的包

| 包 | 页面 | 下载的 zip | 许可证原文 | 用在哪儿 |
|---|---|---|---|---|
| Animal Pack Remastered | <https://kenney.nl/assets/animal-pack-remastered> | [kenney_animal-pack-remastered.zip](https://kenney.nl/media/pages/assets/animal-pack-remastered/54a307a369-1774771709/kenney_animal-pack-remastered.zip) | License (Creative Commons Zero, CC0) | 30 只动物头像(`PNG/Round (outline)`):所有单位、Boss、卡面 |
| RPG Base | <https://kenney.nl/assets/rpg-base> | [kenney_rpg-base.zip](https://kenney.nl/media/pages/assets/rpg-base/316dd80b01-1677669634/kenney_rpg-base.zip) | License (CC0) | 2 倍表格 `RPGpack_sheet_2X.png`:草地、土路、树、灌木、池塘、木桶、木箱、栅栏;墙、屋顶、门窗拼出哨塔、大本营、瞭望台和废墟;鸡窝的木箱 |
| UI Pack - Adventure | <https://kenney.nl/assets/ui-pack-adventure> | [kenney_ui-pack-adventure.zip](https://kenney.nl/media/pages/assets/ui-pack-adventure/9a877376bc-1723597274/kenney_ui-pack-adventure.zip) | License: (Creative Commons Zero, CC0) | 结算页标题的横幅 `banner_hanging.png` |
| Game Icons | <https://kenney.nl/assets/game-icons> | [kenney_game-icons.zip](https://kenney.nl/media/pages/assets/game-icons/1ebf9c14af-1677661579/kenney_game-icons.zip) | License (CC0) | 13 个界面图标(暂停、声音开关、说明、星、锁、奖杯、勾、叉、返回、卡组、奖牌、靶心) |
| Board Game Icons | <https://kenney.nl/assets/board-game-icons> | [kenney_board-game-icons.zip](https://kenney.nl/media/pages/assets/board-game-icons/19cae04050-1721645690/kenney_board-game-icons.zip) | License: (Creative Commons Zero, CC0) | 每日挑战的图标(`notepad.png`) |
| Particle Pack | <https://kenney.nl/assets/particle-pack> | [kenney_particle-pack.zip](https://kenney.nl/media/pages/assets/particle-pack/f8fe0f8cb8-1677578741/kenney_particle-pack.zip) | License (Creative Commons Zero, CC0) | 粒子(光点、光环、光晕、星、火花、刀光、烟、碎土、火苗、心、旋风、焦痕、魔法、拖尾),四张法术卡面里的光效 |
| Smoke Particles | <https://kenney.nl/assets/smoke-particles> | [kenney_smoke-particles.zip](https://kenney.nl/media/pages/assets/smoke-particles/23249a0d35-1677695171/kenney_smoke-particles.zip) | License (CC0) | 白烟(击倒时的烟团、扬尘)、爆炸(火球、塔倒) |
| Interface Sounds | <https://kenney.nl/assets/interface-sounds> | [kenney_interface-sounds.zip](https://kenney.nl/media/pages/assets/interface-sounds/fa43c1dd4d-1677589452/kenney_interface-sounds.zip) | License: (Creative Commons Zero, CC0) | 点按、出兵、击倒、投掷、冰冻、回血、鼓舞、返还能量、出错、星星、升级、倒计时 |
| Impact Sounds | <https://kenney.nl/assets/impact-sounds> | [kenney_impact-sounds.zip](https://kenney.nl/media/pages/assets/impact-sounds/87b4ddecda-1677589768/kenney_impact-sounds.zip) | License: (Creative Commons Zero, CC0) | 挨打(三种)、重击、箭、塔挨打、塔倒 |
| RPG Audio | <https://kenney.nl/assets/rpg-audio> | [kenney_rpg-audio.zip](https://kenney.nl/media/pages/assets/rpg-audio/8e99002d76-1677590336/kenney_rpg-audio.zip) | License (Creative Commons Zero, CC0) | 结算时的金币声 |
| Music Jingles | <https://kenney.nl/assets/music-jingles> | [kenney_music-jingles.zip](https://kenney.nl/media/pages/assets/music-jingles/f37e530b9e-1677590399/kenney_music-jingles.zip) | License (Creative Commons Zero, CC0) | 胜利、失败、解锁新卡(拨弦那一组 `jingles_PIZZI02/01/16`) |
| Casino Audio | <https://kenney.nl/assets/casino-audio> | [kenney_casino-audio.zip](https://kenney.nl/media/pages/assets/casino-audio/2472606a04-1721639069/kenney_casino-audio.zip) | License (Creative Commons Zero, CC0) | 只用了纸牌的声音:选牌、出牌、开局洗牌 |
| Sci-fi Sounds | <https://kenney.nl/assets/sci-fi-sounds> | [kenney_sci-fi-sounds.zip](https://kenney.nl/media/pages/assets/sci-fi-sounds/6b296f9ecf-1677589334/kenney_sci-fi-sounds.zip) | License: (Creative Commons Zero, CC0) | 火球和塔倒时的爆炸声 `explosionCrunch_000` |

具体用了包里的哪个文件,以 `tools/build_assets.py` 里写的为准(`ANIMALS`、`build_world`、`load_fx`、`build_ui`、`SOUNDS`)。

## 怎么处理的

`tools/build_assets.py`(Pillow + ffmpeg)做了这些事,产物进仓库,构建时不再跑:

- **图集**:`art/units.webp`(动物头像 + 四张法术卡面 + 栅栏、鸡窝、瞭望台)、`art/world.webp`(五个主题的草地和土路、树、灌木、
  池塘、木桶木箱、两边的塔和废墟)、`art/fx.webp`(白色粒子,游戏里再染色);每一帧的坐标写进 `src/art.ts`;
- **拼和改**:哨塔 = RPG Base 的尖顶压在两块墙拼成的墙身上、中间一扇窗;大本营 = 山墙屋顶 + 两格墙 + 拱门;玩家一方用米色墙和棕屋顶,
  电脑一方用灰石墙和深色屋顶;废墟是墙的下半截咬成锯齿再压暗;五个主题(草地、沼泽、雪原、雨林、高原)的地面是同一张草地和土路
  换色相、饱和度、明度;雪原的树是把深绿的树冠往雪白里掺;法术卡面是画的圆球里叠 Particle Pack 的光效;
- **格式**:图片全部 webp(质量 88),图标是白色剪影、在页面里当遮罩用(颜色跟着主题走);音效转成单声道 AAC(m4a,64 kbps),
  去掉元数据;
- **大小**:图和声音一共约 390 KB。

## 重新生成

```sh
# 1. 按上表的地址下载 13 个 zip,解压到同一个目录,子目录名用页面地址里的名字:
#    <素材目录>/animal-pack-remastered/  rpg-base/  ui-pack-adventure/  game-icons/  board-game-icons/  particle-pack/
#    smoke-particles/  interface-sounds/  impact-sounds/  rpg-audio/  music-jingles/  casino-audio/  sci-fi-sounds/
# 2. 生成(Pillow、ffmpeg)
python3 miniapps/critters/tools/build_assets.py <素材目录>
```
