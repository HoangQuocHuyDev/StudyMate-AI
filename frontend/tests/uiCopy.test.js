import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

async function readSource(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8')
}

test('login does not advertise a persistence option that is not implemented', async () => {
  const source = await readSource('../src/components/Login.jsx')

  assert.doesNotMatch(source, /Ghi nhớ đăng nhập/)
  assert.doesNotMatch(source, /name="remember"/)
})

test('primary learning screens avoid exposing implementation terminology', async () => {
  const [documents, summary, chat] = await Promise.all([
    readSource('../src/components/Documents.jsx'),
    readSource('../src/components/Summarize.jsx'),
    readSource('../src/components/Chat.jsx'),
  ])

  assert.doesNotMatch(documents, />Chunks</)
  assert.doesNotMatch(summary, />Mô hình AI:/)
  assert.doesNotMatch(chat, /message\.model_name/)
  assert.match(documents, />Phần nội dung</)
  assert.match(summary, /phần nội dung/)
  assert.match(chat, /phần nội dung/)
})

