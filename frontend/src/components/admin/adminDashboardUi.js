export const ADMIN_STATISTICS = Object.freeze([
  {
    key: 'user_count',
    label: 'Tổng người dùng',
    icon: 'users',
    tone: 'blue',
  },
  {
    key: 'document_count',
    label: 'Tổng tài liệu',
    icon: 'documents',
    tone: 'cyan',
  },
  {
    key: 'chat_session_count',
    label: 'Tổng cuộc hội thoại',
    icon: 'chat',
    tone: 'violet',
  },
  {
    key: 'processing_document_count',
    label: 'Tài liệu đang xử lý',
    icon: 'history',
    tone: 'amber',
  },
])

export const ADMIN_NAVIGATION = Object.freeze([
  { id: 'overview', label: 'Tổng quan', icon: 'overview' },
  { id: 'users', label: 'Quản lý người dùng', icon: 'users' },
  { id: 'documents', label: 'Quản lý tài liệu', icon: 'documents' },
])

export function getAdminStatisticCards(data = null) {
  return ADMIN_STATISTICS.map((statistic) => ({
    ...statistic,
    value: data?.[statistic.key] ?? null,
    description: data
      ? 'Dữ liệu quản trị đã được xác minh.'
      : 'Chưa có Admin API cung cấp chỉ số này.',
  }))
}
