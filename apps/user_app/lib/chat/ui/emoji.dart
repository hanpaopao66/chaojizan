import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 表情面板:最近用过 + 六个分类。系统自带的 emoji 字体渲染,不打包图片。
const emojiCategories = <(String, IconData, String)>[
  ('笑脸', Icons.emoji_emotions_outlined,
      '😀😃😄😁😆😅😂🤣🥲☺️😊😇🙂🙃😉😌😍🥰😘😗😙😚😋😛😝😜🤪🤨🧐🤓😎🥸🤩🥳😏😒😞😔😟😕🙁☹️😣😖😫😩🥺😢😭😤😠😡🤬🤯😳🥵🥶😱😨😰😥😓🤗🤔🤭🤫🤥😶😐😑😬🙄😯😦😧😮😲🥱😴🤤😪😵🤐🥴🤢🤮🤧😷🤒🤕🤑🤠😈👿👹👺🤡💩👻💀☠️👽👾🤖🎃😺😸😹😻😼😽🙀😿😾'),
  ('手势', Icons.back_hand_outlined,
      '👋🤚🖐️✋🖖👌🤌🤏✌️🤞🫰🤟🤘🤙👈👉👆🖕👇☝️👍👎✊👊🤛🤜👏🙌🫶👐🤲🤝🙏✍️💅🤳💪🦾🦵🦶👂🦻👃🧠🫀🫁🦷🦴👀👁️👅👄💋🩸'),
  ('心情', Icons.favorite_border,
      '❤️🧡💛💚💙💜🖤🤍🤎💔❣️💕💞💓💗💖💘💝💟☮️✝️☯️🕉️✡️🔯☪️☸️💯💢💥💫💦💨🕳️💬👁️‍🗨️🗨️🗯️💭💤🎉🎊🎈🎁🏆🥇🥈🥉🏅🎖️'),
  ('动物', Icons.pets_outlined,
      '🐶🐱🐭🐹🐰🦊🐻🐼🐻‍❄️🐨🐯🦁🐮🐷🐽🐸🐵🙈🙉🙊🐒🐔🐧🐦🐤🐣🐥🦆🦅🦉🦇🐺🐗🐴🦄🐝🪱🐛🦋🐌🐞🐜🪰🪲🪳🦟🦗🕷️🦂🐢🐍🦎🦖🦕🐙🦑🦐🦞🦀🐡🐠🐟🐬🐳🐋🦈🐊🐅🐆🦓🦍🦧🐘🦛🦏🐪🐫🦒🦘🐃🐂🐄🐎🐖🐏🐑🦙🐐🦌🐕🐩🦮🐈🐓🦃🦚🦜🦢🦩🕊️🐇🦝🦨🦡🦫🦦🦥🐁🐀🐿️🦔🌸🌹🌺🌻🌼🌷🌱🌲🌳🌴🌵🍀🍁🍂🍃'),
  ('美食', Icons.ramen_dining_outlined,
      '🍏🍎🍐🍊🍋🍌🍉🍇🍓🫐🍈🍒🍑🥭🍍🥥🥝🍅🍆🥑🥦🥬🥒🌶️🫑🌽🥕🧄🧅🥔🍠🥐🥯🍞🥖🥨🧀🥚🍳🧈🥞🧇🥓🥩🍗🍖🌭🍔🍟🍕🥪🥙🧆🌮🌯🥗🥘🍝🍜🍲🍛🍣🍱🥟🦪🍤🍙🍚🍘🍥🥠🥮🍢🍡🍧🍨🍦🥧🧁🍰🎂🍮🍭🍬🍫🍿🍩🍪🌰🥜🍯🥛🍼☕🍵🧃🥤🧋🍶🍺🍻🥂🍷🥃🍸🍹🧉🍾🧊🥢🍽️🍴🥄'),
  ('出行', Icons.directions_car_outlined,
      '🚗🚕🚙🚌🚎🏎️🚓🚑🚒🚐🛻🚚🚛🚜🛵🏍️🛺🚲🛴🚏🛣️🛤️⛽🚨🚥🚦🛑🚧⚓⛵🛶🚤🛳️⛴️🚢✈️🛩️🛫🛬🪂💺🚁🚟🚠🚡🛰️🚀🛸🏠🏡🏘️🏚️🏗️🏭🏢🏬🏣🏤🏥🏦🏨🏪🏫🏩💒🏛️⛪🕌🕍🛕🕋⛩️🗾🎑🏞️🌅🌄🌠🎇🎆🌇🌆🏙️🌃🌌🌉🌁⌚📱💻⌨️🖥️🖨️🖱️💽💾💿📷📸📹🎥📞☎️📺📻⏰⏳💡🔦🕯️💸💵💴💶💷💰💳🧾✉️📦📫📝✏️📌📍📎✂️🔒🔑🔨🧰🧲💊💉🩹🧸🛒'),
];

/// 长按消息时顶上那一排快捷回应(和服务端允许的集合取交集后显示)
const quickReactions = ['👍', '❤️', '😁', '🔥', '🥰', '👏', '🤔', '😢', '🎉', '🙏'];

List<String> splitEmoji(String s) {
  // 按字素簇切:肤色、ZWJ 组合、国旗都算一个
  return s.characters.toList();
}

class EmojiPanel extends StatefulWidget {
  const EmojiPanel({super.key, required this.onPick, this.onBackspace, this.height = 280});

  final void Function(String emoji) onPick;
  final VoidCallback? onBackspace;
  final double height;

  @override
  State<EmojiPanel> createState() => _EmojiPanelState();
}

class _EmojiPanelState extends State<EmojiPanel> with SingleTickerProviderStateMixin {
  static const _recentKey = 'chat_recent_emoji';
  List<String> _recent = [];
  late final TabController _tc = TabController(length: emojiCategories.length + 1, vsync: this);

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((sp) {
      if (!mounted) return;
      setState(() => _recent = sp.getStringList(_recentKey) ?? []);
      if (_recent.isEmpty) _tc.index = 1;
    });
  }

  @override
  void dispose() {
    _tc.dispose();
    super.dispose();
  }

  Future<void> _pick(String e) async {
    widget.onPick(e);
    final next = [e, ..._recent.where((x) => x != e)].take(32).toList();
    setState(() => _recent = next);
    final sp = await SharedPreferences.getInstance();
    await sp.setStringList(_recentKey, next);
  }

  Widget _grid(List<String> items) => GridView.builder(
        padding: const EdgeInsets.all(8),
        gridDelegate:
            const SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: 44, mainAxisExtent: 44),
        itemCount: items.length,
        itemBuilder: (_, i) => InkResponse(
          onTap: () => _pick(items[i]),
          radius: 22,
          child: Center(child: Text(items[i], style: const TextStyle(fontSize: kFigureMd))),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SizedBox(
      height: widget.height,
      child: Column(children: [
        Row(children: [
          Expanded(
            child: TabBar(
              controller: _tc,
              isScrollable: true,
              tabAlignment: TabAlignment.start,
              labelColor: sz.clay,
              unselectedLabelColor: sz.inkMuted,
              indicatorColor: sz.clay,
              dividerColor: Colors.transparent,
              tabs: [
                const Tab(icon: Icon(Icons.history, size: 20)),
                for (final c in emojiCategories) Tab(icon: Icon(c.$2, size: 20)),
              ],
            ),
          ),
          if (widget.onBackspace != null)
            IconButton(
                tooltip: '删除', icon: const Icon(Icons.backspace_outlined), onPressed: widget.onBackspace),
        ]),
        Expanded(
          child: TabBarView(controller: _tc, children: [
            _recent.isEmpty
                ? Center(child: Text('最近用过的表情会出现在这里', style: TextStyle(color: sz.inkMuted)))
                : _grid(_recent),
            for (final c in emojiCategories) _grid(splitEmoji(c.$3)),
          ]),
        ),
      ]),
    );
  }
}
