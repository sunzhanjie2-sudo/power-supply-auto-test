// Read-only report QA with the bundled spreadsheet renderer.
import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const [report, out] = process.argv.slice(2);
if (!report || !out) throw new Error('usage: node render_report.mjs report.xlsx output_dir');
await fs.mkdir(out, { recursive: true });
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(report));
wb.recalculate();
const errors = await wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',
  options: { useRegex: true, maxResults: 30 }, maxChars: 2000 });
console.log('Formula errors: ' + errors.ndjson);
const previews = [
  ['执行汇总', 'A1:O20'], ['规格&说明', 'A1:D19'],
  ['纹波与稳压精度测试', 'A9:H22'], ['动态响应测试', 'A9:H22'],
  ['动态稳定度测试', 'A9:I22'], ['启机关机测试', 'A9:G22']
];
for (let i = 0; i < previews.length; i++) {
  const [sheetName, range] = previews[i];
  if (!wb.worksheets.items.some(sheet => sheet.name === sheetName)) continue;
  const result = await wb.inspect({ kind: 'table', range: `${sheetName}!${range}`,
    include: 'values,formulas', tableMaxRows: 22, tableMaxCols: 12, maxChars: 4000 });
  await fs.writeFile(path.join(out, `sheet_${i}.json`), result.ndjson);
  const png = await wb.render({ sheetName, range, scale: 1, format: 'png' });
  await fs.writeFile(path.join(out, `sheet_${i}.png`), new Uint8Array(await png.arrayBuffer()));
  console.log(`Rendered ${sheetName}`);
}
