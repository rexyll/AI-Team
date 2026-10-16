# stringkit — 容器镜像模板
# 构建: docker build -t stringkit:latest .
# 说明: CMD 为占位入口，请按 docs/deployment.md 中的已验证命令调整。
FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt || echo "no requirements.txt"

CMD ["python", "main.py  # ← 按部署指引修改为实际入口"]
