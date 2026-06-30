/**
 * 知识库 API 客户端
 */

import client from "./client";
import type { ApiResponse, PaginatedData } from "@/types/api";
import {
  type KnowledgeBase,
  type KnowledgeDocument,
  type KnowledgeChunk,
  type SearchResult,
  type CreateKnowledgeBaseParams,
  type UpdateKnowledgeBaseParams,
  type SearchParams,
} from "@/types/knowledge";

/**
 * 知识库管理 API
 */

// 创建知识库
export const createKnowledgeBase = (params: CreateKnowledgeBaseParams) => {
  const queryParams = new URLSearchParams();
  queryParams.append("name", params.name);
  if (params.description) queryParams.append("description", params.description);
  if (params.embedding_model) queryParams.append("embedding_model", params.embedding_model);

  return client.post<ApiResponse<KnowledgeBase>>(
    `/knowledge/knowledge-bases?${queryParams}`
  );
};

// 列出知识库
export const listKnowledgeBases = (page = 1, pageSize = 20) => {
  return client.get<PaginatedData<KnowledgeBase>>(
    `/knowledge/knowledge-bases?page=${page}&page_size=${pageSize}`
  );
};

// 获取知识库详情
export const getKnowledgeBase = (kbId: number) => {
  return client.get<KnowledgeBase>(
    `/knowledge/knowledge-bases/${kbId}`
  );
};

// 更新知识库
export const updateKnowledgeBase = (kbId: number, params: UpdateKnowledgeBaseParams) => {
  const queryParams = new URLSearchParams();
  if (params.name) queryParams.append("name", params.name);
  if (params.description) queryParams.append("description", params.description);

  return client.put<ApiResponse<KnowledgeBase>>(
    `/knowledge/knowledge-bases/${kbId}?${queryParams}`
  );
};

// 删除知识库
export const deleteKnowledgeBase = (kbId: number) => {
  return client.delete(`/knowledge/knowledge-bases/${kbId}`);
};

/**
 * 文档管理 API
 */

// 上传文档
export const uploadDocument = (kbId: number, file: File) => {
  const formData = new FormData();
  formData.append("file", file);

  return client.post<ApiResponse<KnowledgeDocument>>(
    `/knowledge/knowledge-bases/${kbId}/documents/upload`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    }
  );
};

// 列出文档
export const listDocuments = (kbId: number, status?: string, page = 1, pageSize = 20) => {
  let url = `/knowledge/knowledge-bases/${kbId}/documents?page=${page}&page_size=${pageSize}`;
  if (status) url += `&status=${status}`;

  return client.get<PaginatedData<KnowledgeDocument>>(url);
};

// 获取文档详情
export const getDocument = (docId: number) => {
  return client.get<ApiResponse<KnowledgeDocument>>(
    `/knowledge/documents/${docId}`
  );
};

// 删除文档
export const deleteDocument = (docId: number) => {
  return client.delete(`/knowledge/documents/${docId}`);
};

/**
 * 分块管理 API
 */

// 获取文档分块
export const getDocumentChunks = (docId: number, page = 1, pageSize = 20) => {
  return client.get<{
    items: KnowledgeChunk[];
    total: number;
    page: number;
    page_size: number;
  }>(
    `/knowledge/documents/${docId}/chunks?page=${page}&page_size=${pageSize}`
  );
};

/**
 * 向量检索 API
 */

// 检索知识库
export const searchKnowledgeBase = (kbId: number, params: SearchParams) => {
  const queryParams = new URLSearchParams();
  queryParams.append("query", params.query);
  if (params.top_k !== undefined) queryParams.append("top_k", params.top_k.toString());
  if (params.score_threshold !== undefined) queryParams.append("score_threshold", params.score_threshold.toString());

  return client.post<SearchResult[]>(
    `/knowledge/knowledge-bases/${kbId}/search?${queryParams}`
  );
};
