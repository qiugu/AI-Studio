/**
 * 知识库相关的TypeScript类型定义
 */

export interface KnowledgeBase {
  id: string;
  name: string;
  description?: string;
  embedding_model: string;
  document_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentStatus {
  value: "pending" | "processing" | "completed" | "failed";
  label: string;
}

export interface KnowledgeDocument {
  id: string;
  kb_id: string;
  file_name: string;
  file_type: string;
  file_size: number;
  status: "pending" | "processing" | "completed" | "failed";
  chunk_count: number;
  error_message?: string;
  processed_at?: string;
  created_at: string;
}

export interface KnowledgeChunk {
  id: string;
  content: string;
  chunk_index: number;
  source_page?: number;
  created_at: string;
}

export interface SearchResult {
  id: string;
  content: string;
  score: number;
  doc_id: string;
  doc_name?: string;
  chunk_index: number;
  /**
   * 被折叠掉的等值副本数。
   *
   * 后端按内容去重后，本条是唯一保留的副本；该字段记录同内容还有多少份副本被
   * 折叠（无副本时为 0）。存在它的意义是让界面能解释「结果条数为何少于请求的
   * top_k」——那是去重在生效，而不是召回不足。
   *
   * 可选：服务端去重关闭时不返回该字段。
   */
  duplicate_count?: number;
}

// 请求参数类型

export interface CreateKnowledgeBaseParams {
  name: string;
  description?: string;
  embedding_model?: string;
}

export interface UpdateKnowledgeBaseParams {
  name?: string;
  description?: string;
}

export interface SearchParams {
  query: string;
  top_k?: number;
  score_threshold?: number;
}
