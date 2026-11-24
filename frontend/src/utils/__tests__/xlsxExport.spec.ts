import { describe, expect, it } from 'vitest'
import * as XLSX from 'xlsx'

describe('usage workbook export dependency', () => {
  it('writes a readable workbook using the admin export API', () => {
    const sheet = XLSX.utils.aoa_to_sheet([['Model', 'Tokens', 'Cost']])
    XLSX.utils.sheet_add_aoa(sheet, [['gpt-test', 123, 0.25]], { origin: -1 })
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, sheet, 'Usage')
    const bytes = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' })
    const exported = XLSX.read(bytes, { type: 'array' })
    expect(XLSX.utils.sheet_to_json(exported.Sheets.Usage)).toEqual([
      { Model: 'gpt-test', Tokens: 123, Cost: 0.25 }
    ])
  })
})
