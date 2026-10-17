"""Invented faithful talk excerpts and strict unsupported-claim controls."""
import unittest
from itertools import product

from app.grounding_literals import literal_quantities
from app.models import TranscriptResult, TranscriptSegment
from app.summarizer import note_grounding_issues


class GroundingLiteralTests(unittest.TestCase):
    def issues(self, source, note):
        transcript = TranscriptResult(full_text=source, source="faster-whisper",
            segments=[TranscriptSegment(start=0, end=16200, text=source)])
        return note_grounding_issues(note, transcript, [])

    def test_only_whole_editorial_headings_are_exempt(self):
        source = "主持人说：先见面再散步。嘉宾认为这样更方便。"
        for heading in ("# Highlights", "## Part 1", "### part 12 ###"):
            self.assertEqual(self.issues(source, heading + "\n\n" + source), [])
        for heading in ("## Highlights Zoom", "## Part 1 Amanjiwo", "## Part Zero", "## Part 0", "## Part 10000"):
            self.assertTrue(any(i.startswith("unsupported_terms:") for i in self.issues(source, heading + "\n\n" + source)))
        for body in ("我们使用 Highlights。", "Part 是本期嘉宾。", "```\n## Highlights\n```", "    ## Highlights", "\t## Part 1"):
            self.assertTrue(any(i.startswith("unsupported_terms:") for i in self.issues(source, body)), body)
        self.assertIn("unsupported_terms:zoom", self.issues(source, "## Highlights\n\n使用 Zoom。"))

    def test_exact_unambiguous_chinese_arabic_values_keep_units_and_sign(self):
        cases = [("五十元", "50元"), ("负五十元", "-50元"), ("正五十元", "+50元"),
            ("两百元", "200元"), ("一千零五十元", "1050元"), ("十元", "10元"),
            ("零点五公斤", "0.5千克"), ("负三点一五摄氏度", "-3.15℃"),
            ("五万元", "5万元"), ("五十％", "50%"), ("五十点零五元", "50.05元"),
            ("九千九百九十九毫米", "9999毫米")]
        for chinese, arabic in cases:
            with self.subTest(chinese=chinese, arabic=arabic):
                self.assertEqual(literal_quantities(chinese), literal_quantities(arabic))
                self.assertTrue(literal_quantities(chinese))
                self.assertEqual(self.issues("预算" + chinese + "。", "预算" + arabic + "。"), [])
                self.assertEqual(self.issues("预算" + arabic + "。", "预算" + chinese + "。"), [])
        fractional = "一" * 40
        self.assertEqual(literal_quantities("负零点" + fractional + "元"), literal_quantities("-0." + "1" * 40 + "元"))
        self.assertEqual(literal_quantities("预算-50元"), {("-50", "元", "", "", "")})

    def test_no_approximation_ordinals_unit_conversion_or_sign_changes(self):
        for source, candidate in (
            ("约五十元", "50元"), ("大概有五十元", "50元"), ("估计五十元", "50元"), ("五十元左右", "50元"), ("五十多元", "50元"),
            ("第五十元", "50元"), ("五十至六十元", "60元"), ("一百一元", "110元"),
            ("一百一元", "101元"), ("一万五千元", "5000元"), ("一二元", "2元"),
            ("五十元", "500元"), ("负五十元", "50元"), ("五十元", "-50元"),
            ("五十元", "约500元"), ("五十元", "500元左右"),
            ("五十元", "约五百元"), ("五十元", "五百元左右"),
            ("50元", "负500元"), ("50元", "正500元"), ("50元", "第500元"),
            ("约50元", "五十元"), ("50元左右", "五十元"),
            ("50元", "一百一元"), ("50元", "1万5000元"),
            ("50元", "正五十元"), ("50元", "50-60元"),
            ("三点一五元", "3.1元"), ("五万元", "50000元"), ("五十千克", "50000毫克"),
        ):
            with self.subTest(source=source, candidate=candidate):
                self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues(source, candidate)))
        self.assertEqual(literal_quantities("一万五千元"), {("literal:一万五千", "元", "", "", "")})

    def test_qualified_and_unresolved_literals_copy_faithfully_without_guessing(self):
        for amount in ("约五百元", "五百元左右", "第500元", "负500元", "正500元", "一百一元", "1万5000元", "50-60元", "五十多元"):
            with self.subTest(amount=amount):
                self.assertTrue(literal_quantities(amount))
                self.assertEqual(self.issues("预算" + amount + "。", "预算" + amount + "。"), [])
        for source, note in (("约五十元", "约50元"), ("五十元左右", "50元左右"),
                             ("第五十元", "第50元"), ("不超过五十元", "不超过50元")):
            self.assertEqual(self.issues(source, note), [])
        for source, note in (("不超过五十元", "超过50元"), ("五十多元", "50元"), ("50-60元", "60元")):
            self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues(source, note)))

    def test_sign_prefix_matrix_keeps_unknown_forms_literal(self):
        signs = ("+", "-", "正", "负", "−", "＋", "－", "±")
        prefixes = signs + tuple("".join(pair) for pair in product(signs, repeat=2))
        for prefix in prefixes:
            for value in ("50", "五十"):
                amount = prefix + value + "元"
                with self.subTest(amount=amount):
                    self.assertTrue(literal_quantities(amount))
                    self.assertEqual(self.issues(amount, amount), [])
                    self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues("50元", prefix + "500元")))
                    self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues(amount, "50元")))
                    if len(prefix) > 1 or prefix in ("−", "＋", "－", "±"):
                        self.assertEqual(next(iter(literal_quantities(amount)))[0], "literal:" + prefix + value)
        for source, note in (("正50元", "+五十元"), ("负50元", "-五十元")):
            self.assertEqual(self.issues(source, note), [])

    def test_invalid_fraction_and_unicode_qualifier_offsets_fail_closed(self):
        for amount in ("五十点元", "50.元", "五十点点元", "50..元"):
            with self.subTest(amount=amount):
                self.assertTrue(literal_quantities(amount))
                self.assertEqual(self.issues(amount, amount), [])
                self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues(amount, "50元")))
                self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues("50元", amount)))
        for amount in ("İ约50元", "İİ50元左右", "İ约五十元", "İİ五十元左右"):
            self.assertEqual(self.issues(amount, amount), [])
            self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues("50元", amount)))
            self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues(amount, "50元")))

    def test_range_markers_do_not_misread_ordinary_mention(self):
        self.assertEqual(self.issues("嘉宾提到五十元。", "预算50元。"), [])
        self.assertEqual(self.issues("嘉宾提到50元。", "预算50元。"), [])
        self.assertEqual(self.issues("预算增加到六十元。", "预算60元。"), [])
        for amount in ("50至60元", "五十到六十元", "50 至 60元", "五十 到 六十元", "50元到60元", "五十元至六十元"):
            self.assertEqual(self.issues(amount, amount), [])
            self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues(amount, "60元")))
            self.assertTrue(any(i.startswith("unsupported_quantity:") for i in self.issues(amount, "50元")))

    def test_exact_source_scoped_duration_reports_pass(self):
        for text in (
            "我不认为该视频长达10分钟，这个说法不对。",
            "嘉宾说：该视频时长约20分钟。",
            "主持人转述：“该视频全长20分钟”。",
            '主持人转述："该视频全长20分钟"。',
            "原话是「本视频时长10分钟」，这里说的是预告。",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.issues(text, "# 对话摘记\n\n" + text), [])

    def test_duration_exception_requires_whole_exact_sentence_and_scope(self):
        for source, note in (
            ("我们聊的是周末安排。", "本视频时长为10分钟。"),
            ("本视频时长为10分钟。", "本视频时长为10分钟。"),
            ("我不认同这个观点，本视频时长10分钟。", "我不认同这个观点，本视频时长10分钟。"),
            ("我们聊的是周末安排。", "嘉宾说：本视频时长为10分钟。"),
            ("我们聊的是周末安排。", "我不认为本视频时长为10分钟。"),
            ("本视频时长为10分钟。", "“本视频时长为10分钟”。"),
            ("嘉宾说：本视频时长1 0分钟。", "嘉宾说：本视频时长10分钟。"),
            ("我不同意你，本视频时长10分钟。", "我不同意你，本视频时长10分钟。"),
            ("我不认为你对，该视频长达10分钟。", "我不认为你对，该视频长达10分钟。"),
            ("嘉宾说：本视频时长为10分钟，这其实是口误。", "嘉宾说：本视频时长为10分钟。"),
            ("嘉宾说：本视频时长为10分钟。", "嘉宾说：本视频时长为20分钟。"),
            ("我不认为该视频长达10分钟，这个说法不对。", "该视频长达10分钟。"),
        ):
            with self.subTest(source=source, note=note):
                self.assertTrue(any(i.startswith("duration_mismatch:") for i in self.issues(source, note)))
        self.assertEqual(self.issues("我们聊的是周末安排。", "本视频时长为4.5小时。"), [])
        for prefix in ("不能否认", "我不能不同意", "我不是不认为", "我没有否认", "并非不认同", "我没有说我不认为"):
            text = prefix + "本视频时长10分钟。"
            self.assertTrue(any(i.startswith("duration_mismatch:") for i in self.issues(text, text)), text)

    def test_no_new_semantic_fact_check_claim(self):
        self.assertEqual(self.issues("我不建议每天熬夜。", "我建议每天熬夜。"), [])
        self.assertEqual(self.issues("我个人觉得这个办法可能有用，但没有验证。", "这个办法已经验证有效。"), [])
        self.assertIn("unsupported_terms:zoom", self.issues("我们线下见面。", "我们使用Zoom。"))
        self.assertEqual(self.issues("我们使用GitHub，CEO只是引用的称呼。", "我们使用GitHub，ceo只是引用的称呼。"), [])
