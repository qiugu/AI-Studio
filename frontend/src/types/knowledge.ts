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

/**
 * 分块类型。取值域由后端 `app.utils.document.CHUNK_TYPES` 定义，两边必须一致。
 *
 * 它是**后端解析层给前端选渲染方式的唯一依据**：`table` 需要按列渲染（按纯文本
 * 渲染会丢掉整张表的行列结构），`code` 需要保留换行与缩进（按 Markdown 段落渲染
 * 会把代码压成一行）。`title` 仅用于加大字号，`image` 为图片占位（后端尚未产出）。
 *
 * 历史数据由迁移回填为 `text`，因此运行时**不会**是 undefined；`?:` 只是为了让
 * 旧缓存与 mock 数据仍能通过类型检查。
 */
export type ChunkType = "text" | "table" | "code" | "title" | "image";

export interface KnowledgeChunk {
  id: string;
  content: string;
  chunk_index: number;
  /**
   * 块类型。**它是仓库里唯一能区分「这段文本是不是表格/代码」的字段**——不能从
   * `content` 反推：块只保存纯文本，表格与正文在纯文本层面无法区分。
   */
  chunk_type?: ChunkType;
  /**
   * 覆盖页码的**闭区间**（1 基）。块可以跨页，单值只能表达起点，故用区间表达：
   * 单页块两者相等，非 PDF 两者同为 undefined。呈现规则见 `@/utils/citation`。
   */
  source_page?: number;
  source_page_end?: number;
  /** 标题路径（md/docx）；PDF 恒为 undefined */
  heading_path?: string;
  /**
   * `heading_path` 是否**粗于**本块的实际覆盖范围。
   *
   * 为 true 表示本块只覆盖了若干兄弟子节、而 `heading_path` 只能标到它们的公共
   * 祖先（块内并无该祖先自身的内容），应呈现为「§A 等小节」。
   */
  heading_path_mixed?: boolean;
  created_at: string;
}

export interface SearchResult {
  id: string;
  content: string;
  score: number;
  doc_id: string;
  doc_name?: string;
  chunk_index: number;
  /** 块类型，语义同 `KnowledgeChunk.chunk_type` */
  chunk_type?: ChunkType;
  /** 出处区间与粗化标记，语义同 `KnowledgeChunk`；呈现用 `@/utils/citation` */
  source_page?: number;
  source_page_end?: number;
  heading_path?: string;
  heading_path_mixed?: boolean;
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
  /**
   * P4 上下文装配的产物：**应当喂给 LLM 的文本**。
   *
   * = 出处标记（`context_header`）+ 含前后邻块的窗口正文。与 `content` 分开是刻意
   * 的：`content` 仍是块原文，界面展示与「复制引用」都应继续用它，直接把
   * `llm_content` 渲染出来会让用户看到 `[《x.pdf》| p.3–4]` 这类内部标记。
   * 两个开关全关时它与 `content` 逐字符相等。
   */
  llm_content?: string;
  /** `llm_content` 前置的出处标记行；无可标注的出处时为 undefined */
  context_header?: string;
  /** 是否真的拼入了邻块（开关关闭或本块无邻块均为 false，不细分） */
  context_expanded?: boolean;
  /**
   * **响应内编号**（该次检索响应数组下标 + 1），仅在本条响应内有效。
   *
   * 与 Agent 侧 `Citation.marker`（**轮次内编号**，跨工具调用单调递增）是两套
   * 作用域，数值可能不同——不要为了「让数字对上」而引入跨请求状态。
   */
  marker?: number;
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
