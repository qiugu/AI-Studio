/**
 * 知识库详情页面
 */

import { useState, useEffect } from "react";
import {
  Card,
  Button,
  Space,
  Spin,
  Tabs,
  Table,
  Tag,
  Input,
  Popconfirm,
  message,
  Upload,
  Drawer,
  List,
} from "antd";
import {
  DeleteOutlined,
  UploadOutlined,
  SearchOutlined,
  FileTextOutlined,
  ArrowLeftOutlined,
} from "@ant-design/icons";
import { useParams, useNavigate } from "react-router-dom";
import * as kbApi from "@/api/knowledge";
import { type KnowledgeBase, type KnowledgeDocument, type KnowledgeChunk, type SearchResult } from "@/types/knowledge";
import { formatCitation } from "@/utils/citation";
import type { ColumnsType } from "antd/es/table";
import type { RcFile } from "antd/es/upload";
import { getErrorMessage } from "@/utils/request";
import { CitationMarker } from "@/components/CitationBadge";
import ChunkContentView from "@/components/ChunkContentView";

const DocumentStatusTag: Record<string, any> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "处理中" },
  completed: { color: "success", label: "完成" },
  failed: { color: "error", label: "失败" },
};

/**
 * 检索请求的召回条数。
 *
 * 后端会先超额召回再按内容去重，因此**返回条数允许少于该值**：库里同一段落存在
 * 等值副本时，副本会被折叠成一条，折叠后的数量就是可用内容的上限。界面据此提示
 * 用户「少于 N 条」的原因，避免把「去重生效」误读为「检索坏了」。
 */
const SEARCH_TOP_K = 10;

export default function KnowledgeDetail() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [selectedChunks, setSelectedChunks] = useState<KnowledgeChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksDrawerVisible, setChunksDrawerVisible] = useState(false);

  useEffect(() => {
    if (kbId) {
      loadKnowledgeBase();
      loadDocuments();
    }
  }, [kbId]);

  const loadKnowledgeBase = async () => {
    try {
      const { data } = await kbApi.getKnowledgeBase(kbId || '');
      setKb(data);
    } catch (error) {
      console.error("Failed to load knowledge base:", error);
      message.error("加载知识库失败");
    }
  };

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const { data } = await kbApi.listDocuments(kbId || '');
      setDocuments(data.items);
    } catch (error) {
      console.error("Failed to load documents:", error);
      message.error("加载文档列表失败");
    } finally {
      setLoading(false);
    }
  };

  const handleUploadDocument = async (file: RcFile) => {
    setUploading(true);
    try {
      await kbApi.uploadDocument(kbId || '', file, { _suppressErrorMessage: true });
      message.success("文档上传成功，正在处理中...");
      loadDocuments();
      loadKnowledgeBase();
    } catch (error) {
      console.error("Failed to upload document:", error);
      // 上传失败几乎都是可预期的业务拒绝（类型不符、同名同大小重复上传等），
      // 后端 message 已包含具体原因与处置建议，直接透出比笼统的「上传失败」有用。
      message.error(getErrorMessage(error));
    } finally {
      setUploading(false);
    }
    return false; // 禁止自动上传
  };

  const handleDeleteDocument = async (docId: string) => {
    try {
      await kbApi.deleteDocument(docId);
      message.success("文档已删除");
      loadDocuments();
      loadKnowledgeBase();
    } catch (error) {
      console.error("Failed to delete document:", error);
      message.error("删除文档失败");
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      message.warning("请输入搜索内容");
      return;
    }

    setChunksLoading(true);
    try {
      const { data } = await kbApi.searchKnowledgeBase(kbId || '', {
        query: searchQuery,
        top_k: SEARCH_TOP_K,
        score_threshold: 0.3,
      });
      setSearchResults(data);
    } catch (error) {
      console.error("Failed to search:", error);
      message.error(getErrorMessage(error));
    } finally {
      setChunksLoading(false);
    }
  };

  const handleViewChunks = async (docId: string) => {
    setChunksLoading(true);
    try {
      const { data } = await kbApi.getDocumentChunks(docId);
      setSelectedChunks(data.items);
      setChunksDrawerVisible(true);
    } catch (error) {
      console.error("Failed to load chunks:", error);
      message.error("加载分块失败");
    } finally {
      setChunksLoading(false);
    }
  };

  const documentColumns: ColumnsType<KnowledgeDocument> = [
    {
      title: "文件名",
      dataIndex: "file_name",
      key: "file_name",
      render: (_, record) => (
        <Space>
          <FileTextOutlined />
          {record.file_name}
        </Space>
      ),
    },
    {
      title: "类型",
      dataIndex: "file_type",
      key: "file_type",
      width: 80,
    },
    {
      title: "大小",
      dataIndex: "file_size",
      key: "file_size",
      width: 180,
      render: (size) => `${(size / 1024).toFixed(2)} KB`,
    },
    {
      title: "分块数",
      dataIndex: "chunk_count",
      key: "chunk_count",
      width: 80,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (status) => (
        <Tag color={DocumentStatusTag[status].color}>
          {DocumentStatusTag[status].label}
        </Tag>
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 150,
      render: (_, record) => (
        <Space>
          {record.status === "completed" && (
            <Button size="small" type="link" onClick={() => handleViewChunks(record.id)}>
              查看分块
            </Button>
          )}
          <Popconfirm
            title="删除文档"
            description="删除文档会同时删除对应的向量数据，是否确认？"
            onConfirm={() => handleDeleteDocument(record.id)}
            okText="是"
            cancelText="否"
          >
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 本次检索中被折叠掉的等值副本总数：用于向用户解释结果条数与「内容重复的文档」
  // 之间的关系，而不是让用户对着变少的条数自行猜测。
  const foldedCopyCount = searchResults.reduce(
    (sum, result) => sum + (result.duplicate_count || 0),
    0
  );

  if (!kb) {
    return <Spin />;
  }

  return (
    <div style={{ padding: "24px" }}>
      {/* 顶部导航 */}
      <div style={{ marginBottom: "24px" }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/knowledge")} />
        <h2 style={{ marginTop: "12px" }}>{kb.name}</h2>
        {kb.description && <p style={{ color: "#666" }}>{kb.description}</p>}
      </div>

      {/* 统计信息 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "16px", marginBottom: "24px" }}>
        <Card>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "24px", fontWeight: "bold" }}>{kb.document_count}</div>
            <div style={{ fontSize: "14px", color: "#666" }}>文档数</div>
          </div>
        </Card>
        <Card>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "24px", fontWeight: "bold" }}>{kb.chunk_count}</div>
            <div style={{ fontSize: "14px", color: "#666" }}>总分块数</div>
          </div>
        </Card>
        <Card>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "14px", color: "#666" }}>{kb.embedding_model}</div>
            <div style={{ fontSize: "12px", color: "#999" }}>Embedding模型</div>
          </div>
        </Card>
      </div>

      {/* 标签页 */}
      <Tabs
        items={[
          {
            key: "documents",
            label: "文档管理",
            children: (
              <Card>
                <Space style={{ marginBottom: "16px", width: "100%" }} direction="vertical">
                  <Upload
                    beforeUpload={handleUploadDocument}
                    maxCount={1}
                    accept=".txt,.pdf,.docx,.md"
                    disabled={uploading}
                  >
                    <Button icon={<UploadOutlined />} loading={uploading}>
                      上传文档
                    </Button>
                  </Upload>
                  <div style={{ fontSize: "12px", color: "#999" }}>
                    支持格式: TXT, PDF, DOCX, Markdown
                  </div>
                </Space>

                <Table
                  columns={documentColumns}
                  dataSource={documents}
                  loading={loading}
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                />
              </Card>
            ),
          },
          {
            key: "search",
            label: "语义检索",
            children: (
              <Card>
                <Space direction="vertical" style={{ width: "100%" }}>
                  <Input.Search
                    placeholder="输入查询文本"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onSearch={handleSearch}
                    prefix={<SearchOutlined />}
                    loading={chunksLoading}
                  />

                  {searchResults.length > 0 && (
                    <div>
                      <h3>
                        检索结果 ({searchResults.length}
                        {searchResults.length < SEARCH_TOP_K ? ` / ${SEARCH_TOP_K}` : ""})
                      </h3>
                      {foldedCopyCount > 0 && (
                        <div
                          style={{
                            fontSize: "12px",
                            color: "#999",
                            marginBottom: "8px",
                          }}
                        >
                          已折叠 {foldedCopyCount} 条内容重复的分块：知识库中存在内容相同的
                          重复文档，同一内容只保留相似度最高的那一条。结果条数少于{" "}
                          {SEARCH_TOP_K} 表示去重后可用内容不足，可考虑清理重复文档。
                        </div>
                      )}
                      <List
                        dataSource={searchResults}
                        renderItem={(result) => (
                          <List.Item key={result.id}>
                            <List.Item.Meta
                              title={
                                <>
                                  {/* 响应内编号：与 Agent 角标同款视觉，但作用域不同
                                      （仅本条响应内有效），故用不可点击的 CitationMarker */}
                                  {result.marker != null && (
                                    <span style={{ marginRight: "10px" }}>
                                      <CitationMarker
                                        marker={result.marker}
                                        title="本条在本次检索结果中的编号（响应内编号）"
                                      />
                                    </span>
                                  )}
                                  <span style={{ marginRight: "12px" }}>
                                    分块 #{result.chunk_index}
                                  </span>
                                  <Tag color="blue">{result.doc_name}</Tag>
                                  {formatCitation(result) && (
                                    <Tag color="geekblue" style={{ marginLeft: "12px" }}>
                                      {formatCitation(result)}
                                    </Tag>
                                  )}
                                  <span style={{ color: "#666", marginLeft: "12px" }}>
                                    相似度: {(result.score * 100).toFixed(1)}%
                                  </span>
                                  {!!result.duplicate_count && (
                                    <Tag color="orange" style={{ marginLeft: "12px" }}>
                                      另有 {result.duplicate_count} 份同内容副本
                                    </Tag>
                                  )}
                                </>
                              }
                              description={
                                <div
                                  title={result.content}
                                  style={{
                                    color: "#666",
                                    lineHeight: "1.6",
                                    marginTop: "8px",
                                  }}
                                >
                                  {/* 预览按**块类型**渲染：表格折叠成结构摘要（截断
                                      一张表只剩一堆竖线，毫无信息），代码保留换行。
                                      其余类型仍是纯文本预览，与改动前一致。 */}
                                  <ChunkContentView
                                    content={result.content}
                                    chunkType={result.chunk_type}
                                    previewChars={200}
                                  />
                                </div>
                              }
                            />
                          </List.Item>
                        )}
                      />
                    </div>
                  )}
                </Space>
              </Card>
            ),
          },
        ]}
      />

      {/* 分块查看 Drawer */}
      <Drawer
        title="文档分块"
        placement="right"
        onClose={() => setChunksDrawerVisible(false)}
        open={chunksDrawerVisible}
        width={600}
      >
        <Spin spinning={chunksLoading}>
          <List
            dataSource={selectedChunks}
            renderItem={(chunk) => (
              <List.Item key={chunk.id}>
                <List.Item.Meta
                  title={`分块 #${chunk.chunk_index}${
                    formatCitation(chunk) ? ` (${formatCitation(chunk)})` : ""
                  }`}
                  description={
                    <div
                      style={{
                        color: "#666",
                        lineHeight: "1.6",
                        marginTop: "8px",
                      }}
                    >
                      {/* 完整内容同样按块类型渲染：表格给真实 <table>（此前是
                          「一堆竖线」的纯文本，正是本次修复的原始报障）。 */}
                      <ChunkContentView content={chunk.content} chunkType={chunk.chunk_type} />
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        </Spin>
      </Drawer>
    </div>
  );
}
