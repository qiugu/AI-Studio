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
import type { ColumnsType } from "antd/es/table";
import type { RcFile } from "antd/es/upload";

const DocumentStatusTag: Record<string, any> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "处理中" },
  completed: { color: "success", label: "完成" },
  failed: { color: "error", label: "失败" },
};

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
      const { data } = await kbApi.getKnowledgeBase(Number(kbId));
      setKb(data);
    } catch (error) {
      console.error("Failed to load knowledge base:", error);
      message.error("加载知识库失败");
    }
  };

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const { data } = await kbApi.listDocuments(Number(kbId));
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
      await kbApi.uploadDocument(Number(kbId), file);
      message.success("文档上传成功，正在处理中...");
      loadDocuments();
      loadKnowledgeBase();
    } catch (error) {
      console.error("Failed to upload document:", error);
      message.error("文档上传失败");
    } finally {
      setUploading(false);
    }
    return false; // 禁止自动上传
  };

  const handleDeleteDocument = async (docId: number) => {
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
      const { data } = await kbApi.searchKnowledgeBase(Number(kbId), {
        query: searchQuery,
        top_k: 10,
        score_threshold: 0.3,
      });
      setSearchResults(data);
    } catch (error) {
      console.error("Failed to search:", error);
      message.error("检索失败");
    } finally {
      setChunksLoading(false);
    }
  };

  const handleViewChunks = async (docId: number) => {
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
                      <h3>检索结果 ({searchResults.length})</h3>
                      <List
                        dataSource={searchResults}
                        renderItem={(result) => (
                          <List.Item>
                            <List.Item.Meta
                              title={
                                <>
                                  <span style={{ marginRight: "12px" }}>
                                    分块 #{result.chunk_index}
                                  </span>
                                  <Tag color="blue">{result.doc_name}</Tag>
                                  <span style={{ color: "#666", marginLeft: "12px" }}>
                                    相似度: {(result.score * 100).toFixed(1)}%
                                  </span>
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
                                  {result.content.substring(0, 200)}
                                  {result.content.length > 200 && "..."}
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
                  title={`分块 #${chunk.chunk_index}${chunk.source_page ? ` (第 ${chunk.source_page} 页)` : ""}`}
                  description={
                    <div
                      style={{
                        color: "#666",
                        lineHeight: "1.6",
                        marginTop: "8px",
                        whiteSpace: "pre-wrap",
                      }}
                    >
                      {chunk.content}
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
