import { Button, Dropdown, Badge } from 'antd'
import type { MenuProps } from 'antd'
import { PlusOutlined, MessageOutlined, MoreOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { Conversation } from '@/types/agent'
import { memo, useMemo } from 'react'

interface ConversationListProps {
  conversations: Conversation[]
  currentConversationId?: string
  onSelect: (conversation: Conversation) => void
  onCreateNew: () => void
  onDelete?: (conversation: Conversation) => void
  onRename?: (conversation: Conversation) => void
  showCreateButton?: boolean
}

// Extract last message preview
function getLastMessagePreview(conversation: Conversation): string {
  const userMessages = conversation.messages.filter(msg => msg.role === 'user')
  if (userMessages.length === 0) return ''

  const lastMessage = userMessages[userMessages.length - 1]
  const preview = lastMessage.content.trim()

  // Truncate to 50 characters
  return preview.length > 50 ? `${preview.substring(0, 50)}...` : preview
}

// Get message count badge
function getMessageCount(conversation: Conversation): number {
  return conversation.messages.filter(msg => msg.role !== 'system').length
}

// Group conversations by date periods
function groupConversationsByDate(conversations: Conversation[]) {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const thisWeekStart = new Date(today)
  thisWeekStart.setDate(thisWeekStart.getDate() - 7)

  const groups = {
    '今天': [] as Conversation[],
    '昨天': [] as Conversation[],
    '本周': [] as Conversation[],
    '更早': [] as Conversation[],
  }

  conversations.forEach((conv) => {
    const date = new Date(conv.updated_at)
    if (date >= today) {
      groups['今天'].push(conv)
    } else if (date >= yesterday) {
      groups['昨天'].push(conv)
    } else if (date >= thisWeekStart) {
      groups['本周'].push(conv)
    } else {
      groups['更早'].push(conv)
    }
  })

  return groups
}

// Format timestamp to relative time
function formatRelativeTime(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return '刚刚'
  if (diffMins < 60) return `${diffMins}分钟前`
  if (diffHours < 24) return `${diffHours}小时前`
  if (diffDays === 1) return '昨天'
  if (diffDays < 7) return `${diffDays}天前`

  return date.toLocaleDateString('zh-CN', {
    month: 'numeric',
    day: 'numeric'
  })
}

// Single conversation item component (memoized for performance)
const ConversationItem = memo(function ConversationItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
  onRename,
}: {
  conversation: Conversation
  isActive: boolean
  onSelect: () => void
  onDelete?: () => void
  onRename?: () => void
}) {
  const messagePreview = getLastMessagePreview(conversation)
  const messageCount = getMessageCount(conversation)

  // Dropdown menu items
  const menuItems: MenuProps['items'] = [
    {
      key: 'rename',
      icon: <EditOutlined />,
      label: '重命名',
      onClick: onRename,
    },
    {
      key: 'delete',
      icon: <DeleteOutlined />,
      label: '删除',
      danger: true,
      onClick: onDelete,
    },
  ]

  return (
    <div
      className={`conversation-item ${isActive ? 'conversation-item--active' : ''}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
    >
      <div className="conversation-item__body">
        {/* Title and badge */}
        <div className="conversation-item__title-row">
          <h3 className="conversation-item__title">
            {conversation.title}
          </h3>
          {messageCount > 0 && (
            <Badge
              count={messageCount}
              className="conversation-item__count"
              style={{
                backgroundColor: isActive ? 'var(--app-color-primary)' : 'var(--app-color-text-muted)',
                fontSize: '11px',
                fontWeight: '500',
                minWidth: '20px',
                height: '20px',
                lineHeight: '20px',
              }}
            />
          )}
        </div>

        {/* Message preview */}
        {messagePreview && (
          <p className="conversation-item__preview">
            {messagePreview}
          </p>
        )}
      </div>

      {/* Time and actions */}
      <div className="conversation-item__aside">
        <span className="conversation-item__time">
          {formatRelativeTime(conversation.updated_at)}
        </span>

        {/* Action menu */}
        {(onDelete || onRename) && (
          <Dropdown
            menu={{ items: menuItems }}
            trigger={['click']}
            placement="bottomRight"
          >
            <button
              className="conversation-item__more"
              onClick={(e) => e.stopPropagation()}
              aria-label="对话操作"
            >
              <MoreOutlined />
            </button>
          </Dropdown>
        )}
      </div>
    </div>
  )
})

export default function ConversationList({
  conversations,
  currentConversationId,
  onSelect,
  onCreateNew,
  onDelete,
  onRename,
  showCreateButton = true,
}: ConversationListProps) {
  const groupedConversations = useMemo(
    () => groupConversationsByDate(conversations),
    [conversations]
  )

  return (
    <div className="conversation-list">
      {/* New conversation button */}
      {showCreateButton && (
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={onCreateNew}
          block
          className="conversation-list__new"
        >
          新对话
        </Button>
      )}

      {/* Conversation list */}
      <div className="conversation-list__scroll">
        {conversations.length === 0 ? (
          <div className="conversation-list__empty">
            <div className="conversation-list__empty-icon">
              <MessageOutlined />
            </div>
            <p className="conversation-list__empty-title">暂无对话历史</p>
            <p className="conversation-list__empty-hint">
              创建一个会话，保留这次任务的上下文
            </p>
            <Button
              type="default"
              size="middle"
              icon={<PlusOutlined />}
              onClick={onCreateNew}
              className="conversation-list__empty-action"
            >
              创建首个对话
            </Button>
          </div>
        ) : (
          Object.entries(groupedConversations).map(([period, convs]) => {
            if (convs.length === 0) return null

            return (
              <div key={period} className="conversation-group">
                {/* Period header */}
                <div className="conversation-group__header">
                  <div className="conversation-group__label-row">
                    <span className="conversation-group__label">
                      {period}
                    </span>
                    <span className="conversation-group__count">
                      {convs.length} 个对话
                    </span>
                  </div>
                </div>

                {/* Conversation items */}
                <div className="conversation-group__items">
                  {convs.map((conv) => (
                    <ConversationItem
                      key={conv.id}
                      conversation={conv}
                      isActive={currentConversationId === conv.id}
                      onSelect={() => onSelect(conv)}
                      onDelete={onDelete ? () => onDelete(conv) : undefined}
                      onRename={onRename ? () => onRename(conv) : undefined}
                    />
                  ))}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
