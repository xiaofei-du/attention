import json
import unittest

from nkc.summary import extract_summary, spoken_text


def marked(why="你希望登入狀態保持穩定。", done="我修好了更新邏輯，測試已通過。", next_step="接下來需要你決定何時部署。"):
    data = {"why": why, "done": done, "next": next_step}
    return ("這裡是詳細的技術說明，完整回覆仍然留在畫面供你查看。" * 8 +
            "\n\n<!-- nkc-summary:v1\n" + json.dumps(data, ensure_ascii=False) + "\n-->")


def direct(reply):
    return reply + '\n\n<!-- nkc-summary:v1\n{"mode":"direct"}\n-->'


class SummaryTests(unittest.TestCase):
    def test_only_the_explicit_summary_is_spoken_not_the_full_answer(self):
        self.assertEqual(extract_summary(marked()), "你希望登入狀態保持穩定。我修好了更新邏輯，測試已通過。接下來需要你決定何時部署。")

    def test_greeting_is_added_even_if_the_model_omits_it(self):
        self.assertEqual(spoken_text("我已完成這輪檢查。", "sunshine"), "Hello, sunshine。我已完成這輪檢查。")

    def test_no_name_is_invented_when_none_is_configured(self):
        self.assertEqual(spoken_text("我已完成這輪檢查。"), "Hello。我已完成這輪檢查。")

    def test_no_next_step_is_allowed_without_inventing_work(self):
        self.assertEqual(extract_summary(marked(next_step="")), "你希望登入狀態保持穩定。我修好了更新邏輯，測試已通過。")

    def test_missing_summary_never_falls_back_to_reading_the_answer(self):
        with self.assertRaises(ValueError):
            extract_summary("A very long normal answer with shell logs and file paths.")

    def test_a_quoted_example_in_a_code_fence_is_not_a_notification(self):
        with self.assertRaises(ValueError):
            extract_summary("```html\n" + marked() + "\n```")

    def test_malformed_json_and_missing_fields_do_not_become_speech(self):
        for payload in ["not JSON", '{"done":"已經完成"}', '{"why":123,"done":"完成","next":""}']:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                extract_summary("<!-- nkc-summary:v1\n" + payload + "\n-->")

    def test_oversized_summary_is_rejected_not_cut_mid_instruction(self):
        with self.assertRaises(ValueError):
            extract_summary(marked(done="完成" * 200))

    def test_native_speech_control_sequences_are_rejected(self):
        with self.assertRaises(ValueError):
            extract_summary(marked(done="[[rate 1000]] 亂碼"))
        with self.assertRaises(ValueError):
            spoken_text("完成。", "[[slnc 99999]]")

    def test_an_unterminated_fence_cannot_hide_a_marker_as_code(self):
        with self.assertRaises(ValueError):
            extract_summary("```html\n" + marked())

    def test_short_reply_is_read_verbatim_without_a_second_summary(self):
        self.assertEqual(spoken_text(extract_summary(direct('好了，已經存好了。')), 'sunshine'),
                         'Hello, sunshine。好了，已經存好了。')

    def test_short_reply_from_an_inflight_old_prompt_also_uses_original_words(self):
        legacy_metadata = marked().split('<!-- nkc-summary:v1')[1]
        self.assertEqual(extract_summary('改好了。\n\n<!-- nkc-summary:v1' + legacy_metadata), '改好了。')

    def test_short_reply_removes_only_simple_formatting(self):
        self.assertEqual(extract_summary(direct('**已完成**。\n\n音量保持 *原本設定*，`Meijia` 沒有變。')),
                         '已完成。 音量保持 原本設定，Meijia 沒有變。')

    def test_direct_mode_never_reads_a_long_answer_or_truncates_it(self):
        self.assertEqual(extract_summary(direct('好' * 160)), '好' * 160)
        with self.assertRaises(ValueError):
            extract_summary(direct('好' * 161))

    def test_technical_short_answers_use_the_existing_summary(self):
        metadata = marked().split('<!-- nkc-summary:v1')[1]
        summary = '你希望登入狀態保持穩定。我修好了更新邏輯，測試已通過。接下來需要你決定何時部署。'
        for reply in ('```sh\nrm example\n```', '| 欄位 | 狀態 |\n| a | b |',
                      '[說明](https://example.com)', '/Users/example/output.txt', '[[rate 1000]] 完成。'):
            with self.subTest(reply=reply):
                self.assertEqual(extract_summary(reply + '\n\n<!-- nkc-summary:v1' + metadata), summary)
                with self.assertRaises(ValueError):
                    extract_summary(direct(reply))

    def test_invalid_or_missing_metadata_cannot_turn_a_short_answer_into_speech(self):
        for message in ('好了。', direct(''),
                        '好了。\n<!-- nkc-summary:v1\n{"mode":"direct","extra":"ignored"}\n-->',
                        '好了。\n<!-- nkc-summary:v1\nnot json\n-->'):
            with self.subTest(message=message), self.assertRaises(ValueError):
                extract_summary(message)

    def test_short_english_reply_is_measured_in_words_not_chinese_character_limit(self):
        reply = 'The notification now follows the language of each reply. Chinese sentences use the Chinese voice, and English sentences use the English voice. You do not need to change the setting between replies.'
        self.assertEqual(extract_summary(direct(reply)), reply)

    def test_english_summary_keeps_word_boundaries_and_can_fit_half_a_minute(self):
        why = 'You wanted each notification to follow the language of the reply, so you can switch between Chinese and English without changing any settings.'
        done = 'I added automatic voice selection and checked that both languages can share one audio file while background media stays quiet.'
        next_step = 'The next step is to listen to a mixed reply and confirm that the transitions sound natural.'
        message = ('A detailed explanation. ' * 100 + '\n<!-- nkc-summary:v1\n' +
                   json.dumps({'why': why, 'done': done, 'next': next_step}) + '\n-->')
        self.assertEqual(extract_summary(message), why + ' ' + done + ' ' + next_step)


if __name__ == "__main__":
    unittest.main()
