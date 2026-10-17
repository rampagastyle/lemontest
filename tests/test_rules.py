"""Тесты чистой логики проверки списков. Запуск из корня проекта: python -m unittest tests.test_rules -v"""
import io
import unittest

from listcheck import rules


class MentionsTest(unittest.TestCase):
    def test_ids_names_and_communities(self):
        ids, names = rules.extract_mentions("[id111|Аня] и [id222|Боря], [durov|Паша], [club5|LEMON], [public7|Паблик]")
        self.assertEqual(ids, {111, 222})
        self.assertEqual(names, {"durov"})

    def test_empty(self):
        self.assertEqual(rules.extract_mentions(""), (set(), set()))
        self.assertEqual(rules.extract_mentions(None), (set(), set()))


class VkPostUrlTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(rules.parse_vk_post_url("https://vk.com/wall-123_456"),
                         (-123, 456, "https://vk.com/wall-123_456"))
        self.assertEqual(rules.parse_vk_post_url("vk.com/lemon?w=wall-123_456")[:2], (-123, 456))

    def test_invalid(self):
        self.assertIsNone(rules.parse_vk_post_url("https://example.com/wall-1_2"))
        self.assertIsNone(rules.parse_vk_post_url("https://vk.com/lemon"))
        self.assertIsNone(rules.parse_vk_post_url(""))


class LinkCodeTest(unittest.TestCase):
    def test_find(self):
        self.assertEqual(rules.find_link_code("привет, вот код lemon-ab12cd !"), "LEMON-AB12CD")
        self.assertIsNone(rules.find_link_code("просто сообщение"))


class NamesMatchTest(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(rules.names_match("Иван Петров", "Иван Петров"))
        self.assertTrue(rules.names_match("Иван Петров", "Петров Иван"))
        self.assertTrue(rules.names_match("Алёна Смирнова", "Алена Смирнова"))
        self.assertTrue(rules.names_match("Иван Петров", "Иван Петров ✨"))

    def test_mismatches(self):
        self.assertFalse(rules.names_match("Иван Петров", "Мария Сидорова"))
        self.assertFalse(rules.names_match("Иван Петров", "Иван"))        # одно имя из двух — мало
        self.assertFalse(rules.names_match("Иван Петров", ""))
        self.assertFalse(rules.names_match("", "Иван Петров"))


class DecideStoryTest(unittest.TestCase):
    def ai(self, **kw):
        base = dict(is_story=True, lemon_mention=True, event_content_visible=True,
                    author_name="Иван Петров", confidence=0.9)
        base.update(kw)
        return base

    def test_approve(self):
        self.assertEqual(rules.decide_story(self.ai(), True)[0], "approve")

    def test_reject_not_story(self):
        self.assertEqual(rules.decide_story(self.ai(is_story=False), True)[0], "reject")

    def test_reject_no_mention(self):
        self.assertEqual(rules.decide_story(self.ai(lemon_mention=False), True)[0], "reject")

    def test_low_confidence_goes_to_review(self):
        self.assertEqual(rules.decide_story(self.ai(confidence=0.5), True)[0], "review")
        # даже «не сторис» при низкой уверенности — на проверку человеку, а не отказ
        self.assertEqual(rules.decide_story(self.ai(is_story=False, confidence=0.3), True)[0], "review")

    def test_name_problems_go_to_review(self):
        self.assertEqual(rules.decide_story(self.ai(), False)[0], "review")
        self.assertEqual(rules.decide_story(self.ai(author_name=""), True)[0], "review")

    def test_event_not_visible_goes_to_review(self):
        self.assertEqual(rules.decide_story(self.ai(event_content_visible=False), True)[0], "review")

    def test_unknown_fields_go_to_review(self):
        self.assertEqual(rules.decide_story(self.ai(is_story=None, lemon_mention=None), True)[0], "review")


class AiJsonTest(unittest.TestCase):
    def test_plain_fenced_and_wrapped(self):
        self.assertEqual(rules.parse_ai_json('{"a": 1}'), {"a": 1})
        self.assertEqual(rules.parse_ai_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(rules.parse_ai_json('Вот ответ: {"a": 1} готово'), {"a": 1})

    def test_garbage(self):
        self.assertIsNone(rules.parse_ai_json("не json"))
        self.assertIsNone(rules.parse_ai_json(""))
        self.assertIsNone(rules.parse_ai_json("[1, 2]"))

    def test_normalize(self):
        norm = rules.normalize_ai({"is_story": "true", "lemon_mention": True, "event_content_visible": None,
                                   "author_name": " Иван ", "confidence": "1.7", "reason": "ок"})
        self.assertIs(norm["is_story"], True)
        self.assertIsNone(norm["event_content_visible"])
        self.assertEqual(norm["author_name"], "Иван")
        self.assertEqual(norm["confidence"], 1.0)
        self.assertEqual(rules.normalize_ai({})["confidence"], 0.0)


class ImageHashTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            raise unittest.SkipTest("Pillow не установлен")
        cls.Image, cls.Draw = Image, ImageDraw

    def make(self, boxes, size=(360, 640)):
        image = self.Image.new("RGB", size, "white")
        draw = self.Draw.Draw(image)
        for box in boxes:
            draw.rectangle(box, fill="black")
        return image

    @staticmethod
    def jpeg(image, quality=90, scale=1.0):
        if scale != 1.0:
            image = image.resize((int(image.width * scale), int(image.height * scale)))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality)
        return buffer.getvalue()

    def test_recompressed_copy_is_close_and_other_image_is_far(self):
        story = self.make([(20, 40, 340, 200), (60, 400, 300, 600)])
        other = self.make([(0, 0, 180, 640)])
        h_original = rules.average_hash(self.jpeg(story, 95))
        h_copy = rules.average_hash(self.jpeg(story, 60, scale=0.5))
        h_other = rules.average_hash(self.jpeg(other, 95))
        self.assertLessEqual(rules.hamming(h_original, h_copy), 4)
        self.assertGreater(rules.hamming(h_original, h_other), 8)
        self.assertEqual(len(h_original), 16)


if __name__ == "__main__":
    unittest.main()
