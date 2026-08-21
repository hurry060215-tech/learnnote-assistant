# 本地知识检索模式

LearnNote 默认使用 SQLite FTS5/BM25，缺少 FTS5 时降级到 LIKE；所有结果保留 source_evidence_id、视频秒级时间范围、PDF 页码或文档定位。

## 可选本地 embedding

安装 backend/requirements.embedding.txt 后，调用：

GET /api/knowledge/embedding-status
GET /api/knowledge/search?q=梯度下降&mode=embedding
POST /api/knowledge/ask，提交 question 和 mode=embedding

embedding 模型在本机加载，默认不安装、不上传资料库；模型缺失时 API 返回明确的 local_embedding_unavailable，不会偷偷退回远程服务。删除和重建仍由本地 SourceEvidence API 管理。
