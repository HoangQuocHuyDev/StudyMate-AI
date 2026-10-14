export function createDocumentObjectUrl(blob, urlApi = URL) {
  if (!(blob instanceof Blob)) throw new TypeError('Dữ liệu tài liệu không hợp lệ.')
  return urlApi.createObjectURL(blob)
}

export function revokeDocumentObjectUrl(objectUrl, urlApi = URL) {
  if (typeof objectUrl === 'string' && objectUrl) {
    urlApi.revokeObjectURL(objectUrl)
  }
}

export function triggerDocumentDownload(
  blob,
  filename,
  { urlApi = URL, documentObject = document } = {},
) {
  if (!(blob instanceof Blob)) throw new TypeError('Dữ liệu tài liệu không hợp lệ.')
  if (typeof filename !== 'string' || !filename.trim()) {
    throw new TypeError('Tên tài liệu không hợp lệ.')
  }

  const objectUrl = urlApi.createObjectURL(blob)
  try {
    const link = documentObject.createElement('a')
    link.href = objectUrl
    link.download = filename
    link.hidden = true
    documentObject.body.append(link)
    link.click()
    link.remove()
  } finally {
    urlApi.revokeObjectURL(objectUrl)
  }
}
