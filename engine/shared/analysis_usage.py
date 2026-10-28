"""Numeric provider receipts only; missing usage is never counted as zero."""
def safe_usage(raw):
    if not isinstance(raw,dict):return None
    result={k:raw[k] for k in ('prompt_tokens','completion_tokens','total_tokens') if type(raw.get(k)) is int and raw[k]>=0}
    details=raw.get('completion_tokens_details')
    if isinstance(details,dict) and type(details.get('reasoning_tokens')) is int and details['reasoning_tokens']>=0:result['reasoning_tokens']=details['reasoning_tokens']
    return result or None

def usage_summary(attempts):
    fields=('prompt_tokens','completion_tokens','total_tokens','reasoning_tokens')
    coverage={k:sum(k in (a.get('usage') or {}) for a in attempts) for k in fields}
    sums={k:sum((a.get('usage') or {}).get(k,0) for a in attempts) for k in fields if coverage[k]}
    return {'knownTokens':sums,'fieldCoverage':coverage,'attemptCount':len(attempts),'complete':bool(attempts) and coverage['total_tokens']==len(attempts)}
