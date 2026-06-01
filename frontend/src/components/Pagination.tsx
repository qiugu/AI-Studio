import { Pagination as AntPagination } from 'antd'
import type { PageParams } from '@/types/api'

interface PaginationProps {
  total: number
  current: number
  pageSize: number
  onChange: (page: number, pageSize: number) => void
  pageParams?: Partial<PageParams>
}

export default function Pagination({
  total,
  current,
  pageSize,
  onChange,
}: PaginationProps) {
  return (
    <AntPagination
      total={total}
      current={current}
      pageSize={pageSize}
      onChange={onChange}
      showSizeChanger
      showQuickJumper
      showTotal={(total) => `共 ${total} 条`}
      style={{ marginTop: 16, textAlign: 'right' }}
    />
  )
}