import unittest
from chat_cost import price,total

class CostTests(unittest.TestCase):
    def test_openai_cache_buckets_are_not_double_counted(self):
        event={'engine':'openai','model_requested':'gpt-6.1-sol','usage':{'input_tokens':1000,'input_tokens_details':{'cached_tokens':200,'cache_write_tokens':300},'output_tokens':100,'output_tokens_details':{'reasoning_tokens':80}}}
        self.assertAlmostEqual(price(event),(.001+.00002+.00075+.001))
    def test_claude_cache_write_lifetimes_and_thinking(self):
        event={'engine':'anthropic','model_requested':'claude-opus-5-5','usage':{'input_tokens':100,'cache_read_input_tokens':200,'cache_creation_input_tokens':300,'cache_creation':{'ephemeral_1h_input_tokens':100,'ephemeral_5m_input_tokens':200},'output_tokens':50,'output_tokens_details':{'thinking_tokens':40}}}
        self.assertAlmostEqual(price(event),.0004+.00004+.001+.0008+.001)
    def test_long_context_uses_official_higher_rate(self):
        event={'engine':'openai','model_requested':'gpt-6.1-sol','usage':{'input_tokens':300000,'output_tokens':1000}}
        self.assertAlmostEqual(price(event),1.215)
    def test_long_context_threshold_is_per_provider_request(self):
        event={'engine':'openai','model_requested':'gpt-6.1-sol','usage':{'input_tokens':300000,'output_tokens':200},
               'provider_response_ids':['a','b'],'lookup_counts':{'provider_reports':[
                   {'response_id':ident,'usage':{'input_tokens':150000,'output_tokens':100}} for ident in ('a','b')]}}
        self.assertAlmostEqual(price(event),.602)
    def test_unknown_model_tier_or_bill_hides_money(self):
        base={'engine':'openai','model_requested':'gpt-6.1-sol','usage':{'input_tokens':1,'output_tokens':1}}
        self.assertIsNone(price({**base,'model_requested':'unknown'}))
        self.assertIsNone(price(base,service_tier='priority'))
        self.assertIsNone(price({**base,'api_tool_uses':[{'tool':'image_generation'}]}))
        self.assertIsNone(total([base,{'kind':'judge','model_requested':'unknown'}]))
    def test_judge_is_counted(self):
        base={'engine':'openai','model_requested':'gpt-6.1-sol','usage':{'input_tokens':100,'output_tokens':10}}
        judge={'engine':'anthropic','kind':'judge','model_requested':'claude-opus-5-5','usage':{'input_tokens':100,'output_tokens':10}}
        self.assertAlmostEqual(total([base,judge]),.0009)
    def test_openai_search_calls_count_only_this_response(self):
        base={'engine':'openai','model_requested':'gpt-6.1-sol','response_id':'now','usage':{'input_tokens':100,'output_tokens':10},'lookup_counts':{'calls':[{'response_id':'old','kind':'search'},{'response_id':'now','kind':'search'}]}}
        self.assertAlmostEqual(price(base),.0103)
    def test_unpriced_openai_fetch_hides_money(self):
        event={'engine':'openai','model_requested':'gpt-6.1-sol','response_id':'a','usage':{'input_tokens':100,'output_tokens':10},'lookup_counts':{'calls':[{'response_id':'a','kind':'fetch'}]}}
        self.assertIsNone(price(event))
    def test_missing_cancelled_turn_cost_hides_session_total(self):
        from pathlib import Path
        import tempfile
        from chat_cost import record,prior_cost,report
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            record(root,'s',.01);record(root,'s',None);record(root,'s',.02)
            self.assertIsNone(prior_cost(root,'s'))
            self.assertIn('Turn $0.02000',report(root,'s'))
            self.assertNotIn('session $',report(root,'s'))
