"""Actual PDF/OOXML links must resolve to the claim's own recorded evidence."""
from copy import deepcopy
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile
import hashlib
import tempfile
from pathlib import Path
from PIL import Image

from lxml import etree
from pypdf import PdfReader

from app.claims import build_claim_evidence_map
from app.document_exports import build_docx_export, build_pdf_export, build_html_export, build_structured_export
from app.models import TaskRecord, TranscriptResult, TranscriptSegment, FrameGrid
from app.routers.knowledge_study import api_export_docx, api_unified_export, UnifiedExportRequest

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
class DocumentClaimCitationTests(TestCase):
    def setUp(self):
        self.task=TaskRecord(id='cite-fixture', title='证据引用课程', source_type='local',
            page_url='https://example.com/lesson?v=1&token=SOURCE_SECRET',created_at='2026-10-08',updated_at='2026-10-08')
        self.note='# 证据引用课程\n\n水在标准压力下于一百度沸腾。\n\n图表展示三个阶段。\n\n原始文档规定保留输入。\n\n该现象可能与环境有关。\n'
        self.transcript=TranscriptResult(segments=[TranscriptSegment(start=12,end=18,text='水在标准压力下于一百度沸腾。')])
        self.claims=build_claim_evidence_map(self.task.id,self.task.title,self.note,self.transcript,
            visual_windows=[{'id':'frame-1','start':30,'end':35,'summary':'图表展示三个阶段。','grid_url':'/api/tasks/cite-fixture/assets/frame.jpg'}],
            document_evidence=[{'evidence_id':'document-source','text':'原始文档规定保留输入。','source_uri':'https://docs.example.org/spec?page=3&key=DOC_SECRET','locator':'第 3 页'}])
    def export(self, builder, **kwargs):
        return builder(self.task,self.note,self.transcript.model_dump(mode='json'),claim_map=self.claims,**kwargs)
    def test_docx_has_real_claim_bookmarks_and_correct_evidence_relationships(self):
        with ZipFile(BytesIO(self.export(build_docx_export).content)) as z:
            root=etree.fromstring(z.read('word/document.xml'))
            rels=etree.fromstring(z.read('word/_rels/document.xml.rels'))
        bookmarks=set(root.xpath('//w:bookmarkStart/@w:name',namespaces=NS))
        for claim in self.claims['claims']:
            links=root.xpath('//w:hyperlink[w:r/w:t=$cid]',namespaces=NS,cid=claim['claim_id'])
            self.assertEqual(len(links),1)
            target=links[0].get('{'+NS['w']+'}anchor')
            self.assertIn(target,bookmarks)
            destination=root.xpath('//w:bookmarkStart[@w:name=$target]',namespaces=NS,target=target)[0].getparent()
            self.assertIn(claim['claim_id'], ''.join(destination.itertext()))
            source_text=[]
            for following in destination.itersiblings():
                if following.xpath('.//w:bookmarkStart',namespaces=NS): break
                source_text.append(''.join(following.itertext()))
            for eid in claim['evidence_ids']:
                self.assertIn(eid,''.join(source_text))
        targets={x.get('Target') for x in rels if x.get('Type','').endswith('/hyperlink')}
        self.assertIn('https://example.com/lesson?v=1&t=12',targets)
        self.assertIn('https://example.com/lesson?v=1&t=30',targets)
        self.assertIn('https://docs.example.org/spec?page=3',targets)
        text=''.join(root.itertext())
        for secret in ['SOURCE_SECRET','DOC_SECRET']:self.assertNotIn(secret,text+str(targets))
        self.assertIn('推断；需回源核对',text)
    def test_pdf_claim_links_resolve_to_the_actual_evidence_appendix(self):
        reader=PdfReader(BytesIO(self.export(build_pdf_export).content))
        links=[x.get_object() for p in reader.pages for x in p.get('/Annots',[]) if x.get_object().get('/Subtype')=='/Link']
        destinations=[x['/Dest'] for x in links if '/Dest' in x]
        self.assertEqual(len(destinations),len(self.claims['claims']))
        self.assertEqual(len({(str(dest[0]),float(dest[3])) for dest in destinations}),len(destinations))
        for claim, dest in zip(self.claims['claims'], destinations):
            page=next(p for p in reader.pages if p.indirect_reference==dest[0])
            heading_positions = []
            def visit(text, matrix, text_matrix, font, size):
                if '证据引用 ' + claim['claim_id'] in text:
                    heading_positions.append(matrix[5] + text_matrix[5])
            page.extract_text(visitor_text=visit)
            self.assertEqual(len(heading_positions), 1)
            self.assertLess(abs(float(dest[3]) - heading_positions[0]), 20)
        uris={x['/A']['/URI'] for x in links if '/A' in x and x['/A'].get('/S')=='/URI'}
        self.assertIn('https://example.com/lesson?v=1&t=12',uris)
        self.assertIn('https://example.com/lesson?v=1&t=30',uris)
        self.assertIn('https://docs.example.org/spec?page=3',uris)
        self.assertFalse(any('SECRET' in x for x in uris))
    def test_html_and_markdown_preserve_stable_ids_and_no_broken_fragments(self):
        html=etree.HTML(self.export(build_html_export).content)
        ids=set(html.xpath('//@id'))
        for href in html.xpath('//a/@href'):
            if href.startswith('#'):self.assertIn(href[1:],ids)
        markdown=self.export(build_structured_export)['markdown']
        for c in self.claims['claims']: self.assertIn('['+c['claim_id']+'](#',markdown)
        # A duplicated pre-existing heading cannot steal the citation target.
        cid=self.claims['claims'][0]['claim_id']; self.note+='\n#### 证据引用 '+cid+'\n'
        self.claims['source_revision']=hashlib.sha256(self.note.encode()).hexdigest()
        html=etree.HTML(self.export(build_html_export).content)
        ids=html.xpath('//@id'); self.assertEqual(len(ids),len(set(ids)))
        link=html.xpath('//a[string(.)=$cid]/@href',cid=cid)[0]
        self.assertTrue(link.endswith('-2'))
    def test_stale_other_task_and_bad_spans_do_not_acquire_citations(self):
        for key,value in [('task_id','another-task'),('source_revision','stale'),('schema_version',5)]:
            with self.subTest(key=key):
                bad=deepcopy(self.claims);bad[key]=value
                result=build_structured_export(self.task,self.note,claim_map=bad)
                self.assertIn('claim_citations_require_current_map',result['warnings'])
                self.assertNotIn('逐条证据引用',result['markdown'])
        bad=deepcopy(self.claims);bad['claims'][0]['source_span']['end']+=1
        result=build_structured_export(self.task,self.note,claim_map=bad)
        self.assertNotIn('['+bad['claims'][0]['claim_id']+']',result['markdown'])
        self.assertIn('claim_citations_require_current_map',result['warnings'])
    def test_local_and_private_sources_keep_internal_navigation_and_options(self):
        task=self.task.model_copy(update={'page_url':'http://localhost/private?token=SECRET'})
        options={'include_source_link':False,'include_timestamps':False,'include_images':False,'include_transcript':False}
        result=build_structured_export(task,self.note,claim_map=self.claims,options=options)
        self.assertIn('](#',result['markdown'])
        for excluded in ['https://','localhost','SECRET','00:12','00:30','![','> 水']:
            self.assertNotIn(excluded,result['markdown'])
        self.assertNotIn('逐条证据引用',build_structured_export(task,self.note,claim_map=self.claims,options={'include_note':False})['markdown'])
    def test_actual_legacy_and_unified_routes_load_claim_map_without_annotation_revision_change(self):
        target='app.routers.knowledge_study.'
        with patch(target+'get_task',return_value=self.task),patch(target+'read_task_note',return_value=self.note),patch(target+'read_task_transcript',return_value=self.transcript.model_dump(mode='json')),patch(target+'read_json',return_value=self.claims) as read,patch('app.personal_notes.annotation_markdown',return_value='\n## 我的补充\n个人内容'):
            for response in [api_export_docx(self.task.id,include_annotations=True),api_unified_export(self.task.id,'pdf',UnifiedExportRequest())]:
                self.assertNotIn('claim_citations_require_current_map',response.headers.get('X-LearnNote-Export-Warning',''))
                if response.media_type.endswith('pdf'):
                    text=''.join(p.extract_text() for p in PdfReader(BytesIO(response.body)).pages)
                else:
                    with ZipFile(BytesIO(response.body)) as z:text=z.read('word/document.xml').decode()
                self.assertIn(self.claims['claims'][0]['claim_id'],text)
            read.assert_called_with(self.task.id,'claim_evidence_map.json',{})

    def test_markdown_route_surfaces_stale_citation_warning(self):
        target='app.routers.knowledge_study.'
        bad=deepcopy(self.claims);bad['source_revision']='stale'
        with patch(target+'get_task',return_value=self.task),patch(target+'read_task_note',return_value=self.note),patch(target+'read_task_transcript',return_value={}),patch(target+'read_json',return_value=bad):
            response=api_unified_export(self.task.id,'markdown',UnifiedExportRequest(options={'include_annotations':False}))
        self.assertIn('claim_citations_require_current_map',response.headers['X-LearnNote-Export-Warning'])
        self.assertNotIn('逐条证据引用',response.body.decode())

    def test_actual_indexed_visual_frame_is_embedded_and_exclusion_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=root/self.task.id;folder.mkdir()
            frame=folder/'frame.jpg';Image.new('RGB',(160,90),'white').save(frame)
            self.task=self.task.model_copy(update={'frame_grids':[FrameGrid(path=str(frame),url=f'/api/tasks/{self.task.id}/assets/frame.jpg',start=30,end=35,frame_count=1)]})
            with patch('app.document_exports.TASK_DIR',root):
                for include in [True,False]:
                    options={'include_images':include}
                    reader=PdfReader(BytesIO(self.export(build_pdf_export,export_options=options).content))
                    self.assertEqual(sum(len(p.images) for p in reader.pages),int(include))
                    with ZipFile(BytesIO(self.export(build_docx_export,export_options=options).content)) as z:
                        self.assertEqual(sum(p.startswith('word/media/') for p in z.namelist()),int(include))
                        if include:self.assertIn('画面 00:00:30',z.read('word/document.xml').decode())
                visual=next(e for e in self.claims['evidence'] if e['kind']=='visual')
                visual['grid_url']='/api/tasks/other-task/assets/frame.jpg'
                reader=PdfReader(BytesIO(self.export(build_pdf_export).content))
                self.assertEqual(sum(len(p.images) for p in reader.pages),0)

    def test_candidate_sources_are_never_presented_as_support(self):
        note = '# 候选来源\n\n[00:12] 压力可能改变沸点。\n\n[00:12] 压力改变具体温度。\n'
        claims = build_claim_evidence_map(self.task.id, self.task.title, note, self.transcript)
        self.assertEqual(claims['claims'][0]['verification'], 'inference')
        self.assertEqual(claims['claims'][1]['verification'], 'located_only')
        self.assertTrue(claims['claims'][0]['candidate_evidence_ids'])
        for builder in (build_docx_export, build_pdf_export):
            artifact = builder(self.task, note, self.transcript.model_dump(mode='json'), claim_map=claims)
            if artifact.suffix == 'pdf':
                text = ''.join(page.extract_text() for page in PdfReader(BytesIO(artifact.content)).pages)
            else:
                with ZipFile(BytesIO(artifact.content)) as archive:
                    text = ''.join(etree.fromstring(archive.read('word/document.xml')).itertext())
            self.assertIn('候选定位，不代表支持', text)
            self.assertIn('推断；需回源核对', text)
            self.assertIn('仅定位；未验证支持', text)
            self.assertNotIn('支持来源：', text)

    def test_changed_ambiguous_and_foreign_evidence_maps_are_rejected(self):
        changes = {
            'revision': lambda value: value.update(evidence_revision='stale'),
            'text': lambda value: value['evidence'][0].update(text='替换后的证据'),
            'timestamp': lambda value: value['evidence'][0].update(start=13),
            'foreign_source': lambda value: value['evidence'][0].update(evidence_id='task-other-transcript-00000'),
            'foreign_owner': lambda value: value['evidence'][0].update(task_id='other'),
            'duplicate': lambda value: value['evidence'].append(deepcopy(value['evidence'][0])),
            'unknown_kind': lambda value: value['evidence'][0].update(kind=['transcript']),
            'malformed_source': lambda value: value['evidence'].append(None),
            'rebuild': lambda value: value.update(requires_rebuild=True),
            'revision_kind': lambda value: value.update(source_revision_kind='different'),
        }
        for label, change in changes.items():
            with self.subTest(label=label):
                claims = deepcopy(self.claims)
                change(claims)
                result = build_structured_export(self.task, self.note, claim_map=claims)
                self.assertIn('claim_citations_require_current_map', result['warnings'])
                self.assertNotIn('逐条证据引用', result['markdown'])

    def test_replaced_transcript_does_not_reuse_recorded_links(self):
        transcript = self.transcript.model_dump(mode='json')
        transcript['segments'][0]['text'] = '现在是完全不同的来源文本。'
        result = build_structured_export(self.task, self.note, transcript, claim_map=self.claims)
        self.assertIn('claim_citations_require_current_map', result['warnings'])
        self.assertNotIn('逐条证据引用', result['markdown'])

    def test_malformed_claim_or_missing_source_does_not_gain_a_link(self):
        for fields in ({'evidence_ids': ['missing']}, {'evidence_ids': []},
                       {'evidence_ids': [{}]}, {'verification': ['direct']}):
            with self.subTest(fields=fields):
                claims = deepcopy(self.claims)
                claims['claims'][0].update(fields)
                result = build_structured_export(self.task, self.note, claim_map=claims)
                self.assertIn('claim_citations_require_current_map', result['warnings'])
                self.assertNotIn('[' + claims['claims'][0]['claim_id'] + ']', result['markdown'])

    def test_frontmatter_and_annotations_do_not_change_original_note_revision(self):
        note = '---\ntitle: 原始笔记\n---\n\n' + self.note
        claims = build_claim_evidence_map(self.task.id, self.task.title, note, self.transcript)
        target = 'app.routers.knowledge_study.'
        with patch(target + 'get_task', return_value=self.task), \
                patch(target + 'read_task_note', return_value=note), \
                patch(target + 'read_task_transcript', return_value=self.transcript.model_dump(mode='json')), \
                patch(target + 'read_json', return_value=claims), \
                patch('app.personal_notes.annotation_markdown', return_value='\n## 我的补充\n个人内容'):
            response = api_export_docx(self.task.id, include_annotations=True)
        self.assertNotIn('claim_citations_require_current_map', response.headers.get('X-LearnNote-Export-Warning', ''))
        with ZipFile(BytesIO(response.body)) as archive:
            text = ''.join(etree.fromstring(archive.read('word/document.xml')).itertext())
        self.assertIn(claims['claims'][0]['claim_id'], text)
        self.assertIn('个人内容', text)
        self.assertNotIn('title: 原始笔记', text)
