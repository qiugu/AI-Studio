import { useState } from 'react'
import type { PaginatedData } from '@/types/api'
import type { PageParams } from '@/types/api'

const DEFAULT_PAGE = 1
const DEFAULT_PAGE_SIZE = 20

export function usePagination<T>() {
  const [pagination, setPagination] = useState<PageParams>({
    page: DEFAULT_PAGE,
    page_size: DEFAULT_PAGE_SIZE,
  })
  const [data, setData] = useState<PaginatedData<T> | null>(null)
  const [loading, setLoading] = useState(false)

  const onChange = (page: number, pageSize: number) => {
    setPagination({ page, page_size: pageSize })
  }

  const total = data?.total ?? 0

  return {
    pagination,
    data,
    loading,
    setData,
    setLoading,
    onChange,
    total,
    current: pagination.page ?? DEFAULT_PAGE,
    pageSize: pagination.page_size ?? DEFAULT_PAGE_SIZE,
  }
}