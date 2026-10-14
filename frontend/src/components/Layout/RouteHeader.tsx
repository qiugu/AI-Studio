import type { ReactNode } from 'react'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { Button, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import './RouteHeader.css'

const { Text, Title } = Typography

interface RouteHeaderProps {
  title: ReactNode
  backTo: string
  backLabel?: string
  eyebrow?: string
  description?: ReactNode
  extra?: ReactNode
  compact?: boolean
}

/**
 * Contextual route navigation for detail, editor and execution pages.
 * Every contextual page declares its owning module explicitly instead of
 * depending on the browser history stack.
 */
export default function RouteHeader({
  title,
  backTo,
  backLabel = '返回列表',
  eyebrow,
  description,
  extra,
  compact = false,
}: RouteHeaderProps) {
  const navigate = useNavigate()

  return (
    <div className={`route-header ${compact ? 'route-header--compact' : ''}`}>
      <Button
        type="text"
        className="route-header__back"
        icon={<ArrowLeftOutlined />}
        aria-label={backLabel}
        onClick={() => navigate(backTo)}
      >
        {backLabel}
      </Button>
      <div className="route-header__content">
        {eyebrow && !compact && <Text className="route-header__eyebrow">{eyebrow}</Text>}
        <Title level={3} className="route-header__title">
          {title}
        </Title>
        {description && <Text className="route-header__description">{description}</Text>}
      </div>
      {extra && <div className="route-header__extra">{extra}</div>}
    </div>
  )
}
