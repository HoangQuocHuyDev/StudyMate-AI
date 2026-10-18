import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../../services/apiClient.js'


export const ADMIN_STATISTICS = Object.freeze([
  { key: 'user_count', label: 'Tổng người dùng', description: 'Gồm người dùng và quản trị viên', icon: 'users', tone: 'blue' },
  { key: 'document_count', label: 'Tổng tài liệu', description: 'Tài liệu hiện còn trong hệ thống', icon: 'documents', tone: 'cyan' },
  { key: 'chat_session_count', label: 'Tổng cuộc hội thoại', description: 'Các cuộc hỏi đáp thuộc tài liệu hiện có', icon: 'chat', tone: 'violet' },
  { key: 'processing_document_count', label: 'Tài liệu đang xử lý', description: 'Đang xử lý nội dung hoặc chuẩn bị cho AI', icon: 'history', tone: 'amber' },
])

export const ADMIN_NAVIGATION = Object.freeze([
  { id: 'overview', label: 'Tổng quan', icon: 'overview' },
  { id: 'users', label: 'Quản lý người dùng', icon: 'users' },
  { id: 'documents', label: 'Quản lý tài liệu', icon: 'documents' },
])

export const ADMIN_ACTIVITY_SERIES = Object.freeze([
  { key: 'registered_user_count', label: 'Tài khoản mới', tone: 'blue' },
  { key: 'uploaded_document_count', label: 'Tài liệu tải lên', tone: 'cyan' },
  { key: 'created_chat_session_count', label: 'Cuộc hội thoại', tone: 'violet' },
  { key: 'generated_summary_count', label: 'Bản tóm tắt', tone: 'amber' },
])

const ACTIVITY_PRESENTATION = Object.freeze({
  USER_REGISTERED: {
    icon: 'users', tone: 'blue',
    title: ({ user_id: userId }) => `Tài khoản mã ${userId} được tạo`,
    detail: () => 'Đăng ký tài khoản mới',
  },
  DOCUMENT_UPLOADED: {
    icon: 'upload', tone: 'cyan',
    title: ({ document_id: documentId }) => `Tài liệu mã ${documentId} được tải lên`,
    detail: ({ file_type: fileType, user_id: userId }) => `${fileType} · Mã người dùng ${userId}`,
  },
  DOCUMENT_PROCESSED: {
    icon: 'check', tone: 'cyan',
    title: ({ document_id: documentId }) => `Tài liệu mã ${documentId} đã xử lý xong`,
    detail: ({ file_type: fileType, user_id: userId }) => `${fileType} · Mã người dùng ${userId}`,
  },
  DOCUMENT_INDEXED: {
    icon: 'sparkle', tone: 'violet',
    title: ({ document_id: documentId }) => `Tài liệu mã ${documentId} đã sẵn sàng cho AI`,
    detail: ({ file_type: fileType, user_id: userId }) => `${fileType} · Mã người dùng ${userId}`,
  },
  SUMMARY_CREATED: {
    icon: 'summary', tone: 'amber',
    title: ({ resource_id: summaryId }) => `Bản tóm tắt mã ${summaryId} được tạo`,
    detail: ({ document_id: documentId, user_id: userId }) => `Mã tài liệu ${documentId} · Mã người dùng ${userId}`,
  },
  CHAT_SESSION_CREATED: {
    icon: 'chat', tone: 'violet',
    title: ({ session_id: sessionId }) => `Cuộc hội thoại mã ${sessionId} được tạo`,
    detail: ({ document_id: documentId, user_id: userId }) => `Mã tài liệu ${documentId} · Mã người dùng ${userId}`,
  },
  DOCUMENT_DELETED: {
    icon: 'trash', tone: 'red',
    title: ({ document_id: documentId }) => `Tài liệu mã ${documentId} đã được xóa`,
    detail: ({ user_id: userId }) => `Mã người dùng ${userId}`,
  },
})

const initialSectionState = Object.freeze({ activeRequestId: 0, data: null, error: '', status: 'idle' })

export const initialAdminDashboardState = Object.freeze({
  overview: initialSectionState,
  activity: initialSectionState,
  recent: initialSectionState,
})

function requireNonNegativeInteger(value, message) {
  if (!Number.isInteger(value) || value < 0) throw new TypeError(message)
  return value
}

function requirePositiveInteger(value, message) {
  if (!Number.isInteger(value) || value < 1) throw new TypeError(message)
  return value
}

function isIsoDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const parsed = new Date(Date.UTC(year, month - 1, day))
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day
}

export function validateAdminOverviewResponse(response) {
  if (!response || typeof response !== 'object') {
    throw new TypeError('Phản hồi tổng quan quản trị không hợp lệ.')
  }
  return Object.fromEntries(ADMIN_STATISTICS.map(({ key }) => [
    key,
    requireNonNegativeInteger(response[key], 'Phản hồi tổng quan quản trị không hợp lệ.'),
  ]))
}

export function getAdminStatisticCards(data) {
  const overview = validateAdminOverviewResponse(data)
  return ADMIN_STATISTICS.map((statistic) => ({ ...statistic, value: overview[statistic.key] }))
}

export function validateAdminActivityResponse(response) {
  if (!response || response.timezone !== 'UTC' || response.days !== 7
    || !Array.isArray(response.items) || response.items.length !== 7) {
    throw new TypeError('Phản hồi biểu đồ hoạt động không hợp lệ.')
  }
  const dates = new Set()
  const items = response.items.map((item) => {
    if (!item || !isIsoDate(item.date) || dates.has(item.date)) {
      throw new TypeError('Phản hồi biểu đồ hoạt động không hợp lệ.')
    }
    dates.add(item.date)
    return {
      date: item.date,
      ...Object.fromEntries(ADMIN_ACTIVITY_SERIES.map(({ key }) => [
        key,
        requireNonNegativeInteger(item[key], 'Phản hồi biểu đồ hoạt động không hợp lệ.'),
      ])),
    }
  })
  return { timezone: 'UTC', days: 7, items }
}

export function getAdminActivityChart(data) {
  const activity = validateAdminActivityResponse(data)
  const values = activity.items.flatMap((item) => ADMIN_ACTIVITY_SERIES.map(({ key }) => item[key]))
  const maximum = Math.max(0, ...values)
  const scaleMaximum = Math.max(1, maximum)
  return {
    ...activity,
    maximum,
    items: activity.items.map((item) => ({
      ...item,
      label: formatAdminActivityDay(item.date),
      series: ADMIN_ACTIVITY_SERIES.map((series) => ({
        ...series,
        value: item[series.key],
        height: (item[series.key] / scaleMaximum) * 100,
      })),
    })),
  }
}

export function validateAdminRecentActivitiesResponse(response) {
  if (!response || !Array.isArray(response.items) || !Number.isInteger(response.limit)
    || response.limit < 1 || response.limit > 50 || response.is_audit_log !== false
    || response.items.length > response.limit) {
    throw new TypeError('Phản hồi hoạt động gần đây không hợp lệ.')
  }
  return {
    limit: response.limit,
    is_audit_log: false,
    items: response.items.map((item) => {
      if (!item || !ACTIVITY_PRESENTATION[item.activity_type]
        || !Number.isFinite(Date.parse(item.occurred_at))) {
        throw new TypeError('Phản hồi hoạt động gần đây không hợp lệ.')
      }
      requirePositiveInteger(item.resource_id, 'Phản hồi hoạt động gần đây không hợp lệ.')
      requirePositiveInteger(item.user_id, 'Phản hồi hoạt động gần đây không hợp lệ.')
      for (const key of ['document_id', 'session_id']) {
        if (item[key] !== null) requirePositiveInteger(item[key], 'Phản hồi hoạt động gần đây không hợp lệ.')
      }
      if (item.file_type !== null && !['PDF', 'DOCX'].includes(item.file_type)) {
        throw new TypeError('Phản hồi hoạt động gần đây không hợp lệ.')
      }
      return { ...item }
    }),
  }
}

export function getAdminRecentActivityPresentation(activity) {
  const validated = validateAdminRecentActivitiesResponse({
    items: [activity], limit: 1, is_audit_log: false,
  }).items[0]
  const presentation = ACTIVITY_PRESENTATION[validated.activity_type]
  return {
    ...presentation,
    title: presentation.title(validated),
    detail: presentation.detail(validated),
    time: formatAdminActivityTime(validated.occurred_at),
  }
}

export function formatAdminActivityDay(value) {
  const [year, month, day] = value.split('-').map(Number)
  return new Intl.DateTimeFormat('vi-VN', {
    day: '2-digit', month: '2-digit', timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month - 1, day)))
}

export function formatAdminActivityTime(value) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'Không rõ thời gian'
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(parsed)
}

export function adminDashboardReducer(state, action) {
  if (!Object.hasOwn(state, action.section)) return state
  const current = state[action.section]
  if (action.type === 'request-started') {
    return { ...state, [action.section]: { ...current, activeRequestId: action.requestId, error: '', status: 'loading' } }
  }
  if (current.activeRequestId !== action.requestId) return state
  if (action.type === 'request-succeeded') {
    return { ...state, [action.section]: { ...current, data: action.data, error: '', status: 'success' } }
  }
  if (action.type === 'request-failed') {
    return { ...state, [action.section]: { ...current, error: action.error, status: 'error' } }
  }
  return state
}

export function getAdminDashboardErrorMessage(error) {
  if (error instanceof ApiHttpError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    if (error.status === 403) return 'Bạn không có quyền truy cập dữ liệu quản trị.'
    if (error.status >= 500) return 'Hệ thống chưa thể tải dữ liệu quản trị. Vui lòng thử lại.'
  }
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến hệ thống. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  return 'Không thể tải dữ liệu quản trị lúc này.'
}
