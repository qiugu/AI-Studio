/**
 * 知识库相关的TypeScript类型定义
 */

export interface KnowledgeBase {
  id: number;
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
  id: number;
  kb_id: number;
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
  id: number;
  content: string;
  chunk_index: number;
  source_page?: number;
  created_at: string;
}

export interface SearchResult {
  id: number;
  content: string;
  score: number;
  doc_id: number;
  doc_name?: string;
  chunk_index: number;
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
