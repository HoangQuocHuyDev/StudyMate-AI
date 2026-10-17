export const documentPreparationStages = Object.freeze({
  UPLOADING: 'uploading',
  PROCESSING: 'processing',
  INDEXING: 'indexing',
  READY: 'ready',
})

export class DocumentPreparationStageError extends Error {
  constructor(stage, cause) {
    super(`Document preparation failed during ${stage}.`, { cause })
    this.name = 'DocumentPreparationStageError'
    this.stage = stage
    this.originalError = cause
  }
}

function requireDocumentId(response) {
  const documentId = response?.id
  if (!Number.isInteger(documentId) || documentId < 1) {
    throw new TypeError('Phản hồi tải tài liệu không hợp lệ.')
  }
  return documentId
}

export async function uploadAndPrepareDocument(file, {
  upload,
  process,
  index,
  onStage,
} = {}) {
  for (const operation of [upload, process, index]) {
    if (typeof operation !== 'function') {
      throw new TypeError('Quy trình chuẩn bị tài liệu không hợp lệ.')
    }
  }

  let uploaded
  try {
    onStage?.(documentPreparationStages.UPLOADING)
    uploaded = await upload(file)
  } catch (error) {
    throw new DocumentPreparationStageError(
      documentPreparationStages.UPLOADING,
      error,
    )
  }

  const documentId = requireDocumentId(uploaded)
  let processed
  try {
    onStage?.(documentPreparationStages.PROCESSING, uploaded)
    processed = await process(documentId)
  } catch (error) {
    throw new DocumentPreparationStageError(
      documentPreparationStages.PROCESSING,
      error,
    )
  }

  let indexed
  try {
    onStage?.(documentPreparationStages.INDEXING, uploaded)
    indexed = await index(documentId)
  } catch (error) {
    throw new DocumentPreparationStageError(
      documentPreparationStages.INDEXING,
      error,
    )
  }

  onStage?.(documentPreparationStages.READY, uploaded)
  return { uploaded, processed, indexed }
}
