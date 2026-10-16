export const MAX_DOCUMENT_UPLOAD_SIZE = 10 * 1024 * 1024

const ALLOWED_DOCUMENT_EXTENSIONS = new Set(['pdf', 'docx'])

export function getDocumentUploadValidationMessage(file) {
  if (!file || typeof file.name !== 'string' || !Number.isFinite(file.size)) {
    return 'Tệp được chọn không hợp lệ. Vui lòng chọn lại file PDF hoặc DOCX.'
  }

  const extension = file.name.split('.').pop()?.toLocaleLowerCase('en')
  if (!extension || !ALLOWED_DOCUMENT_EXTENSIONS.has(extension)) {
    return 'Định dạng không được hỗ trợ. Vui lòng chọn file PDF hoặc DOCX.'
  }

  if (file.size === 0) {
    return 'File đã chọn đang rỗng. Vui lòng chọn một file có nội dung.'
  }

  if (file.size > MAX_DOCUMENT_UPLOAD_SIZE) {
    return 'File vượt quá giới hạn 10 MiB. Vui lòng chọn một file nhỏ hơn.'
  }

  return null
}

export function getSingleDocumentUploadFile(files) {
  const candidates = Array.from(files ?? [])
  if (candidates.length === 0) return { file: null, error: null }
  if (candidates.length > 1) {
    return {
      file: null,
      error: 'Mỗi lần chỉ có thể tải lên một file.',
    }
  }

  const [file] = candidates
  return {
    file,
    error: getDocumentUploadValidationMessage(file),
  }
}

export function createDocumentAutoUploadController() {
  let generation = 0
  let activeRequestId = null

  return {
    isBusy() {
      return activeRequestId !== null
    },

    invalidate() {
      generation += 1
      activeRequestId = null
    },

    async submit(file, {
      upload,
      onStart,
      onSuccess,
      onError,
      onSettled,
    } = {}) {
      if (activeRequestId !== null) return { status: 'busy' }
      if (typeof upload !== 'function') {
        throw new TypeError('Hàm tải tài liệu lên không hợp lệ.')
      }

      const validationError = getDocumentUploadValidationMessage(file)
      if (validationError) return { status: 'invalid', error: validationError }

      const requestId = generation + 1
      generation = requestId
      activeRequestId = requestId
      onStart?.(file)

      try {
        const response = await upload(file)
        if (activeRequestId !== requestId) return { status: 'stale' }
        onSuccess?.(response, file)
        return { status: 'success', response }
      } catch (error) {
        if (activeRequestId !== requestId) return { status: 'stale' }
        onError?.(error, file)
        return { status: 'error', error }
      } finally {
        if (activeRequestId === requestId) {
          activeRequestId = null
          onSettled?.(file)
        }
      }
    },
  }
}
