import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const component = (name) => new URL(`../src/components/admin/${name}`, import.meta.url)

test('admin header and user management show Vietnamese role and account labels', async () => {
  const [dashboard, users] = await Promise.all([
    readFile(component('AdminDashboard.jsx'), 'utf8'),
    readFile(component('AdminUsers.jsx'), 'utf8'),
  ])

  assert.match(dashboard, />Quản trị viên<\/span>/)
  assert.doesNotMatch(dashboard, />ADMIN<\/span>/)
  assert.match(users, /<th>Mã người dùng<\/th>/)
  assert.match(users, /<th>Tên đăng nhập<\/th>/)
  assert.match(users, /<option value="ADMIN">Quản trị viên<\/option>/)
  assert.doesNotMatch(users, /<th>Username<\/th>|<th>ID<\/th>/)
})

test('admin documents consistently describe files, uploaders and statuses in Vietnamese', async () => {
  const documents = await readFile(component('AdminDocuments.jsx'), 'utf8')

  for (const label of [
    'Mã tài liệu',
    'Loại tệp',
    'Người tải lên',
    'Trạng thái xử lý',
    'Trạng thái hỏi đáp',
    'Cập nhật lần cuối',
    'Hoàn tất xử lý',
  ]) assert.match(documents, new RegExp(label))

  assert.doesNotMatch(documents, /<th>ID<\/th>|<th>Chủ sở hữu<\/th>|Loại file|tên file/)
  assert.match(documents, /<option value="PDF">PDF<\/option>/)
  assert.match(documents, /<option value="DOCX">DOCX<\/option>/)
})

test('admin overview avoids raw role enums and technical audit wording', async () => {
  const [overview, ui] = await Promise.all([
    readFile(component('AdminOverview.jsx'), 'utf8'),
    readFile(component('adminDashboardUi.js'), 'utf8'),
  ])

  assert.match(overview, /Đã cập nhật/)
  assert.match(overview, /10 mục gần nhất/)
  assert.match(overview, /Giờ UTC/)
  assert.doesNotMatch(overview, /Dữ liệu trực tiếp|nhật ký kiểm toán/)
  assert.match(ui, /Gồm người dùng và quản trị viên/)
  assert.doesNotMatch(ui, /Gồm tài khoản USER và ADMIN/)
})
