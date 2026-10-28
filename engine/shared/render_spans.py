"""Encode uninterrupted source speech once; keep logical clips for editing/cues.

Sentence labels are not physical cuts. Re-encoding each adjacent sentence creates
frame-rounding seams even when the source ranges touch exactly.
"""
def render_spans(clips):
    spans=[]
    for index,c in enumerate(clips):
        if spans and abs(spans[-1]['end']-c['start'])<1e-7:
            spans[-1]['end']=c['end'];spans[-1]['indices'].append(index)
        else:spans.append({'start':c['start'],'end':c['end'],'indices':[index]})
    return spans

def assign_durations(clips,span,actual,speed):
    planned=(span['end']-span['start'])/speed
    if actual<=0 or planned<=0:raise ValueError('连续片段时长无效')
    # Keep word offsets unchanged. Only the group's final clip owns encoder
    # rounding, rather than introducing an extra seam at every sentence.
    for index in span['indices']:
        c=clips[index];c['outputDuration']=(c['end']-c['start'])/speed;c['speed']=speed
    last=clips[span['indices'][-1]];last['outputDuration']+=actual-planned
    if last['outputDuration']<=0:raise ValueError('连续片段末句过短')
