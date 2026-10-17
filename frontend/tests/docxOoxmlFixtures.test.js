import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import JSZip from 'jszip'


async function readPart(fixture, part) {
  const bytes = await readFile(
    new URL(`./fixtures/docx/${fixture}`, import.meta.url),
  )
  const archive = await JSZip.loadAsync(bytes)
  const file = archive.file(part)
  assert.ok(file, `${part} must exist in ${fixture}`)
  return file.async('string')
}


test('typography fixture covers Vietnamese, multiple fonts and character spacing', async () => {
  const documentXml = await readPart('typography-vietnamese.docx', 'word/document.xml')

  assert.match(documentXml, /Tiếng Việt rõ ràng/)
  for (const font of ['Times New Roman', 'Arial', 'Calibri', 'Aptos']) {
    assert.ok(documentXml.includes(font), `${font} font must be represented`)
  }
  assert.match(documentXml, /<w:rFonts w:hAnsi="Arial"\/>/)
  assert.match(documentXml, /<w:spacing w:val="40"\/>/)
  assert.match(documentXml, /<w:b\/>/)
  assert.match(documentXml, /<w:i\/>/)
  assert.match(documentXml, /<w:u w:val="single"\/>/)
})


test('table fixture distinguishes left and justified cell paragraphs', async () => {
  const documentXml = await readPart('tables-left-justify.docx', 'word/document.xml')

  assert.match(documentXml, /<w:tbl>/)
  assert.match(documentXml, /<w:jc w:val="left"\/>/)
  assert.match(documentXml, /<w:jc w:val="both"\/>/)
  assert.match(documentXml, /Nội dung dài trong ô bảng/)
})


test('list fixture covers numbering, bullets and hanging indentation', async () => {
  const documentXml = await readPart('lists-indentation.docx', 'word/document.xml')
  const stylesXml = await readPart('lists-indentation.docx', 'word/styles.xml')

  assert.match(documentXml, /w:val="ListNumber"/)
  assert.match(documentXml, /w:val="ListBullet"/)
  assert.match(documentXml, /<w:ind w:left="864" w:hanging="432"\/>/)
  assert.match(stylesXml, /<w:numId w:val=/)
})


test('multi-page fixture contains explicit page breaks, sections and an embedded image', async () => {
  const documentXml = await readPart('multipage-media.docx', 'word/document.xml')

  assert.match(documentXml, /<w:br w:type="page"\/>/)
  assert.match(documentXml, /<w:sectPr/)
  assert.match(documentXml, /<w:drawing>/)
})
