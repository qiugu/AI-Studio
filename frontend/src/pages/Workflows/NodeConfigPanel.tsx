import React from 'react'
import { Drawer, Form, Input, Select, InputNumber, Button, Space, message } from 'antd'
import type { Node } from 'reactflow'
import type { NodeType, WorkflowNodeConfig } from '../../types/workflow'

interface NodeConfigPanelProps {
  visible: boolean
  node: Node | null
  onClose: () => void
  onSave: (nodeId: string, data: { name: string; config: WorkflowNodeConfig }) => void
}

const NodeConfigPanel: React.FC<NodeConfigPanelProps> = ({
  visible,
  node,
  onClose,
  onSave,
}) => {
  const [form] = Form.useForm()

  React.useEffect(() => {
    if (node) {
      form.setFieldsValue({
        name: node.data.name,
        ...node.data.config,
      })
    }
  }, [node, form])

  const handleSave = () => {
    form.validateFields().then((values) => {
      onSave(node!.id, {
        name: values.name,
        config: values,
      })
      message.success('节点配置已保存')
      onClose()
    })
  }

  const renderConfigFields = (nodeType: NodeType) => {
    switch (nodeType) {
      case 'llm':
        return (
          <>
            <Form.Item label="模型ID" name="model_id" rules={[{ required: true }]}>
              <InputNumber />
            </Form.Item>
            <Form.Item label="Prompt模板" name="prompt_template" rules={[{ required: true }]}>
              <Input.TextArea rows={6} placeholder="使用 {{variable}} 插入变量" />
            </Form.Item>
            <Form.Item label="Temperature" name="temperature">
              <InputNumber min={0} max={2} step={0.1} />
            </Form.Item>
            <Form.Item label="Max Tokens" name="max_tokens">
              <InputNumber min={1} max={8000} />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="output" />
            </Form.Item>
          </>
        )

      case 'knowledge':
        return (
          <>
            <Form.Item label="知识库ID" name="knowledge_base_id" rules={[{ required: true }]}>
              <InputNumber />
            </Form.Item>
            <Form.Item label="查询模板" name="query_template" rules={[{ required: true }]}>
              <Input.TextArea rows={4} placeholder="使用 {{variable}} 插入变量" />
            </Form.Item>
            <Form.Item label="Top K" name="top_k">
              <InputNumber min={1} max={20} />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="knowledge_result" />
            </Form.Item>
          </>
        )

      case 'condition':
        return (
          <>
            <Form.List name="conditions">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                      <Form.Item
                        {...restField}
                        name={[name, 'expression']}
                        rules={[{ required: true, message: '请输入条件表达式' }]}
                      >
                        <Input placeholder="{{output.value > 10}}" />
                      </Form.Item>
                      <Form.Item
                        {...restField}
                        name={[name, 'label']}
                        rules={[{ required: true, message: '请输入标签' }]}
                      >
                        <Input placeholder="大于10" />
                      </Form.Item>
                      <Button onClick={() => remove(name)}>删除</Button>
                    </Space>
                  ))}
                  <Button onClick={() => add()}>添加条件</Button>
                </>
              )}
            </Form.List>
          </>
        )

      case 'code':
        return (
          <>
            <Form.Item label="Python代码" name="code" rules={[{ required: true }]}>
              <Input.TextArea
                rows={10}
                placeholder="result = input_data['value'] * 2\nreturn result"
              />
            </Form.Item>
            <Form.Item label="输入变量" name="input_variables">
              <Select mode="tags" placeholder="选择或输入变量名" />
            </Form.Item>
            <Form.Item label="输出变量名" name="output_variable">
              <Input placeholder="result" />
            </Form.Item>
          </>
        )

      case 'variable':
        return (
          <>
            <Form.List name="variables">
              {(fields, { add, remove }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <Space key={key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                      <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true }]}>
                        <Input placeholder="变量名" />
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'type']} rules={[{ required: true }]}>
                        <Select style={{ width: 120 }}>
                          <Select.Option value="static">静态值</Select.Option>
                          <Select.Option value="context">上下文引用</Select.Option>
                          <Select.Option value="expression">表达式</Select.Option>
                        </Select>
                      </Form.Item>
                      <Form.Item {...restField} name={[name, 'value']}>
                        <Input placeholder="值" />
                      </Form.Item>
                      <Button onClick={() => remove(name)}>删除</Button>
                    </Space>
                  ))}
                  <Button onClick={() => add()}>添加变量</Button>
                </>
              )}
            </Form.List>
          </>
        )

      default:
        return <div>此节点类型暂无配置项</div>
    }
  }

  return (
    <Drawer
      title="节点配置"
      width={400}
      open={visible}
      onClose={onClose}
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={handleSave}>
            保存
          </Button>
        </Space>
      }
    >
      {node && (
        <Form form={form} layout="vertical">
          <Form.Item label="节点名称" name="name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>

          {renderConfigFields(node.type as NodeType)}
        </Form>
      )}
    </Drawer>
  )
}

export default NodeConfigPanel