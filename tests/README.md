# 测试

## 要求

Docker 容器在运行中：

```bash
docker compose up -d
```

## 运行

```bash
# 方式 1：直接运行
python tests/test_api.py

# 方式 2：pytest
pip install pytest
pytest tests/ -v
```

## 测试项

| 测试 | 端点 | 说明 |
|------|------|------|
| 健康检查 | `GET /health` | API 是否在线 |
| 基础 RAG 查询 | `POST /query` | 最简 RAG 链路 |
| API Key 鉴权 | `POST /query` | 无 Key 应 403 |
| 混合检索 | `POST /query/hybrid` | 含多路召回 |
| Reranker 检索 | `POST /query/hybrid` | Cross-Encoder 排序 |
| 知识库统计 | `GET /kb/stats` | 文档数量 |
| 限流测试 | `GET /health` | 连续请求 |
