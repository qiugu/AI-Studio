import { Position } from 'reactflow'

export const getLoopHandleDefinitions = () => [
  { id: 'loop-body', position: Position.Right, label: '循环体' },
  { id: 'loop-done', position: Position.Bottom, label: '完成后' },
]
