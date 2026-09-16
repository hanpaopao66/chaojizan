import React from 'react'

import './pages.css'
import { SitePage, useFeatures } from './SiteChrome.jsx'
import ChatOneGroupFilm from './films/ChatOneGroupFilm.jsx'
import VideoToOrderFilm from './films/VideoToOrderFilm.jsx'

/* 功能介绍页(/features):App 里点外卖以外的四块 ——「聊天」「视频」「音乐」「论坛」。
 * 设计稿「官网动画集」里第 10、11 支片子标的位置就是前两节。
 *
 * 只写 App 里真有的功能(docs/DEV-PROMPTS-40.md、41.md、docs/VERIFY-40.md,逐条对过代码):
 * - 通话、机器人做好了但生产开关缺省关(docs/LAUNCH-40.md §1),这一页不提;
 * - 名片二维码现在从 App 外面扫出来没有落地页、App 里也没有扫一扫,不写「扫码加好友」;
 * - 视频要等《信息网络传播视听节目许可证》,音乐要等《网络文化经营许可证》
 *   (docs/COMPLIANCE-40.md #17、#18),生产上缺省关着。开没开读 /config 的
 *   features(和 App 收起入口用的是同一份开关),关着时这一节头上写明「暂未开放」,
 *   片子标「开放以后的样子」。 */

const CHAT_CARDS = [
  ['私聊、群、频道、收藏夹', '群最多 1000 人。文字、图片、视频、文件、语音、位置、名片都能发，能回复、转发、编辑，也能「为双方删除」。'],
  ['找人不靠通讯录', '靠 @用户名、别人转给你的名片，或输入对方完整的手机号精确找到（「按手机号找到我」能在隐私设置里关掉）。不上传通讯录，找到了也不显示号码。'],
  ['平台读得到，所以把规矩写死', '消息存在平台服务器上，不做端到端加密。管理员只在处理举报时，查看被举报的那几条和前后各 5 条，每次都留记录，次数在透明中心按月公示；订单群另外留档，处理这一单的纠纷时会调取。'],
]

const VIDEO_CARDS = [
  ['推荐公式公开，个性化能关', '推荐、热门、排行榜、竖屏用同一段公开公式：热度 = 互动分 ÷（发布小时数 + 2）^1.5，关注的 UP 主 +30%、常看的分区 +15%，没有付费加权。个性化一键关掉，看到的就和没登录的人一样。'],
  ['探店视频挂的是真店', '只能挂一家本平台的店；挂了店必须声明和商家有没有合作，有合作就标「合作」。平台不收推广费，也不按挂没挂店给流量。'],
  ['先审后发', '投稿先审后发；驳回、下架都带原因，可以申诉，由另一名审核员复核。审核量、驳回率和处置记录在透明中心公示。'],
]

const MUSIC_CARDS = [
  ['音乐人自己上传，不用签公司', '实名不要求，填个音乐人名字就能开通。上传原创或已获授权的作品，自己填曲风、歌词、封面，自己定发布时间；作品、专辑、歌单都在你名下。'],
  ['榜单公式公开', '热歌榜分数 = 近 7 天收听人数 + 3 × 新增喜欢人数 + 5 × 加入歌单人数；听满 min(30 秒, 时长一半) 才算一次收听，按人去重。飙升榜、新歌榜、每日推荐的算法同样写在页面上，个性化一键关掉。同一位音乐人在一个榜里最多 10 首 —— 不让一个人刷满榜。'],
  ['不卖歌，也不卖位置', '没有付费歌曲、没有会员、没有打赏，也没有买榜和推广位。平台不从音乐上收钱，所以也没有理由把谁的歌往前排。'],
]

const FORUM_CARDS = [
  ['发帖、回复、转发、引用、投票', '和你熟悉的那种时间线一样：正文 500 字以内，配图片、话题、@，也能带一个 2–4 选项的投票（5 分钟到 7 天）。转发是原样带走，引用是带着你的话转 —— 两件事分开记，也分开算分。'],
  ['时间线公式公开，个性化能关', '推荐分 = (互动分 + 1) ÷ (发帖后小时数 + 2)^1.5，关注的作者 ×2、带我最近用过的话题 ×1.5。关掉个性化后这两个加权都按 0 算，看到的就是纯粹按热度和时间排的。每屏同一个作者最多 2 条。'],
  ['热门话题不偷偷压', '热门话题分数 = 近 24 小时用过的人数 + 2 × 近 3 小时用过的人数，至少 2 个人用过才上榜。运营要隐藏一个话题，必须写原因、留记录，公示在透明中心。'],
]

export default function FeaturesPage() {
  const features = useFeatures()
  const videoOpen = !!features.video
  const musicOpen = !!features.music
  const forumOpen = !!features.forum

  return (
    <SitePage
      active="features"
      title="超级赞 · 聊天、视频、音乐、论坛:和点外卖在同一个 App 里"
      desc="超级赞 App 里点外卖以外的四块:聊天(一单一个群、私聊群组频道、机器人)、视频(挂真店、先审后发)、音乐(音乐人自己上传、榜单公式公开)、论坛(动态、转发、引用、投票)。四块都不收钱——没有打赏、会员、付费内容和推广位;推荐和榜单用公开公式,个性化可以关掉。"
    >
      <div className="sz-page">
        <div className="sz-eyebrow">聊天 · 视频 · 音乐 · 论坛</div>
        <h1 className="sz-h1">聊天、视频、音乐、论坛，<br />和点外卖在同一个 App 里。</h1>
        <p className="sz-lede ft-lede">
          一个超级赞账号走完全部：聊天里一单一个群，你、商家、骑手在一起说；视频可以挂上视频里那家店，点一下就进店；音乐人自己上传作品；论坛里发动态、转发和投票。
          关注一个人，他的视频、歌和动态就都跟着来。
          这四块都不收钱：没有打赏、会员、付费内容，也没有推广位。
        </p>
        <nav className="ft-toc" aria-label="这一页的四节">
          <a href="#chat">聊天</a>
          <a href="#video">视频{!videoOpen && <span className="st">暂未开放</span>}</a>
          <a href="#music">音乐{!musicOpen && <span className="st">暂未开放</span>}</a>
          <a href="#forum">论坛{!forumOpen && <span className="st">暂未开放</span>}</a>
        </nav>

        <section className="ft-sec" id="chat">
          <div className="sz-eyebrow">聊天</div>
          <h2 className="sz-h2">催出餐、问送到哪了，<br />在同一个群里说。</h2>
          <p className="sz-lede ft-p">万物皆会话：平台通知是带认证标的服务号，视频互动是机器人，每一单是一个群（你 + 商家 + 骑手）。列表只有一种行；群里不出现手机号，送达 24 小时后自动归档 —— 还能翻，不能再发。</p>
          {features.chat === false && <div className="cp-closed">聊天暂时关着，恢复之前发不了新消息。</div>}
          <div className="sz-film-slot"><ChatOneGroupFilm /></div>
          <div className="sz-grid3">
            {CHAT_CARDS.map(([t, d]) => (
              <div key={t} className="sz-card"><div className="body"><div className="t">{t}</div><p className="muted">{d}</p></div></div>
            ))}
          </div>
          <p className="note">自己的聊天记录能导出（每个会话一份 JSON，连同图片和视频）。聊天怎么管、处置了什么、管理员查看了几次，见<a href="/transparency#community">透明中心 · 社区</a>。</p>
        </section>

        <section className="ft-sec" id="video">
          <div className="sz-eyebrow">视频{!videoOpen && <span className="ft-tag">暂未开放</span>}</div>
          <h2 className="sz-h2">从看到吃，两步。</h2>
          <p className="sz-lede ft-p">视频可以挂上视频里那家店 —— 就是屏幕上正在拍的这一家，不是广告位买来的另一家。点一下直接进店，账还是那本账：同一张费率表，配送费一分不抽。硬币只能投给视频，不能充值、不能提现、不能兑换。</p>
          {!videoOpen && (
            <div className="cp-closed">视频暂未开放：上线要先拿到《信息网络传播视听节目许可证》。代码已经做完，许可证到手之前生产上一直关着 —— 下面是开放以后的样子。</div>
          )}
          <div className="sz-film-slot"><VideoToOrderFilm open={videoOpen} /></div>
          <div className="sz-grid3">
            {VIDEO_CARDS.map(([t, d]) => (
              <div key={t} className="sz-card"><div className="body"><div className="t">{t}</div><p className="muted">{d}</p></div></div>
            ))}
          </div>
          <p className="note">推荐公式原文、审核和处置记录见<a href="/transparency#community">透明中心 · 社区</a>；排序代码在开源仓的 <a href="https://github.com/hanpaopao66/chaojizan/blob/main/server/app/services/video_rank.py" target="_blank" rel="noreferrer">services/video_rank.py</a>。</p>
        </section>

        <section className="ft-sec" id="music">
          <div className="sz-eyebrow">音乐{!musicOpen && <span className="ft-tag">暂未开放</span>}</div>
          <h2 className="sz-h2">歌是音乐人自己传的，<br />榜是按公开公式排的。</h2>
          <p className="sz-lede ft-p">发现、榜单、歌单、每日推荐，还有一个音乐人中心：开通之后自己上传作品、建专辑、看自己的收听数。先审后发，作品要声明是原创还是已获授权。歌能分享进聊天，也能分享成一条动态。</p>
          {!musicOpen && (
            <div className="cp-closed">音乐暂未开放：上线要先拿到《网络文化经营许可证》。代码已经做完，许可证到手之前生产上一直关着。</div>
          )}
          <div className="sz-grid3">
            {MUSIC_CARDS.map(([t, d]) => (
              <div key={t} className="sz-card"><div className="body"><div className="t">{t}</div><p className="muted">{d}</p></div></div>
            ))}
          </div>
          <p className="note">榜单公式原文和审核记录见<a href="/transparency#community">透明中心 · 社区</a>；排序代码在开源仓的 <a href="https://github.com/hanpaopao66/chaojizan/blob/main/server/app/services/music_rank.py" target="_blank" rel="noreferrer">services/music_rank.py</a>。</p>
        </section>

        <section className="ft-sec" id="forum">
          <div className="sz-eyebrow">论坛{!forumOpen && <span className="ft-tag">暂未开放</span>}</div>
          <h2 className="sz-h2">一条时间线，<br />排法写在页面上。</h2>
          <p className="sz-lede ft-p">关注流按时间倒序，推荐流按公开公式；话题页、搜索、投票、屏蔽词都有。发帖只要手机号账号，不要求实名。先发后审 —— 发出去就能看见，违规的事后处理，处理要写原因、可以申诉。</p>
          {!forumOpen && (
            <div className="cp-closed">论坛还没在生产上打开，下面是开放以后的样子。</div>
          )}
          <div className="sz-grid3">
            {FORUM_CARDS.map(([t, d]) => (
              <div key={t} className="sz-card"><div className="body"><div className="t">{t}</div><p className="muted">{d}</p></div></div>
            ))}
          </div>
          <p className="note">时间线公式原文、举报和处置记录见<a href="/transparency#community">透明中心 · 社区</a>；排序代码在开源仓的 <a href="https://github.com/hanpaopao66/chaojizan/blob/main/server/app/services/forum_rank.py" target="_blank" rel="noreferrer">services/forum_rank.py</a>。</p>
        </section>

        <div className="jr-cta ft-cta">
          <a className="h3-btn primary lg" href="/download">下载用户端</a>
        </div>
      </div>
    </SitePage>
  )
}
