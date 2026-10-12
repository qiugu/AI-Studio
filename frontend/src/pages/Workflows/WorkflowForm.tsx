import React, { useState, useEffect, useCallback } from 'react'
import { Form, Input, Button, Card, message } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { createWorkflow, getWorkflow, updateWorkflow } from '../../api/workflow'
import type { WorkflowCreateRequest } from '../../types/workflow'
import RouteHeader from '@/components/Layout/RouteHeader'

const WorkflowForm: React.FC = () => {
  const navigate = useNavigate()
  const { workflowId } = useParams<{ workflowId: string }>()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const isEdit = !!workflowId

  const fetchWorkflow = useCallback(async () => {
    setLoading(true)
    try {
      const response = await getWorkflow(workflowId!)
      const workflow = response.data
      form.setFieldsValue({
        name: workflow.name,
        description: workflow.description,
      })
    } catch {
      message.error('获取工作流信息失败')
    } finally {
      setLoading(false)
    }
  }, [form, workflowId])

  useEffect(() => {
    if (isEdit) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 路由参数变化后加载远端资源
      void fetchWorkflow()
    }
  }, [isEdit, fetchWorkflow])

  const handleSubmit = async (values: WorkflowCreateRequest) => {
    setLoading(true)
    try {
      if (isEdit) {
        await updateWorkflow(workflowId!, values)
        message.success('工作流已更新')
        navigate(`/workflows/${workflowId}/edit`)
      } else {
        const response = await createWorkflow(values)
        const workflow = response.data
        message.success('工作流已创建')
        navigate(`/workflows/${workflow.id}/edit`)
      }
    } catch {
      message.error(isEdit ? '更新失败' : '创建失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <RouteHeader
        eyebrow="应用开发 / 工作流"
        title={isEdit ? '编辑工作流基本信息' : '创建工作流'}
        backTo="/workflows"
        backLabel="返回工作流列表"
      />
      <Card title={isEdit ? '编辑工作流基本信息' : '创建工作流'}>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{
            name: '',
            description: '',
          }}
        >
        <Form.Item
          label="工作流名称"
          name="name"
          rules={[{ required: true, message: '请输入工作流名称' }]}
        >
          <Input placeholder="请输入工作流名称" maxLength={255} />
        </Form.Item>

        <Form.Item
          label="描述"
          name="description"
        >
          <Input.TextArea
            placeholder="请输入工作流描述"
            rows={4}
            maxLength={1000}
          />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>
            {isEdit ? '保存' : '创建'}
          </Button>
          <Button style={{ marginLeft: 8 }} onClick={() => navigate('/workflows')}>
            取消
          </Button>
        </Form.Item>
        </Form>
      </Card>
    </>
  )
}

export default WorkflowForm
