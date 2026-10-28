"""Exact source-bound evidence for proposed characters or whole acoustic tokens.

Does not choose words or timestamps. An unchanged original audition provides
the recognition baseline when an unrelated spelling varies across ASR runs.
"""
from collections import Counter
import math,re
VERSION=4
PROPOSED_DISCOURSE_FILLERS=frozenset(('就是','就是说'))

def spoken(value):return ''.join(c for c in value if c.isalnum()).upper()

def prepare(words,indices,before,proposed_fillers=(),reviewed_excerpts=()):
    reject=lambda reason:{'passed':False,'reason':reason,'version':VERSION}
    if not isinstance(proposed_fillers,(list,tuple)) or any(not isinstance(p,(list,tuple)) or not p or any(type(i) is not int for i in p) for p in proposed_fillers):return reject('invalid proposed filler binding')
    selected=set(indices);audible=[i for i,w in enumerate(words) if spoken(w['word'])]
    if not isinstance(reviewed_excerpts,(list,tuple)) or any(not isinstance(p,(list,tuple)) or not p or list(p)!=sorted(set(p)) or any(type(i) is not int or i not in audible for i in p) for p in reviewed_excerpts):return reject('invalid reviewed excerpt binding')
    if any(set(p)&selected and not set(p)<=selected for p in reviewed_excerpts):return reject('partial reviewed excerpt')
    removed=[i for i in audible if i in selected]
    if not removed or len(removed)>12:return reject('unsupported removal size')
    from speech_refine import FACT
    atomic=__import__('acoustic_atoms').removal_evidence(words,indices)
    tokens=atomic.get('tokens',[]) if atomic['passed'] else []
    token_members={i:token for token in tokens for i in token['members']}
    runs=[];witness_indices=set()
    for i in removed:
        if runs and not any(k not in selected for k in audible if runs[-1][-1]<k<i):runs[-1].append(i)
        else:runs.append([i])
    for run in runs:
        quote=spoken(''.join(words[i]['word'] for i in run))
        following=spoken(''.join(words[i]['word'] for i in audible if i>run[-1] and i not in selected))
        # Protected words keep the stricter path, even if they repeat.
        if FACT.search(quote):return reject('protected removal')
        if not re.fullmatch(r'[\u4e00-\u9fff]+',quote) and not all(i in token_members for i in run):return reject('non-Chinese removal without complete token')
        # This is an acoustic audition of a source-bound software proposal,
        # never a semantic approval. The normal post-cut independent review
        # must still reject an emphatic/meaningful use of these words.
        proposed=quote in PROPOSED_DISCOURSE_FILLERS and any(list(run)==list(p) for p in proposed_fillers)
        # Ordinary words require a separately reviewed continuous excerpt.
        # Existing literal interjections may join it in the SAME audition,
        # but no other old deletion inherits this permission.
        excerpt=any(set(p)<=selected and bool(set(run)&set(p)) and all(i in p or re.fullmatch('[呃嗯额啊哦]+',spoken(words[i]['word'])) for i in run) for p in reviewed_excerpts)
        hesitation=bool(re.fullmatch('[呃嗯额啊哦]+',quote))
        if not hesitation and not following.startswith(quote) and not proposed and not excerpt:return reject('not a literal hesitation or restart')
        if not hesitation and not proposed and not excerpt:
            retained_copy=[];length=0
            for i in audible:
                if i<=run[-1] or i in selected:continue
                retained_copy.append(i);length+=len(spoken(words[i]['word']))
                if length>=len(quote):break
            if length!=len(quote):return reject('surviving copy is not a complete source unit')
            witness_indices.update(retained_copy)
    groups={words[i].get('alignmentGroup') for i in removed}
    if None in groups or any(words[i].get('alignmentGroup') in groups for i in audible if i not in selected):return reject('shared or missing acoustic group')
    if any(i not in token_members and (len(spoken(words[i]['word']))!=1 or not words[i].get('alignmentStable') or words[i].get('alignmentProbability',0)<.8 or spoken(words[i].get('acousticRecognized',''))!=spoken(words[i]['word'])) for i in removed):return reject('weak or inexact two-window occurrence')
    if not before or any(not isinstance(t.get('time'),(int,float)) or not math.isfinite(t['time']) for t in before):return reject('missing original trace times')
    if any(a['time']>b['time'] for a,b in zip(before,before[1:])):return reject('unordered original trace')
    matches=[]
    seen_tokens=set()
    for i in removed:
        token=token_members.get(i)
        if token and token['id'] in seen_tokens:continue
        if token:seen_tokens.add(token['id'])
        text=token['text'] if token else spoken(words[i]['word'])
        center=token['center'] if token else words[i].get('acousticCenter')
        if not isinstance(center,(int,float)) or not math.isfinite(center):return reject('missing acoustic centre')
        hits=[n for n,t in enumerate(before) if spoken(t['text'])==text and t.get('probability',0)>=.8 and abs(t['time']-center)<=.08]
        if len(hits)!=1:return reject('ambiguous third-window occurrence')
        matches.append(hits[0])
    if matches!=sorted(set(matches)):return reject('reused third-window occurrence')
    # Both copies must independently exist. A missing surviving copy in the
    # original audition is not permission to accept its disappearance later.
    witnesses=[];seen_witness_tokens=set()
    for i in sorted(witness_indices):
        token=__import__('acoustic_atoms').token_at(words,i) if words[i].get('alignmentToken') else None
        if token:
            if not set(token['members']).issubset(witness_indices):return reject('partial surviving token')
            if token['id'] in seen_witness_tokens:continue
            seen_witness_tokens.add(token['id']);text=token['text'];center=token['center']
        else:
            w=words[i]
            if not w.get('alignmentStable') or w.get('alignmentProbability',0)<.8 or spoken(w.get('acousticRecognized',''))!=spoken(w['word']):return reject('weak surviving copy')
            text=spoken(w['word']);center=w.get('acousticCenter')
        if not isinstance(center,(int,float)) or not math.isfinite(center):return reject('missing surviving centre')
        hits=[n for n,t in enumerate(before) if spoken(t['text'])==text and t.get('probability',0)>=.8 and abs(t['time']-center)<=.08]
        if len(hits)!=1 or hits[0] in matches or hits[0] in witnesses:return reject('missing or ambiguous surviving copy')
        witnesses.append(hits[0])
    expected=''.join(t['text'] for n,t in enumerate(before) if n not in matches)
    protected=Counter(FACT.findall(spoken(''.join(words[i]['word'] for i in audible if i not in selected))))
    observed=Counter(FACT.findall(spoken(expected)))
    if any(observed[term]<count for term,count in protected.items()):return reject('protected source wording missing from baseline')
    return {'version':VERSION,'passed':True,'expected':spoken(expected),'beforeRecognized':spoken(''.join(t['text'] for t in before)),'removedOccurrences':matches,'retainedOccurrences':witnesses,'indices':removed,'atomicTokens':[t['id'] for t in tokens]}

def verify(evidence,words,before,cuts,heard):
    if not evidence.get('passed') or not cuts or spoken(heard)!=evidence['expected']:return False
    if any(not all(isinstance(c.get(k),(int,float)) and math.isfinite(c[k]) for k in ('start','end')) or c['start']>=c['end'] for c in cuts):return False
    if any(a['end']>b['start'] for a,b in zip(cuts,cuts[1:])):return False
    removed=set(evidence['indices']);occurrences=set(evidence['removedOccurrences'])
    # Both original recognized tokens and all canonical retained word centres
    # stay protected, including uncertain neighbours. No normal-word waiver.
    centres=[t['time'] for n,t in enumerate(before) if n not in occurrences and spoken(t['text'])]
    for i,w in enumerate(words):
        if i in removed or not spoken(w['word']):continue
        center=w.get('acousticCenter')
        if not isinstance(center,(int,float)) or not math.isfinite(center):return False
        centres.append(center)
    if any(c['start']-.06<t<c['end']+.06 for t in centres for c in cuts):return False
    return all(any(c['start']<=before[n]['time']<=c['end'] for c in cuts) for n in occurrences)

def constrain_candidate(evidence,words,before,cuts):
    """Shrink an already proposed cut around all three original anchor views.

    Never authorizes a deletion: the newly bounded union still needs its own
    retained-audio audition and verify(). No protected centre can be waived.
    """
    if not evidence.get('passed') or not cuts:return None
    removed=set(evidence['indices']);occurrences=set(evidence['removedOccurrences'])
    centres=[t['time'] for n,t in enumerate(before) if n not in occurrences and spoken(t['text'])]
    for i,w in enumerate(words):
        if i in removed or not spoken(w['word']):continue
        center=w.get('acousticCenter')
        if not isinstance(center,(int,float)) or not math.isfinite(center):return None
        centres.append(center)
    result=[];covered=set()
    for cut in cuts:
        start,end=cut.get('start'),cut.get('end')
        if not all(isinstance(t,(int,float)) and math.isfinite(t) for t in (start,end)) or start>=end:return None
        members=[n for n in occurrences if start<=before[n]['time']<=end]
        if not members:return None
        first=min(before[n]['time'] for n in members);last=max(before[n]['time'] for n in members)
        if any(first<=t<=last for t in centres):return None
        left=[t for t in centres if t<first];right=[t for t in centres if t>last]
        # nextafter keeps the existing strict 60 ms protection even at a
        # floating-point boundary; it does not reduce the protection margin.
        if left:start=max(start,math.nextafter(max(left)+.06,math.inf))
        if right:end=min(end,math.nextafter(min(right)-.06,-math.inf))
        if start>=end or not start<=first<=last<=end:return None
        result.append({'start':start,'end':end});covered.update(members)
    if covered!=occurrences or any(a['end']>b['start'] for a,b in zip(result,result[1:])):return None
    if any(c['start']-.06<t<c['end']+.06 for t in centres for c in result):return None
    return result
