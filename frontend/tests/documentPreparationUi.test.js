import assert from 'node:assert/strict'
import test from 'node:test'

import {
  DocumentPreparationStageError,
  documentPreparationStages,
  uploadAndPrepareDocument,
} from '../src/components/documentPreparationUi.js'


test('one upload runs processing and indexing once in order', async () => {
  const events = []
  const result = await uploadAndPrepareDocument({ name: 'lesson.pdf' }, {
    upload: async () => {
      events.push('upload')
      return { id: 12, title: 'Lesson' }
    },
    process: async (documentId) => {
      events.push(`process:${documentId}`)
      return { document_id: documentId, status: 'READY' }
    },
    index: async (documentId) => {
      events.push(`index:${documentId}`)
      return { document_id: documentId, rag_status: 'READY' }
    },
    onStage: (stage) => events.push(`stage:${stage}`),
  })

  assert.deepEqual(events, [
    'stage:uploading',
    'upload',
    'stage:processing',
    'process:12',
    'stage:indexing',
    'index:12',
    'stage:ready',
  ])
  assert.equal(result.uploaded.id, 12)
  assert.equal(result.processed.status, 'READY')
  assert.equal(result.indexed.rag_status, 'READY')
})


test('extraction failure stops before embedding and remains manually retryable', async () => {
  let indexCalls = 0
  const extractionError = new Error('private provider detail')

  await assert.rejects(
    uploadAndPrepareDocument({}, {
      upload: async () => ({ id: 3 }),
      process: async () => { throw extractionError },
      index: async () => { indexCalls += 1 },
    }),
    (error) => {
      assert.ok(error instanceof DocumentPreparationStageError)
      assert.equal(error.stage, documentPreparationStages.PROCESSING)
      assert.equal(error.originalError, extractionError)
      return true
    },
  )
  assert.equal(indexCalls, 0)
})


test('embedding failure preserves the completed processing stage without automatic retry', async () => {
  let processCalls = 0
  let indexCalls = 0

  await assert.rejects(
    uploadAndPrepareDocument({}, {
      upload: async () => ({ id: 4 }),
      process: async () => {
        processCalls += 1
        return { status: 'READY' }
      },
      index: async () => {
        indexCalls += 1
        throw new Error('quota unavailable')
      },
    }),
    (error) => error instanceof DocumentPreparationStageError
      && error.stage === documentPreparationStages.INDEXING,
  )

  assert.equal(processCalls, 1)
  assert.equal(indexCalls, 1)
})


test('two sequential files each run one complete preparation pipeline', async () => {
  let nextId = 0
  const calls = []
  const operations = {
    upload: async (file) => {
      calls.push(`upload:${file.name}`)
      nextId += 1
      return { id: nextId }
    },
    process: async (id) => { calls.push(`process:${id}`) },
    index: async (id) => { calls.push(`index:${id}`) },
  }

  await uploadAndPrepareDocument({ name: 'one.pdf' }, operations)
  await uploadAndPrepareDocument({ name: 'two.docx' }, operations)

  assert.deepEqual(calls, [
    'upload:one.pdf', 'process:1', 'index:1',
    'upload:two.docx', 'process:2', 'index:2',
  ])
})
