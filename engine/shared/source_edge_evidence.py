"""Disambiguate a boundary glyph only with two original-audio observations.

No generic fuzzy or phonetic matching: this narrow grammatical 的/地/得
equivalence never removes a character, invents a time, or changes transcript.
The original source must independently support every character at that edge.
"""
DE=frozenset('的地得')


def trace(model,audio,offset=0):
    """Expose the posterior of the DE spelling class, not a lower threshold.

    Competing spellings can split a clear syllable's probability between
    several token IDs. Retain their combined probability from original logits.
    The ordinary recognizer and its timing/word output are unchanged.
    """
    import numpy as np
    original=model.session;captured=[]
    class Scores:
        def run(self,*args,**kwargs):
            result=original.run(*args,**kwargs);captured.append(result[0][0]);return result
    model.session=Scores()
    try:rows=model.trace(audio,offset)
    finally:model.session=original
    ids=[i for i,token in model.tokens.items() if token.replace('▁','') in DE]
    if captured and ids:
        scores=captured[0]
        for row in rows:
            if row['text'] in DE:
                logits=scores[row['frame']]
                row['orthographyClassProbability']=float(np.exp(np.logaddexp.reduce(logits[ids])-np.logaddexp.reduce(logits)))
    return rows


def observation(expected,anchor,peer,trace,second):
    def raw(point,rows):
        try:item=rows[int(point['group'])]
        except (KeyError,TypeError,ValueError,IndexError):return None
        if len(item['text'])!=1 or abs(item['time']-point['time'])>.001:return None
        return {'actual':item['text'],'probability':item['probability'],'time':item['time'],**({'classProbability':item['orthographyClassProbability']} if 'orthographyClassProbability' in item else {})}
    return {'expected':expected,'first':raw(anchor,trace),'second':raw(peer,second)}


def confirmed(wanted,heard,evidence):
    if len(wanted)!=len(heard) or len(evidence)!=len(wanted) or wanted==heard:return False
    if not any(a!=b for a,b in zip(wanted,heard)):return False
    for original,actual,item in zip(wanted,heard,evidence):
        if original!=actual and not (original in DE and actual in DE):return False
        if not isinstance(item,dict) or item.get('expected')!=original:return False
        a=item.get('first') or {};b=item.get('second') or {}
        def supports(point):
            if point.get('actual')==actual and point.get('probability',0)>=.8:return True
            return original in DE and actual in DE and point.get('actual') in DE and point.get('classProbability',0)>=.8
        if not supports(a) or not supports(b):return False
        if abs(a.get('time',0)-b.get('time',0))>.08:return False
    return True


def resolve(expected,heard,evidence):
    from speech_boundary_text import matches
    start,end=matches(expected,heard);used=[]
    clean=lambda text:''.join(c for c in text if c.isalnum()).upper()
    want=clean(expected);got=clean(heard)
    if not start and want and want[0] not in '呃嗯额啊哦' and confirmed(want[:2],got[:2],evidence.get('start',[])):
        start=True;used.append('start')
    if not end and confirmed(want[-2:],got[-2:],evidence.get('end',[])):
        end=True;used.append('end')
    return {'start':start,'end':end,'orthographyOnly':used}
