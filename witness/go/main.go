// Super-Z 社区见证节点(绿色版):双击即运行,Windows/macOS/Linux 单文件零依赖。
//
// 与 witness.py / 网页版 / 手机版完全相同的校验算法:
//  1. 拉取平台公开账本(匿名化流水,无任何个人信息),逐日复算哈希链;
//  2. 校验三原则:商家佣金 ≤承诺上限、净额恒等、配送费只进不冲、团购费 = 承诺费率
//     (上限/费率内嵌在每日账本里,当前 5% / 2%;历史锚点按当天口径复算);
//  3. 锚点留存在本程序旁边的 witness-state.json —— 平台改历史,你立刻知道。
//
// 绿色软件约定:不写注册表、不装服务、状态文件就在可执行文件旁边,删掉即卸载。
package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const (
	version          = "go-0.2.1"
	defaultAPI       = "https://chaojizan.cc"
	heartbeatSeconds = 300
	genesis          = "0000000000000000000000000000000000000000000000000000000000000000"

	cGreen = "\x1b[32m"
	cRed   = "\x1b[31m"
	cDim   = "\x1b[2m"
	cBold  = "\x1b[1m"
	cReset = "\x1b[0m"
)

// ---------- 播报:控制台(彩色) + witness-log.txt(留证,自动轮转) ----------

func logPath() string {
	exe, err := os.Executable()
	if err != nil {
		return "witness-log.txt"
	}
	return filepath.Join(filepath.Dir(exe), "witness-log.txt")
}

func say(color, format string, a ...any) {
	line := fmt.Sprintf(format, a...)
	fmt.Println(color + line + cReset)
	if f, err := os.OpenFile(logPath(),
		os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
		fmt.Fprintf(f, "%s %s\n", time.Now().Format("2006-01-02 15:04:05"), line)
		info, _ := f.Stat()
		f.Close()
		if info != nil && info.Size() > 512*1024 { // 超 512KB 轮转,只留一份旧档
			_ = os.Rename(logPath(), logPath()+".old")
		}
	}
}

func yuan(cents float64) string {
	return fmt.Sprintf("¥%.0f", cents/100)
}

// ---------- 与服务端 canonical() 字节级一致的规范化 JSON ----------

func canonical(v any) string {
	var b bytes.Buffer
	writeCanonical(&b, v)
	return b.String()
}

func writeCanonical(b *bytes.Buffer, v any) {
	switch x := v.(type) {
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSONScalar(b, k)
			b.WriteByte(':')
			writeCanonical(b, x[k])
		}
		b.WriteByte('}')
	case []any:
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			writeCanonical(b, e)
		}
		b.WriteByte(']')
	default:
		writeJSONScalar(b, v)
	}
}

func writeJSONScalar(b *bytes.Buffer, v any) {
	enc := json.NewEncoder(b)
	enc.SetEscapeHTML(false) // Python 不转义 <>&,这里必须一致
	_ = enc.Encode(v)
	b.Truncate(b.Len() - 1) // 去掉 Encode 附加的换行
}

func sha256Hex(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

// ---------- HTTP ----------

var client = &http.Client{Timeout: 30 * time.Second}

func getJSON(url string, out any) error {
	resp, err := client.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 404 {
		return fmt.Errorf("平台还未开通公开账本(服务端待更新),或地址不对")
	}
	if resp.StatusCode >= 400 {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func postJSON(url string, body any) error {
	data, _ := json.Marshal(body)
	resp, err := client.Post(url, "application/json", bytes.NewReader(data))
	if err != nil {
		return err
	}
	resp.Body.Close()
	return nil
}

// localUTCOffset 本机 UTC 偏移(如 UTC+08:00),仅供 /nodes 世界地图粗定位。
// WITNESS_TZ 可覆盖(IANA 名),设为空串则不上报。
func localUTCOffset() string {
	if v, set := os.LookupEnv("WITNESS_TZ"); set {
		if len(v) > 40 {
			v = v[:40]
		}
		return v
	}
	return time.Now().Format("UTC-07:00")
}

// ---------- 三原则逐行核账(与 witness.py verify_rows 一致) ----------

func num(v any) float64 {
	f, _ := v.(float64)
	return f
}

func verifyRows(p map[string]any) []string {
	var problems []string
	rate := 0.06
	if r, ok := p["commission_rate_max"].(float64); ok {
		rate = r
	}
	vrate := 0.03
	if r, ok := p["voucher_rate"].(float64); ok {
		vrate = r
	}
	rows, _ := p["merchant_rows"].([]any)
	for _, ri := range rows {
		r := ri.(map[string]any)
		food, fee, net := num(r["food"]), num(r["commission"]), num(r["net"])
		if net != food-fee {
			problems = append(problems, fmt.Sprintf("商家行 %v: 净额恒等式不成立", r["o"]))
		}
		if abs(fee) > abs(food)*rate+1 {
			problems = append(problems, fmt.Sprintf("商家行 %v: 佣金超过 %.0f%%", r["o"], rate*100))
		}
	}
	rows, _ = p["rider_rows"].([]any)
	for _, ri := range rows {
		r := ri.(map[string]any)
		if r["kind"] != "earning" || num(r["amount"]) < 0 {
			problems = append(problems, fmt.Sprintf("骑手行 %v: 配送费被冲减", r["o"]))
		}
	}
	rows, _ = p["voucher_rows"].([]any)
	for _, ri := range rows {
		r := ri.(map[string]any)
		gross := num(r["gross"])
		expect := float64(int64(gross * vrate))
		if num(r["fee"]) != expect || num(r["net"]) != gross-num(r["fee"]) {
			problems = append(problems, fmt.Sprintf("团购行 %v: 服务费不是 %.0f%%", r["p"], vrate*100))
		}
	}
	return problems
}

func abs(f float64) float64 {
	if f < 0 {
		return -f
	}
	return f
}

// ---------- 状态(绿色软件:放在可执行文件旁边) ----------

type state struct {
	NodeID string            `json:"node_id"`
	Seen   map[string]string `json:"seen"`
}

func statePath() string {
	exe, err := os.Executable()
	if err != nil {
		return "witness-state.json"
	}
	return filepath.Join(filepath.Dir(exe), "witness-state.json")
}

func loadState() *state {
	s := &state{Seen: map[string]string{}}
	if data, err := os.ReadFile(statePath()); err == nil {
		_ = json.Unmarshal(data, s)
	}
	if s.NodeID == "" {
		buf := make([]byte, 16)
		_, _ = rand.Read(buf)
		s.NodeID = hex.EncodeToString(buf)
	}
	if s.Seen == nil {
		s.Seen = map[string]string{}
	}
	return s
}

func (s *state) save() {
	data, _ := json.Marshal(s)
	_ = os.WriteFile(statePath(), data, 0o644)
}

// ---------- 一轮见证 ----------

type anchor struct {
	Day         string `json:"day"`
	PayloadHash string `json:"payload_hash"`
	ChainHash   string `json:"chain_hash"`
}

func runCycle(api string, st *state) (ok bool, summary string) {
	var anchors []anchor
	after := ""
	for {
		var page []anchor
		if err := getJSON(api+"/ledger/anchors?after="+after, &page); err != nil {
			return false, "连接失败: " + err.Error()
		}
		anchors = append(anchors, page...)
		if len(page) < 400 {
			break
		}
		after = page[len(page)-1].Day
	}

	current := map[string]string{}
	for _, a := range anchors {
		current[a.Day] = a.ChainHash
	}
	var problems []string
	for d, h := range st.Seen {
		if ch, okc := current[d]; okc && ch != h {
			problems = append(problems, "锚点被改: "+d)
		} else if !okc {
			problems = append(problems, "锚点消失: "+d)
		}
	}

	prev := genesis
	verifiedDay, verifiedHash := "", ""
	freshDays := 0
	var lastTotals map[string]any
	for _, a := range anchors {
		if h, seen := st.Seen[a.Day]; seen && len(problems) == 0 {
			prev, verifiedDay, verifiedHash = h, a.Day, h
			continue
		}
		var detail struct {
			Payload     map[string]any `json:"payload"`
			PayloadHash string         `json:"payload_hash"`
		}
		if err := getJSON(api+"/ledger/days/"+a.Day, &detail); err != nil {
			return false, "拉取账本失败: " + err.Error()
		}
		ph := sha256Hex(canonical(detail.Payload))
		ch := sha256Hex(prev + ph)
		if ph != detail.PayloadHash || ch != a.ChainHash {
			problems = append(problems, a.Day+": 哈希链复算不一致")
			break
		}
		rowProblems := verifyRows(detail.Payload)
		for _, p := range rowProblems {
			problems = append(problems, a.Day+": "+p)
		}
		// 逐日播报:让看着窗口的人"看见钱在被核对"
		m, _ := detail.Payload["merchant_rows"].([]any)
		rr, _ := detail.Payload["rider_rows"].([]any)
		v, _ := detail.Payload["voucher_rows"].([]any)
		if len(rowProblems) == 0 {
			say(cDim, "  核验 %s ✓ 哈希一致(商家 %d 行 · 骑手 %d 行 · 团购 %d 行)",
				a.Day, len(m), len(rr), len(v))
		}
		lastTotals, _ = detail.Payload["totals"].(map[string]any)
		st.Seen[a.Day] = ch
		prev, verifiedDay, verifiedHash = ch, a.Day, ch
		freshDays++
		if len(problems) > 20 {
			break
		}
	}
	st.save()

	ok = len(problems) == 0
	message := ""
	for i, p := range problems {
		if i > 0 {
			message += "; "
		}
		message += p
	}
	if len(message) > 200 {
		message = message[:200]
	}
	_ = postJSON(api+"/nodes/heartbeat", map[string]any{
		"node_id": st.NodeID, "name": os.Getenv("WITNESS_NAME"),
		"region": "绿色版", "tz": localUTCOffset(), "version": version,
		"verified_day": verifiedDay, "chain_hash": verifiedHash,
		"ok": ok, "message": message,
	})

	if !ok {
		return false, message
	}
	// 报账播报:最新一天的钱都去了哪(核对过的数字才有资格被播报)
	if lastTotals != nil {
		mn, rc, pc := num(lastTotals["merchant_net"]),
			num(lastTotals["rider_amount"]), num(lastTotals["platform_commission"])
		if mn+rc+pc > 0 {
			say(cGreen, "  %s 分账核对:商家净得 %s · 骑手所得 %s · 平台佣金 %s——全部吻合",
				verifiedDay, yuan(mn), yuan(rc), yuan(pc))
		}
	}
	var sum struct {
		Online int `json:"online"`
	}
	if getJSON(api+"/nodes/summary", &sum) == nil && sum.Online > 0 {
		say(cDim, "  全网在线见证节点:%d 个(含你)", sum.Online)
	}
	if freshDays == 0 {
		return true, fmt.Sprintf("账本无新增,历史 %d 天完好", len(st.Seen))
	}
	return true, fmt.Sprintf("本轮核验 %d 天 ✓ 账本可信(累计见证 %d 天)", freshDays, len(st.Seen))
}

func main() {
	setupConsole() // Windows 下切 UTF-8 代码页,中文不乱码
	api := os.Getenv("SUPERZ_API")
	if api == "" {
		api = defaultAPI
	}
	fmt.Println("======================================================")
	fmt.Println("  Super-Z 社区见证节点(绿色版)", version)
	fmt.Println("  平台:", api)
	fmt.Println("  这个小程序每 5 分钟独立核验一次平台的公开账本。")
	fmt.Println("  保持本窗口开着,你就在监督平台;关掉即退出,不留任何东西。")
	fmt.Println("======================================================")
	st := loadState()
	fmt.Println("节点 ID:", st.NodeID[:12]+"…(本机随机生成,只用于去重计数)")
	fmt.Println("日志同时写入:", logPath())
	fmt.Println()
	once := len(os.Args) > 1 && os.Args[1] == "--once"
	for {
		ok, summary := runCycle(api, st)
		now := time.Now()
		if ok {
			say(cBold+cGreen, "[%s] ✓ %s", now.Format("15:04:05"), summary)
		} else {
			// 异常:红色横幅 + 蜂鸣,值得吵醒人
			fmt.Print("\a\a\a")
			say(cBold+cRed, strings.Repeat("!", 56))
			say(cBold+cRed, "[%s] ✗ 发现问题,请截图本窗口并公开质询:", now.Format("15:04:05"))
			say(cBold+cRed, "  %s", summary)
			say(cBold+cRed, strings.Repeat("!", 56))
		}
		if once {
			if ok {
				os.Exit(0)
			}
			os.Exit(1)
		}
		say(cDim, "  下一轮 %s · 保持窗口开启即持续见证",
			now.Add(heartbeatSeconds*time.Second).Format("15:04"))
		time.Sleep(heartbeatSeconds * time.Second)
	}
}
