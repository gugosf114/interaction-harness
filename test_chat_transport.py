import unittest
from types import SimpleNamespace
from unittest.mock import patch
import chat_progress
from openai_transport import complete_response

class Stream:
    def __init__(self, events, result):self.events,self.result=events,result
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def __iter__(self):return iter(self.events)
    def get_final_response(self):return self.result
class Endpoint:
    def __init__(self):self.calls=[]
    def stream(self,**kw):
        self.calls.append(kw)
        return Stream([SimpleNamespace(type='response.output_text.delta',delta='hidden'),SimpleNamespace(type='response.web_search_call.searching')],{'complete':True})
    def create(self,**kw):return {'nonstream':True}

class TransportTests(unittest.TestCase):
    def test_stream_buffers_answer_and_only_shows_public_phase(self):
        endpoint=Endpoint();seen=[]
        with patch.object(chat_progress,'listener',lambda *x:seen.append(x)):
            response=complete_response(endpoint,model='gpt-6.1-sol')
        self.assertEqual(response,{'complete':True});self.assertEqual(seen,[('Searching the web','')])
        self.assertEqual(endpoint.calls,[{'model':'gpt-6.1-sol'}])
    def test_one_off_path_preserved(self):
        with patch.object(chat_progress,'listener',None):self.assertEqual(complete_response(Endpoint()),{'nonstream':True})
