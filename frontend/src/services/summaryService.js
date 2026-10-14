import apiClient from './apiClient.js'

export const SUMMARY_TYPES = Object.freeze(['SHORT', 'STANDARD', 'DETAILED'])

function validateAuthenticatedRequest(documentId, accessToken) {
  if (!Number.isInteger(documentId) || documentId < 1) {
    throw new TypeError('Mã tài liệu phải là một số nguyên lớn hơn hoặc bằng 1.')
  }
  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }
}

function normalizeSummaryType(summaryType) {
  if (typeof summaryType !== 'string') {
    throw new TypeError('Loại bản tóm tắt không hợp lệ.')
  }
  const normalized = summaryType.trim().toUpperCase()
  if (!SUMMARY_TYPES.includes(normalized)) {
    throw new TypeError('Loại bản tóm tắt phải là SHORT, STANDARD hoặc DETAILED.')
  }
  return normalized
}

export function generateSummary(
  documentId,
  summaryType,
  { accessToken, signal } = {},
) {
  validateAuthenticatedRequest(documentId, accessToken)
  const normalizedSummaryType = normalizeSummaryType(summaryType)

  return apiClient.post('/summaries/generate', {
    document_id: documentId,
    summary_type: normalizedSummaryType,
  }, {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
  })
}

export function getDocumentSummaries(
  documentId,
  { accessToken, signal } = {},
) {
  validateAuthenticatedRequest(documentId, accessToken)
  const query = new URLSearchParams({ document_id: String(documentId) })

  return apiClient.get(`/summaries?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
  })
}
