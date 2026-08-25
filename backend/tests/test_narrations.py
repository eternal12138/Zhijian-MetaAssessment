import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.narrations import _detected_type
from app.services.narration_catalog import narration_slots


class NarrationCatalogTest(unittest.TestCase):
    def test_standard_protocol_exposes_nine_recording_slots(self):
        tasks = [
            SimpleNamespace(id="task-a", title="题目一", scenario="情境一"),
            SimpleNamespace(id="task-b", title="题目二", scenario="情境二"),
        ]

        slots = narration_slots(tasks)

        self.assertEqual(len(slots), 9)
        self.assertEqual(
            [slot.key for slot in slots],
            [
                "instructions",
                "practice",
                "questionnaire",
                "task:task-a",
                "task:task-b",
                "silence:0",
                "silence:1",
                "silence:2",
                "silence:3",
            ],
        )
        questionnaire = next(slot for slot in slots if slot.key == "questionnaire")
        self.assertEqual(questionnaire.label, "问卷填写指导语")
        self.assertIn("下面共有24道量表题", questionnaire.source_text)
        self.assertIn("最后还有一道姓名确认题", questionnaire.source_text)
        self.assertIn("按1（强烈不同意）到7（强烈同意）作答", questionnaire.source_text)

    def test_wav_is_detected_from_content(self):
        wav_header = b"RIFF" + (b"\x00" * 4) + b"WAVE" + b"data"

        mime_type, suffix = _detected_type(
            wav_header,
            "application/octet-stream",
            "recording.bin",
        )

        self.assertEqual(mime_type, "audio/wav")
        self.assertEqual(suffix, ".wav")

    def test_unrecognised_file_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            _detected_type(b"not audio", "text/plain", "note.txt")

        self.assertEqual(context.exception.status_code, 415)


if __name__ == "__main__":
    unittest.main()
