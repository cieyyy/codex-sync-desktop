import json
from unittest import TestCase
from codex_sync_desktop.core.import_preview import PreviewSource, iter_dialogue


def source(records):
    return PreviewSource('test', content=''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in records).encode())


def event(kind, text):
    return {'type':'event_msg','payload':{'type':kind,'message':text}}


def message(role, text, **extra):
    return {'type':'response_item','payload':{'type':'message','role':role,'content':[{'type':'input_text' if role=='user' else 'output_text','text':text}],**extra}}


class DialoguePreviewTests(TestCase):
    def test_shows_roles_deduplicates_mirrors_and_hides_internal_logs(self):
        rows = [event('user_message', '你好'),message('user','你好'),
                {'type':'response_item','payload':{'type':'function_call_output','output':'secret tool log'}},
                message('assistant','internal reasoning',channel='analysis'),
                message('developer','system instruction'),
                message('assistant','你好，有什么需要帮助？'),event('agent_message','你好，有什么需要帮助？'),
                {'type':'event_msg','payload':{'type':'task_complete','last_agent_message':'你好，有什么需要帮助？'}}]
        result = list(iter_dialogue(source(rows)))
        self.assertEqual([(row.role,row.text) for row in result], [('user','你好'),('assistant','你好，有什么需要帮助？')])
        self.assertIn('secret tool log', '\n'.join(source(rows).iter_records()))

    def test_preserves_repeated_requests_and_escaped_newlines(self):
        result = list(iter_dialogue(source([event('user_message','再试一次'),event('user_message','再试一次'),message('assistant','第一行\n第二行')])) )
        self.assertEqual(len(result),3)
        self.assertEqual(result[-1].text,'第一行\n第二行')

    def test_falls_back_to_completed_answer_and_handles_no_dialogue(self):
        result = list(iter_dialogue(source([{'type':'event_msg','payload':{'type':'task_complete','last_agent_message':'最终答复'}}])))
        self.assertEqual(result[0].text,'最终答复')
        self.assertEqual(list(iter_dialogue(source([{'type':'session_meta','payload':{}}])))[0].role, 'notice')

    def test_images_have_placeholder_and_content_is_not_executed(self):
        result=list(iter_dialogue(source([{'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_image','image_url':'data:...'}]}},message('assistant','<script>alert(1)</script>')])) )
        self.assertEqual(result[0].text,'[图片附件]')
        self.assertEqual(result[1].text,'<script>alert(1)</script>')
