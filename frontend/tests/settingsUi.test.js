import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('Settings connects profile, password and persisted theme without placeholder behavior', async () => {
  const source = await readFile(
    new URL('../src/components/Settings.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /await updateProfile/)
  assert.match(source, /await changePassword/)
  assert.match(source, /updateCurrentUser/)
  assert.match(source, /useTheme/)
  assert.match(source, /password_changed=1/)
  assert.match(source, /disabled=\{isSubmitting\}/)
  assert.equal(source.includes('chưa kết nối máy chủ'), false)
  assert.equal(source.includes('chỉ được xem trước'), false)
})
