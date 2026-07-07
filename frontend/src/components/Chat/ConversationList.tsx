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
      className={`
        group relative flex items-start justify-between gap-4 px-4 py-3.5 rounded-lg cursor-pointer
        transition-all duration-200 ease-in-out border-l-3
        ${isActive
          ? 'bg-blue-50/40 border-blue-500 shadow-xs'
          : 'bg-white hover:bg-gray-50/80 border-transparent hover:border-gray-400'
        }
      `}
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
      <div className="flex-1 min-w-0">
        {/* Title and badge */}
        <div className="flex items-center gap-2.5 mb-2">
          <h3 className="font-semibold text-base text-gray-900 truncate flex-1 leading-snug">
            {conversation.title}
          </h3>
          {messageCount > 0 && (
            <Badge
              count={messageCount}
              style={{
                backgroundColor: isActive ? '#3b82f6' : '#9ca3af',
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
          <p className="text-sm text-gray-600 truncate leading-relaxed">
            {messagePreview}
          </p>
        )}
      </div>

      {/* Time and actions */}
      <div className="flex flex-col items-end gap-2 flex-shrink-0 mt-0.5">
        <span className="text-xs text-gray-500 tabular-nums">
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
              className={`
                opacity-0 group-hover:opacity-100 transition-opacity duration-200
                p-1.5 hover:bg-gray-100 rounded-md focus:outline-none focus-visible:ring-2
                focus-visible:ring-blue-500 focus-visible:ring-offset-2
              `}
              onClick={(e) => e.stopPropagation()}
              aria-label="对话操作"
            >
              <MoreOutlined className="text-base text-gray-600" />
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
}: ConversationListProps) {
  const groupedConversations = useMemo(
    () => groupConversationsByDate(conversations),
    [conversations]
  )

  return (
    <div className="flex flex-col h-full">
      {/* New conversation button */}
      <Button
        type="primary"
        icon={<PlusOutlined />}
        onClick={onCreateNew}
        block
        className="mb-5 h-11 font-semibold text-base shadow-sm hover:shadow-md transition-shadow"
      >
        新对话
      </Button>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto -mx-2 px-2 space-y-5">
        {conversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8 py-16">
            <div className="w-24 h-24 rounded-full bg-gradient-to-br from-gray-100 to-gray-50 flex items-center justify-center mb-6 shadow-sm">
              <MessageOutlined className="text-4xl text-gray-400" />
            </div>
            <p className="text-gray-700 mb-2 font-semibold text-lg">暂无对话历史</p>
            <p className="text-sm text-gray-500 mb-5 max-w-xs leading-relaxed">
              开始创建你的第一个对话，与 AI 助手交流想法
            </p>
            <Button
              type="default"
              size="large"
              icon={<PlusOutlined />}
              onClick={onCreateNew}
              className="shadow-sm hover:shadow-md transition-shadow"
            >
              创建对话
            </Button>
          </div>
        ) : (
          Object.entries(groupedConversations).map(([period, convs]) => {
            if (convs.length === 0) return null

            return (
              <div key={period} className="space-y-2">
                {/* Period header */}
                <div className="px-3 mb-3 sticky top-0 bg-white z-10 py-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-gray-600 uppercase tracking-wider">
                      {period}
                    </span>
                    <span className="text-xs text-gray-500 tabular-nums">
                      {convs.length} 个对话
                    </span>
                  </div>
                </div>

                {/* Conversation items */}
                <div className="space-y-2">
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