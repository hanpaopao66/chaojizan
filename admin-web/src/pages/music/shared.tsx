import { useEffect, useState } from 'react'

import { MusicReasonCode, musicReasonCodes } from '../../api_music'
import { fail } from '../community/shared'

/**
 * 音乐治理几页共用的小件。
 *
 * 原因代码是音乐自己的一张表(§5.11:视频的通用项 C1xx + 音乐的 M3xx + X999),
 * **不是** `/admin/social/reason-codes` 那一张 —— 那边没有 M301 侵权、M304 歌词违规。
 */

let cached: MusicReasonCode[] | null = null
let cachedCopyright = 'M301'

export function useMusicReasonCodes(): MusicReasonCode[] {
  const [codes, setCodes] = useState<MusicReasonCode[]>(cached ?? [])
  useEffect(() => {
    if (cached) return
    musicReasonCodes().then((r) => {
      cached = r.items
      cachedCopyright = r.copyright_code
      setCodes(r.items)
    }).catch(fail)
  }, [])
  return codes
}

/** 版权投诉的代码(举报页用它决定要不要把联系方式摆出来) */
export const copyrightCode = () => cachedCopyright

export const TARGET_LABELS: Record<string, string> = {
  track: '歌曲', release: '作品', comment: '评论', playlist: '歌单', artist: '音乐人',
}

export const ARTIST_STATUS_LABELS: Record<string, string> = {
  active: '正常', suspended: '已停用', closed: '已注销',
}

export const RELEASE_STATUS_COLORS: Record<string, string> = {
  draft: 'default', reviewing: 'processing', published: 'green', rejected: 'orange',
  withdrawn: 'default', removed: 'red',
}
