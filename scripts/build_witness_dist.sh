#!/bin/bash
# 见证节点绿色版:一台 Mac 交叉编译出 Windows / macOS / Linux 三平台单文件。
# 产物在 build/witness-dist/(不入库),上传方式:
#   - 部署机:scripts/release_apks.sh 之后 scp build/witness-dist/* 到 appdist/witness/
#   - GitHub:gh release upload <tag> build/witness-dist/*
set -e
cd "$(dirname "$0")/.."
SRC=witness/go
OUT=build/witness-dist
mkdir -p $OUT

echo "== Windows (amd64) =="
(cd $SRC && GOOS=windows GOARCH=amd64 go build -ldflags='-s -w' \
    -o ../../$OUT/superz-witness-windows.exe .)

echo "== macOS (通用二进制 Intel+Apple Silicon) =="
(cd $SRC && GOOS=darwin GOARCH=arm64 go build -ldflags='-s -w' -o /tmp/wz-arm64 . \
         && GOOS=darwin GOARCH=amd64 go build -ldflags='-s -w' -o /tmp/wz-amd64 .)
lipo -create /tmp/wz-arm64 /tmp/wz-amd64 -output $OUT/superz-witness-mac
chmod +x $OUT/superz-witness-mac
# zip 保留可执行位,macOS 解压后可直接双击
(cd $OUT && rm -f superz-witness-macos.zip && zip -q superz-witness-macos.zip superz-witness-mac)

echo "== Linux (amd64) =="
(cd $SRC && GOOS=linux GOARCH=amd64 go build -ldflags='-s -w' \
    -o ../../$OUT/superz-witness-linux .)
chmod +x $OUT/superz-witness-linux
(cd $OUT && rm -f superz-witness-linux.tar.gz && tar czf superz-witness-linux.tar.gz superz-witness-linux)

ls -la $OUT
echo "构建完成 ✓"
