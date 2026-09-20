"""Generate a reproducible long export fixture through LearnNote's own API.

Structural checks are automatic. Word/WPS layout acceptance stays explicit.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.document_exports import build_docx_export, build_pdf_export
from app.models import TaskRecord
from pypdf import PdfReader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    title = 'LearnNote 中英文长文档验收'
    sections = ['# ' + title]
    for index in range(1, 41):
        sections.append(f'## 第 {index} 章 Chapter {index}')
        for paragraph in range(4):
            sections.append((f'章节 {index} 段落 {paragraph}。检查中文标点、英文换行、分页与完整性。Source evidence must remain traceable after exporting. ' * 4).strip())
        sections.append('| 项目 Item | 数值 Value |\n| --- | --- |\n| 精度 Precision | 3.5 |\n| 来源 Evidence | 00:05 |')
        sections.append('```python\n# 可编辑代码 Editable code\nlearning_rate = 0.01\nfor step in range(3):\n    value = step * learning_rate\n    print(value)\n```')
        sections.append('公式与符号：E = mc²；α + β = γ；y = 3.5x。')
        sections.append(f'[来源 {index}](https://example.com/lesson?chapter={index}&t=5)')
        sections.append('长链接：[查看来源](https://example.com/' + 'source-evidence-' * 14 + ')')
    note = '\n\n'.join(sections)
    task = TaskRecord(id='long-export-qa', title=title, source_type='local', created_at='2026-09-20', updated_at='2026-09-20')
    docx = build_docx_export(task, note)
    pdf = build_pdf_export(task, note)
    (output / 'source.md').write_text(note, encoding='utf-8')
    (output / 'long-note.docx').write_bytes(docx.content)
    (output / 'long-note.pdf').write_bytes(pdf.content)
    reader = PdfReader(BytesIO(pdf.content))
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    with ZipFile(BytesIO(docx.content)) as package:
        xml = package.read('word/document.xml').decode('utf-8')
        relationships = package.read('word/_rels/document.xml.rels').decode('utf-8')
    checks = {'at_least_30_pdf_pages':len(reader.pages) >= 30,
              'pdf_first_and_last_chapter':all(f'Chapter {i}' in text for i in (1,40)),
              'docx_editable_tables':xml.count('<w:tbl>') >= 40,
              'docx_code_retained':'learning_rate' in xml,
              'source_links_retained':'https://example.com/lesson?' in relationships,
              'pdf_no_replacement_char':'\ufffd' not in text}
    report = {'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'pages':len(reader.pages), 'checks':checks,
              'structural_status':'pass' if all(checks.values()) else 'fail',
              'visual_status':'pending_page_render_review', 'word_wps_status':'pending_native_review',
              'scope':'synthetic bilingual text, tables, code, plain Unicode formulas and source links; no image or native equation coverage'}
    (output / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
