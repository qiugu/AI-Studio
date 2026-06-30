/**
 * 知识库列表页面
 */

import { useState, useEffect } from "react";
import { Card, Button, Space, Popconfirm, Spin, Empty, Input, Modal, Form, Select } from "antd";
import { DeleteOutlined, EditOutlined, FolderOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import * as kbApi from "@/api/knowledge";
import { type KnowledgeBase } from "@/types/knowledge";

export default function KnowledgeList() {
  const navigate = useNavigate();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null);
  const [form] = Form.useForm();

  // 加载知识库列表
  useEffect(() => {
    loadKnowledgeBases();
  }, []);

  const loadKnowledgeBases = async () => {
    setLoading(true);
    try {
      const { data } = await kbApi.listKnowledgeBases();
      setKbs(data.items);
    } catch (error) {
      console.error("Failed to load knowledge bases:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateKb = async (values: any) => {
    setConfirmLoading(true)
    try {
      await kbApi.createKnowledgeBase({
        name: values.name,
        description: values.description,
        embedding_model: values.embedding_model || "text-embedding-3-small",
      });
      setCreateModalVisible(false);
      form.resetFields();
      loadKnowledgeBases();
    } catch (error) {
      console.error("Failed to create knowledge base:", error);
    } finally {
      setConfirmLoading(false)
    }
  };

  const handleEditKb = async (values: any) => {
    if (!editingKb) return;
    try {
      await kbApi.updateKnowledgeBase(editingKb.id, {
        name: values.name,
        description: values.description,
      });
      setCreateModalVisible(false);
      setEditingKb(null);
      form.resetFields();
      loadKnowledgeBases();
    } catch (error) {
      console.error("Failed to update knowledge base:", error);
    }
  };

  const handleDeleteKb = async (kb: KnowledgeBase) => {
    try {
      await kbApi.deleteKnowledgeBase(kb.id);
      loadKnowledgeBases();
    } catch (error) {
      console.error("Failed to delete knowledge base:", error);
    }
  };

  const handleOpenCreateModal = () => {
    setEditingKb(null);
    form.resetFields();
    setCreateModalVisible(true);
  };

  const handleOpenEditModal = (kb: KnowledgeBase) => {
    setEditingKb(kb);
    form.setFieldsValue({
      name: kb.name,
      description: kb.description,
    });
    setCreateModalVisible(true);
  };

  return (
    <div style={{ padding: "24px" }}>
      <div style={{ marginBottom: "24px" }}>
        <Space>
          <h2>知识库管理</h2>
          <Button type="primary" onClick={handleOpenCreateModal}>
            创建知识库
          </Button>
        </Space>
      </div>

      <Spin spinning={loading}>
        {kbs.length === 0 ? (
          <Empty description="暂无知识库，点击上方按钮创建" style={{ marginTop: "48px" }} />
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "16px" }}>
            {kbs.map((kb) => (
              <Card
                key={kb.id}
                hoverable
                onClick={() => navigate(`/knowledge/${kb.id}`)}
                style={{ cursor: "pointer" }}
                cover={
                  <div
                    style={{
                      height: "120px",
                      background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <FolderOutlined style={{ fontSize: "48px", color: "white" }} />
                  </div>
                }
              >
                <Card.Meta
                  title={kb.name}
                  description={kb.description || "暂无描述"}
                  style={{ marginBottom: "12px" }}
                />
                <div style={{ marginBottom: "12px", fontSize: "12px", color: "#666" }}>
                  <div>📄 文档: {kb.document_count}</div>
                  <div>🔤 分块: {kb.chunk_count}</div>
                  <div>🤖 模型: {kb.embedding_model}</div>
                </div>
                <Space style={{ width: "100%" }} onClick={(e) => e.stopPropagation()}>
                  <Button
                    size="small"
                    type="text"
                    icon={<EditOutlined />}
                    onClick={() => handleOpenEditModal(kb)}
                  />
                  <Popconfirm
                    title="删除知识库"
                    description="删除知识库会同时删除所有文档和向量数据，是否确认？"
                    onConfirm={() => handleDeleteKb(kb)}
                    okText="是"
                    cancelText="否"
                  >
                    <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              </Card>
            ))}
          </div>
        )}
      </Spin>

      {/* 创建/编辑知识库 Modal */}
      <Modal
        title={editingKb ? "编辑知识库" : "创建知识库"}
        open={createModalVisible}
        onOk={() => form.submit()}
        confirmLoading={confirmLoading}
        onCancel={() => {
          setCreateModalVisible(false);
          setEditingKb(null);
        }}
        okText="确定"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={editingKb ? handleEditKb : handleCreateKb}
        >
          <Form.Item
            label="知识库名称"
            name="name"
            rules={[{ required: true, message: "请输入知识库名称" }]}
          >
            <Input placeholder="例如: 产品文档" />
          </Form.Item>

          <Form.Item
            label="描述"
            name="description"
            rules={[{ max: 500, message: "描述不超过500个字符" }]}
          >
            <Input.TextArea rows={3} placeholder="简要描述知识库的用途" />
          </Form.Item>

          {!editingKb && (
            <Form.Item
              label="Embedding 模型"
              name="embedding_model"
              initialValue="BAAI/bge-large-zh-v1.5"
            >
              <Select
                options={[
                  { label: "BAAI/bge-large-zh-v1.5", value: "BAAI/bge-large-zh-v1.5" },
                  { label: "BAAI/bge-m3", value: "BAAI/bge-m3" },
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
