/**
 * Agent创建/编辑表单页面
 */

import { useState, useEffect } from 'react'
import { Form, Input, Button, Select, InputNumber, Card, Space, message, Spin } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import * as agentApi from '@/api/agent'
import * as aiModelApi from '@/api/ai-model'
import { type AgentCreateRequest, type AgentUpdateRequest } from '@/types/agent'
import { type AIModel } from '@/types/ai-model'

const { TextArea } = Input

export default function AgentForm() {
  const navigate = useNavigate()
  const { agentId } = useParams()
  const isEdit = Boolean(agentId)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [models, setModels] = useState<AIModel[]>([])

  useEffect(() => {
    loadModels()
    if (isEdit) {
      loadAgent()
    }
  }, [agentId])

  const loadModels = async () => {
    try {
      const { data } = await aiModelApi.listModels({ page: 1, page_size: 100 })
      setModels(data.items)
    } catch (error) {
      console.error('Failed to load models:', error)
      message.error('加载AI模型列表失败')
    }
  }

  const loadAgent = async () => {
    setLoading(true)
    try {
      const { data } = await agentApi.getAgent(agentId || '')
      form.setFieldsValue({
        name: data.name,
        description: data.description,
        avatar: data.avatar,
        system_prompt: data.system_prompt,
        model_id: data.model_id,
        temperature: data.temperature,
        max_tokens: data.max_tokens,
        status: data.status,
      })
    } catch (error) {
      console.error('Failed to load agent:', error)
      message.error('加载Agent信息失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (values: any) => {
    setSubmitting(true)
    try {
      if (isEdit) {
        const updateData: AgentUpdateRequest = {
          name: values.name,
          description: values.description,
          avatar: values.avatar,
          system_prompt: values.system_prompt,
          model_id: values.model_id,
          temperature: values.temperature,
          max_tokens: values.max_tokens,
          status: values.status,
        }
        await agentApi.updateAgent(agentId || '', updateData)
        message.success('Agent已更新')
      } else {
        const createData: AgentCreateRequest = {
          name: values.name,
          description: values.description,
          avatar: values.avatar,
          system_prompt: values.system_prompt,
          model_id: values.model_id,
          temperature: values.temperature || 0.7,
          max_tokens: values.max_tokens || 2000,
          status: values.status || 'draft',
        }
        await agentApi.createAgent(createData)
        message.success('Agent已创建')
      }

      navigate('/agents')
    } catch (error) {
      console.error('Failed to submit:', error)
      message.error(isEdit ? '更新Agent失败' : '创建Agent失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ padding: '24px' }}>
      <Card title={isEdit ? '编辑Agent' : '创建Agent'}>
        <Spin spinning={loading}>
          <Form
            form={form}
            layout="vertical"
            onFinish={handleSubmit}
            initialValues={{
              temperature: 0.7,
              max_tokens: 2000,
              status: 'draft',
            }}
          >
            <Form.Item
              label="Agent名称"
              name="name"
              rules={[{ required: true, message: '请输入Agent名称' }]}
            >
              <Input placeholder="请输入Agent名称" maxLength={255} />
            </Form.Item>

            <Form.Item label="描述" name="description">
              <TextArea placeholder="请输入Agent描述" rows={3} maxLength={500} />
            </Form.Item>

            <Form.Item label="头像URL" name="avatar">
              <Input placeholder="请输入头像URL" maxLength={255} />
            </Form.Item>

            <Form.Item label="系统提示词" name="system_prompt">
              <TextArea placeholder="请输入系统提示词" rows={5} />
            </Form.Item>

            <Form.Item
              label="AI模型"
              name="model_id"
              rules={[{ required: true, message: '请选择AI模型' }]}
            >
              <Select placeholder="请选择AI模型">
                {models.map((model) => (
                  <Select.Option key={model.id} value={model.id}>
                    {model.display_name}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>

            <Form.Item label="Temperature" name="temperature">
              <InputNumber min={0} max={2} step={0.1} />
            </Form.Item>

            <Form.Item label="最大Token数" name="max_tokens">
              <InputNumber min={1} max={32000} />
            </Form.Item>

            <Form.Item label="状态" name="status">
              <Select>
                <Select.Option value="draft">草稿</Select.Option>
                <Select.Option value="published">已发布</Select.Option>
                <Select.Option value="archived">已归档</Select.Option>
              </Select>
            </Form.Item>

            <Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={submitting}>
                  {isEdit ? '更新' : '创建'}
                </Button>
                <Button onClick={() => navigate('/agents')}>取消</Button>
              </Space>
            </Form.Item>
          </Form>
        </Spin>
      </Card>
    </div>
  )
}