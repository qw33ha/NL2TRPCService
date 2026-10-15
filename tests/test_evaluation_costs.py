import pytest
from nl2service.evaluation.costs import summarize_cost


def test_cached_model_and_actual_embedding_usage_are_priced_together():
    row={'model_calls':[{'model':'gpt-4.1-2025-04-14','input_tokens':1000,'output_tokens':100,'cached_input_tokens':500}],
         'retrieval':{'embedding_model':'text-embedding-3-small','embedding_calls':1,'embedding_tokens':100}}
    stats=summarize_cost([row])
    assert stats['usd_estimate']==pytest.approx(.002052)
    assert stats['embedding_calls']==1


def test_failed_call_usage_is_not_silently_priced_as_zero():
    stats=summarize_cost([{'model_calls':[{'model':'gpt-4.1-2025-04-14','input_tokens':None,'output_tokens':None}]}])
    assert stats['model_calls']==1 and stats['unknown_usage_calls']==1
    assert stats['usd_estimate'] is None and stats['usd_uncached_upper_bound'] is None


def test_impossible_cache_usage_cannot_produce_an_underpriced_estimate():
    stats=summarize_cost([{'model_calls':[{'model':'gpt-4.1-2025-04-14','input_tokens':100,'output_tokens':10,'cached_input_tokens':200}]}])
    assert stats['invalid_cached_usage_calls']==1 and stats['usd_estimate'] is None
