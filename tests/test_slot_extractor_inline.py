import unittest

from agents.models import UserInput
from agents.slot_extractor import extract_slots_from_message


class InlineDeclarationTests(unittest.TestCase):
    def test_compound_message_declares_none_fields(self):
        msg = "그냥 욱신거림, 복용중인 약 없음, 알레르기 없음, 기저질환 없음"
        out = extract_slots_from_message(msg, [], [])
        ui = out.user_input
        self.assertEqual(ui.current_drug_names, ["없음"])
        self.assertEqual(ui.allergies, ["없음"])
        self.assertEqual(ui.conditions, ["없음"])
