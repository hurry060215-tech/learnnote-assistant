"""Generate a reproducible long export fixture through LearnNote's own API.

Structural checks are automatic. Word/WPS layout acceptance stays explicit.
"""
import argparse
from io import BytesIO
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.document_exports import build_docx_export, build_pdf_export
from app.models import TaskRecord, FrameGrid
from pypdf import PdfReader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--template', choices=('print', 'academic', 'compact'), default='print')
    parser.add_argument('--include-keyframes', action='store_true')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    title = 'LearnNote 中英文长文档验收'
    frames = []
    task_root = output / 'tasks' / 'long-export-qa'
    if args.include_keyframes:
        from PIL import Image, ImageDraw
        task_root.mkdir(parents=True, exist_ok=True)
        frame = task_root / 'fixture.png'
        picture = Image.new('RGB', (640, 160), '#edf4f3')
        draw = ImageDraw.Draw(picture)
        draw.rectangle((20, 20, 620, 140), outline='#0f766e', width=3)
        draw.text((40, 65), 'Local synthetic keyframe - 00:05', fill='#17201f')
        picture.save(frame)
        frames = [FrameGrid(path=str(frame), start=5, end=5, frame_count=1,
                            url='/api/tasks/long-export-qa/assets/fixture.png')]
    paragraphs_per_chapter = 10 if args.template == 'compact' else 4
    sections = ['# ' + title]
    for index in range(1, 41):
        sections.append(f'## 第 {index} 章 Chapter {index}')
        for paragraph in range(paragraphs_per_chapter):
            sections.append((f'章节 {index} 段落 {paragraph}。检查中文标点、英文换行、分页与完整性。Source evidence must remain traceable after exporting. ' * 4).strip())
        sections.append('| 项目 Item | 数值 Value |\n| --- | --- |\n| 精度 Precision | 3.5 |\n| 来源 Evidence | 00:05 |')
        sections.append('```python\n# 可编辑代码 Editable code\nlearning_rate = 0.01\nfor step in range(3):\n    value = step * learning_rate\n    print(value)\n```')
        sections.append('公式与符号：E = mc²；α + β = γ；y = 3.5x；导航 🧭。')
        if args.include_keyframes and index % 10 == 0:
            sections.append('![00:05 本机生成的合成关键帧](/api/tasks/long-export-qa/assets/fixture.png)')
        sections.append(f'[来源 {index}](https://example.com/lesson?chapter={index}&t=5)')
        sections.append('长链接：[查看来源](https://example.com/' + 'source-evidence-' * 14 + ')')
    note = '\n\n'.join(sections)
    task = TaskRecord(id='long-export-qa', title=title, source_type='local', page_url='https://example.com/lesson', frame_grids=frames, created_at='2026-09-20', updated_at='2026-09-20')
    with patch('app.document_exports.TASK_DIR', task_root.parent):
        docx = build_docx_export(task, note, export_options={'template': args.template})
        pdf = build_pdf_export(task, note, export_options={'template': args.template})
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
              'pdf_no_replacement_char':'\ufffd' not in text,
              'emoji_preserved_or_explicit_fallback':'🧭' in xml and '[compass]' in text}
    if args.include_keyframes:
        checks['docx_frame_alt'] = 'descr="00:05 本机生成的合成关键帧"' in xml
        checks['pdf_frames_embedded'] = sum(bool(page.images) for page in reader.pages) >= 4
    if args.template == 'academic':
        checks['pdf_toc_destinations'] = sum(bool(item.get_object().get('/Dest')) for page in reader.pages for item in page.get('/Annots', [])) >= 40
        checks['docx_native_toc'] = 'TOC \\o' in xml
    report = {'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
              'template':args.template, 'keyframes':args.include_keyframes,
              'paragraphs_per_chapter':paragraphs_per_chapter,
              'pages':len(reader.pages), 'checks':checks,
              'warnings':{'docx':docx.warnings, 'pdf':pdf.warnings},
              'structural_status':'pass' if all(checks.values()) else 'fail',
              'visual_status':'pending_page_render_review', 'word_wps_status':'pending_native_review',
              'scope':'synthetic bilingual text, tables, code, plain Unicode formulas, explicit emoji fallback, source links, optional local keyframes and native TOC; no native equation coverage'}
    (output / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
