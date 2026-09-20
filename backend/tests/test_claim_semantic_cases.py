"""Distinct bilingual statements and material changes, not numbered templates."""
import unittest
from app.claims import build_claim_evidence_map, safe_claim_projection
from app.models import TranscriptResult, TranscriptSegment

# Each row defines an independent source, contradiction and honest inference.
CASES = [
    ('zh-entity', '本课程使用的编程语言是Python。', '本课程使用的编程语言是Java。', '这门课程可能适合初学者。'),
    ('zh-count', '实验分为三个独立的处理组。', '实验分为五个独立的处理组。', '处理组之间可能存在差异。'),
    ('zh-decimal', '测得样品的质量为3.5毫克。', '测得样品的质量为35毫克。', '称量结果可能受到湿度影响。'),
    ('zh-cause', '加热使密闭容器中的气体压力升高。', '气体压力升高导致容器加热。', '压力变化可能与温度有关。'),
    ('zh-steps', '先保存源文件，然后关闭编辑器。', '先关闭编辑器，然后保存源文件。', '提前保存可能减少数据丢失。'),
    ('zh-negative', '这个实验不能证明药物有效。', '这个实验能够证明药物有效。', '药物效果可能需要进一步验证。'),
    ('zh-ratio', '缓冲液按1:20的比例稀释。', '缓冲液按1:30的比例稀释。', '稀释比例可能影响信号强度。'),
    ('zh-temperature', '样品需要在零下二十摄氏度保存。', '样品需要在二十摄氏度保存。', '样品可能对保存温度敏感。'),
    ('zh-comparison', '处理组的平均读数低于对照组。', '处理组的平均读数高于对照组。', '这种处理可能改变了读数。'),
    ('zh-condition', '只有校验成功后才能导入文件。', '校验失败后也可以导入文件。', '校验可能帮助识别损坏文件。'),
    ('en-entity', 'The reference genome is GRCh38.', 'The reference genome is GRCh37.', 'The reference may affect alignment results.'),
    ('en-count', 'The study includes twelve independent samples.', 'The study includes twenty independent samples.', 'The sample size may limit precision.'),
    ('en-decimal', 'The measured distance is 3.5 millimeters.', 'The measured distance is 35 millimeters.', 'The measurement might contain rounding error.'),
    ('en-cause', 'Heating the gas increases its pressure.', 'Increasing pressure heats the gas.', 'Temperature may influence the observed pressure.'),
    ('en-steps', 'Save the file before closing the editor.', 'Close the editor before saving the file.', 'Saving first may prevent data loss.'),
    ('en-negative', 'The treatment does not improve survival.', 'The treatment improves survival.', 'Further trials might clarify the effect.'),
    ('en-ratio', 'The dilution ratio is 1:20.', 'The dilution ratio is 1:30.', 'Dilution may influence the signal.'),
    ('en-temperature', 'The sample is stored at minus twenty degrees.', 'The sample is stored at twenty degrees.', 'Storage temperature might affect stability.'),
    ('en-comparison', 'The control group has the higher mean value.', 'The treated group has the higher mean value.', 'The difference may depend on sampling.'),
    ('en-condition', 'Import is allowed only after validation succeeds.', 'Import is allowed even when validation fails.', 'Validation might detect damaged files.'),
]


class SemanticClaimCorpus(unittest.TestCase):
    def test_cached_substring_verifications_are_downgraded_without_losing_navigation(self):
        old = {'schema_version':3, 'claims':[{'claim_type':'transcript','verification':'direct','evidence_ids':['old-source']}], 'quality':{'supported_count':1}}
        safe = safe_claim_projection(old)
        self.assertTrue(safe['requires_rebuild'])
        self.assertEqual(safe['claims'][0]['evidence_ids'], [])
        self.assertEqual(safe['claims'][0]['candidate_evidence_ids'], ['old-source'])
        self.assertEqual(old['claims'][0]['evidence_ids'], ['old-source'])

    def test_code_block_is_not_projected_as_a_course_claim(self):
        transcript = TranscriptResult(full_text='An example source sentence.', segments=[])
        claims = build_claim_evidence_map('code', 'fixture', '```python\nprint("This string is not a claim.")\n```', transcript)['claims']
        self.assertEqual(claims, [])

    def test_eighty_bilingual_projections(self):
        count = 0
        for label, source, contradiction, inference in CASES:
            transcript = TranscriptResult(full_text=source, segments=[TranscriptSegment(start=0, end=10, text=source)])
            unrelated = '这是一条没有来源的陈述。' if label.startswith('zh') else 'Unrelated volcanoes erupted yesterday.'
            variants = [(source, 'direct'), ('[00:05] ' + contradiction, 'located_only'),
                        (inference, 'inference'), (unrelated, 'pending_review')]
            for note, expected in variants:
                with self.subTest(case=label, expected=expected):
                    claims = build_claim_evidence_map(label, 'fixture', note, transcript)['claims']
                    self.assertEqual(len(claims), 1, note)
                    self.assertEqual(claims[0]['verification'], expected)
                    if expected != 'direct':
                        self.assertTrue(claims[0]['review_required'])
                        self.assertEqual(claims[0]['evidence_ids'], [])
                    else:
                        self.assertTrue(claims[0]['evidence_ids'])
                    count += 1
        self.assertEqual(count, 80)

    def test_positive_substring_of_negative_is_not_verified(self):
        source = 'There is no evidence that treatment improves survival.'
        transcript = TranscriptResult(full_text=source, segments=[TranscriptSegment(start=0,end=10,text=source)])
        claims = build_claim_evidence_map('negative', 'fixture', 'Treatment improves survival.', transcript)['claims']
        self.assertNotEqual(claims[0]['verification'], 'direct')
