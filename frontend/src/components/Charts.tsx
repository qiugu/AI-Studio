/**
 * 轻量 SVG 图表组件（无第三方图表库依赖）。
 * 用于阶段八 Dashboard：Token 趋势折线图、模型调用柱状图。
 */
import { useMemo } from 'react'

const WIDTH = 640
const HEIGHT = 220
const PADDING = { top: 16, right: 16, bottom: 28, left: 48 }

function makeScale(values: number[], maxOverride?: number) {
  const max = maxOverride ?? (values.length ? Math.max(...values) : 0)
  const min = 0
  const drawW = WIDTH - PADDING.left - PADDING.right
  const drawH = HEIGHT - PADDING.top - PADDING.bottom
  return {
    max: max || 1,
    drawW,
    drawH,
    x: (i: number, count: number) =>
      PADDING.left + (count <= 1 ? drawW / 2 : (i / (count - 1)) * drawW),
    y: (v: number) => PADDING.top + drawH - ((v - min) / (max || 1)) * drawH,
  }
}

export function LineChart({
  data,
  valueKey = 'total_tokens',
  color = '#1677ff',
}: {
  data: Array<Record<string, any>>
  valueKey?: string
  color?: string
}) {
  const points = useMemo(() => data.map((d) => Number(d[valueKey] ?? 0)), [data, valueKey])
  const scale = makeScale(points)

  if (!data.length) {
    return <div style={{ color: '#999', padding: 24 }}>暂无数据</div>
  }

  const coords = points.map((v, i) => ({
    x: scale.x(i, points.length),
    y: scale.y(v),
  }))
  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ')
  const areaPath =
    `M${coords[0].x},${PADDING.top + scale.drawH} ` +
    coords.map((c) => `L${c.x},${c.y}`).join(' ') +
    ` L${coords[coords.length - 1].x},${PADDING.top + scale.drawH} Z`

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" height={HEIGHT} role="img">
      {/* 网格线 */}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const y = PADDING.top + scale.drawH * t
        return (
          <line
            key={t}
            x1={PADDING.left}
            y1={y}
            x2={WIDTH - PADDING.right}
            y2={y}
            stroke="#f0f0f0"
            strokeWidth={1}
          />
        )
      })}
      <path d={areaPath} fill={color} fillOpacity={0.08} />
      <path d={path} fill="none" stroke={color} strokeWidth={2} />
      {coords.map((c, i) => (
        <circle key={i} cx={c.x} cy={c.y} r={2.5} fill={color} />
      ))}
      {/* X 轴标签（最多显示 6 个） */}
      {data.map((d, i) => {
        const step = Math.ceil(data.length / 6)
        if (i % step !== 0 && i !== data.length - 1) return null
        const label = String(d.date ?? '').slice(5)
        return (
          <text
            key={i}
            x={scale.x(i, points.length)}
            y={HEIGHT - 8}
            fontSize={10}
            fill="#888"
            textAnchor="middle"
          >
            {label}
          </text>
        )
      })}
    </svg>
  )
}

export function BarChart({
  data,
  valueKey = 'total_tokens',
  labelKey = 'key',
  color = '#52c41a',
}: {
  data: Array<Record<string, any>>
  valueKey?: string
  labelKey?: string
  color?: string
}) {
  const items = useMemo(
    () => data.map((d) => ({ label: String(d[labelKey] ?? '-'), value: Number(d[valueKey] ?? 0) })),
    [data, valueKey, labelKey]
  )
  const scale = makeScale(items.map((d) => d.value))

  if (!items.length) {
    return <div style={{ color: '#999', padding: 24 }}>暂无数据</div>
  }

  const barW = scale.drawW / items.length
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" height={HEIGHT} role="img">
      {items.map((d, i) => {
        const h = (d.value / scale.max) * scale.drawH
        const x = PADDING.left + i * barW + barW * 0.15
        const y = PADDING.top + scale.drawH - h
        const label = d.label.length > 8 ? `${d.label.slice(0, 8)}…` : d.label
        return (
          <g key={i}>
            <rect x={x} y={y} width={barW * 0.7} height={h} fill={color} rx={2} />
            <text x={x + barW * 0.35} y={y - 4} fontSize={10} fill="#555" textAnchor="middle">
              {d.value}
            </text>
            <text
              x={x + barW * 0.35}
              y={HEIGHT - 8}
              fontSize={10}
              fill="#888"
              textAnchor="middle"
            >
              {label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
