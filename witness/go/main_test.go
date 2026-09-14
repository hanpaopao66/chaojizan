package main

// 四个见证实现(Python / Go / 网页 / App)跑同一份用例:witness/testdata/verify_rows_cases.json。
// 口径分叉的话,这里先红。运行:cd witness/go && go test -count=1 ./...
// (-count=1 不能省:用例文件改了,go test 照样拿缓存的旧结果报绿,撞过)

import (
	"encoding/json"
	"os"
	"sort"
	"strings"
	"testing"
)

type sharedCases struct {
	Cases []struct {
		Name    string         `json:"name"`
		Payload map[string]any `json:"payload"`
		Expect  []string       `json:"expect"`
	} `json:"cases"`
	HashVectors []struct {
		Name        string         `json:"name"`
		Payload     map[string]any `json:"payload"`
		Canonical   string         `json:"canonical"`
		Prev        string         `json:"prev"`
		PayloadHash string         `json:"payload_hash"`
		ChainHash   string         `json:"chain_hash"`
	} `json:"hash_vectors"`
}

func loadShared(t *testing.T) sharedCases {
	t.Helper()
	data, err := os.ReadFile("../testdata/verify_rows_cases.json")
	if err != nil {
		t.Fatalf("读不到共用用例: %v", err)
	}
	var doc sharedCases
	// 和运行时的 getJSON 一样解到 map[string]any:数字是 float64
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatalf("共用用例不是合法 JSON: %v", err)
	}
	if len(doc.Cases) == 0 || len(doc.HashVectors) == 0 {
		t.Fatal("共用用例是空的")
	}
	return doc
}

// tagOf 问题的种类:问题文本第一个空格前的那个词(合计类的问题整句没有空格,就是整句)
func tagOf(p string) string {
	if i := strings.Index(p, " "); i >= 0 {
		return p[:i]
	}
	return p
}

func TestVerifyRowsSharedCases(t *testing.T) {
	for _, c := range loadShared(t).Cases {
		problems := verifyRows(c.Payload)
		got := make([]string, 0, len(problems))
		for _, p := range problems {
			got = append(got, tagOf(p))
		}
		want := append([]string{}, c.Expect...)
		sort.Strings(got)
		sort.Strings(want)
		if strings.Join(got, "|") != strings.Join(want, "|") {
			t.Errorf("%s:\n  报出 %v\n  应为 %v\n  原文 %q", c.Name, got, want, problems)
		}
	}
}

func TestHashVectors(t *testing.T) {
	for _, v := range loadShared(t).HashVectors {
		canon := canonical(v.Payload)
		if canon != v.Canonical {
			t.Errorf("%s: 规范化文本不一致\n  得到 %s\n  应为 %s", v.Name, canon, v.Canonical)
		}
		ph := sha256Hex(canon)
		if ph != v.PayloadHash {
			t.Errorf("%s: payload_hash %s,应为 %s", v.Name, ph, v.PayloadHash)
		}
		if ch := sha256Hex(v.Prev + ph); ch != v.ChainHash {
			t.Errorf("%s: chain_hash %s,应为 %s", v.Name, ch, v.ChainHash)
		}
	}
}
