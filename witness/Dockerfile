# Super-Z 社区见证节点:零依赖,几十 MB 内存,树莓派/旧笔记本/最便宜的 VPS 都能跑
FROM python:3.12-alpine

WORKDIR /app
COPY superz_witness.py .

# 状态文件(见过的锚点)放卷里,容器重建不丢——这份记录正是见证的价值所在
VOLUME /data
ENV WITNESS_STATE=/data/witness.json

CMD ["python", "superz_witness.py"]
