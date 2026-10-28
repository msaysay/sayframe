"""Canonicalize automatic adjacent repeats only when retained text is identical.

Manual word deletion never calls this. Acoustic checks and independent semantic
review still decide whether the selected earlier occurrence can be removed.
"""
import copy
VERSION=1

def earlier_copy(cut,row,candidates,reserved=(),partial=()):
    if cut['kind']!='repeat' or row.get('protected') or row.get('caption') is not None:return cut
    from speech_refine import FACT
    if FACT.search(cut['quote']):return cut
    old=set(cut['indices']);removed=set(row['removed'])
    if old&removed:return cut
    expected=''.join(w['word'] for i,w in enumerate(row['words']) if i not in removed|old)
    blocked=set(row.get('protectedIndices',[]))|set(reserved)|set(partial)
    if old&blocked:return cut
    for choice in candidates:
        if choice['id']!=cut['id'] or choice['quote']!=cut['quote'] or choice.get('overlapChain'):continue
        indices=choice['indices'];first=set(indices)
        if indices[-1]>=cut['indices'][0] or first&(removed|blocked):continue
        span=range(indices[0],cut['indices'][-1]+1)
        # No skipped word, existing user cut, punctuation or intervening setup.
        if set(span)!=first|old:continue
        if ''.join(row['words'][i]['word'] for i in span)!=cut['quote']*2:continue
        actual=''.join(w['word'] for i,w in enumerate(row['words']) if i not in removed|first)
        if actual!=expected:continue
        import repeated_takes
        selected=repeated_takes.validate([{**cut,'indices':list(indices),'quote':choice['quote']}],[row])[0]
        return {**copy.deepcopy(cut),**selected,'proposalIndices':cut['indices'],'proposalQuote':cut['quote'],'instanceNormalization':'earlier adjacent identical copy; exact retained text unchanged'}
    return cut
