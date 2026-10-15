"""List-price estimates preserving unknown usage rather than silently dropping it."""
import json
from pathlib import Path

PRICING_PATH=Path(__file__).with_name('pricing-2026-10-14.json')
RATES=json.loads(PRICING_PATH.read_text())


def summarize_cost(rows):
    calls=[call for row in rows for call in row['model_calls']]
    unknown_usage=sum(call.get('input_tokens') is None or call.get('output_tokens') is None for call in calls)
    unknown_cache=sum(call.get('cached_input_tokens') is None for call in calls)
    invalid_cache=sum(call.get('cached_input_tokens') is not None and call.get('input_tokens') is not None
                      and not 0<=call['cached_input_tokens']<=call['input_tokens'] for call in calls)
    unpriced=0;known_estimate=0.0;upper=0.0
    for call in calls:
        rate=RATES.get(call.get('model'))
        if not rate or call.get('service_tier') not in (None,'default','standard','auto'):
            unpriced+=1;continue
        input_tokens,output_tokens=call.get('input_tokens'),call.get('output_tokens')
        if input_tokens is None or output_tokens is None: continue
        upper+=(input_tokens*rate['input']+output_tokens*rate['output'])/1_000_000
        cached=call.get('cached_input_tokens')
        if cached is not None and 0<=cached<=input_tokens:
            known_estimate+=((input_tokens-cached)*rate['input']+cached*rate['cached_input']+output_tokens*rate['output'])/1_000_000
    embedding_tokens=sum(row.get('retrieval',{}).get('embedding_tokens',0) for row in rows)
    embedding_calls=sum(row.get('retrieval',{}).get('embedding_calls',0) for row in rows)
    unsupported_embeddings=any(row.get('retrieval',{}).get('embedding_tokens',0) and row['retrieval'].get('embedding_model')!='text-embedding-3-small' for row in rows)
    embedding_usd=embedding_tokens*RATES['text-embedding-3-small']['input']/1_000_000
    complete=not unknown_usage and not unknown_cache and not invalid_cache and not unpriced and not unsupported_embeddings
    return {'model_calls':len(calls),'unknown_usage_calls':unknown_usage,'unknown_cached_usage_calls':unknown_cache,
            'invalid_cached_usage_calls':invalid_cache,
            'unpriced_calls':unpriced,'embedding_calls':embedding_calls,'embedding_tokens':embedding_tokens,
            'cached_input_tokens_known':sum(call.get('cached_input_tokens') or 0 for call in calls),
            'usd_estimate':round(known_estimate+embedding_usd,8) if complete else None,
            'usd_uncached_upper_bound':round(upper+embedding_usd,8) if not unknown_usage and not unpriced and not unsupported_embeddings else None,
            'estimate_basis':RATES['basis']}
