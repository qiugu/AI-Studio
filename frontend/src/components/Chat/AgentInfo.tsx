import type { Agent } from '@/types/agent'

interface AgentInfoProps {
  agent: Agent
}

export default function AgentInfo({ agent }: AgentInfoProps) {
  return (
    <div className="agent-info-card">
      <div className="agent-info-header">
        <div className="agent-info-content">
          <div>
            <h1 className="agent-name">{agent.name}</h1>
            {agent.description && (
              <p className="agent-description">{agent.description}</p>
            )}
          </div>

          {/* 系统提示词摘要和详情 */}
          {/* {agent.system_prompt && (
            <div className="agent-system-prompt">
              <Space size="small">
                <InfoCircleOutlined style={{ color: '#F59E0B', fontSize: '14px' }} />
                <Typography.Text
                  style={{
                    color: '#475569',
                    fontSize: '13px',
                    maxWidth: '600px',
                    display: 'inline-block',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  title={agent.system_prompt}
                >
                  {agent.system_prompt.substring(0, 80)}...
                </Typography.Text>
                <Button
                  type="link"
                  size="small"
                  icon={showSystemPrompt ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                  onClick={() => setShowSystemPrompt(!showSystemPrompt)}
                  style={{ color: '#F59E0B' }}
                >
                  {showSystemPrompt ? '隐藏详情' : '查看详情'}
                </Button>
              </Space>

              {showSystemPrompt && (
                <div style={{ marginTop: '12px' }}>
                  <MarkdownRenderer content={agent.system_prompt} />
                </div>
              )}
            </div>
          )} */}
        </div>
      </div>
    </div>
  )
}