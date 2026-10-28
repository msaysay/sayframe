"""Compute all internal seams together after acoustic timing revision.

Old caption endpoints can precede the corrected first syllable. Updating a
chain one pair at a time would reject a valid seam against the *old* next end,
then update that end later, leaving repeated source sound at the earlier join.
Only an uninterrupted retained source chain may use these shared seams.
"""
import copy


def normalize(clips,links,locked=()):
    locked=set(locked)
    # Two preserved ranges may deliberately contain a real pause. Do not
    # manufacture a shared seam across it merely because source text adjoins.
    links={i for i in links if not (i in locked and i+1 in locked and clips[i]['end']!=clips[i+1]['start'])}
    out=copy.deepcopy(clips);groups=[]
    for index in sorted(links):
        if groups and groups[-1][-1]==index:groups[-1].append(index+1)
        else:groups.append([index,index+1])
    for indices in groups:
        seams=[clips[i]['end'] if i in locked else clips[i+1]['start'] if i+1 in locked else (clips[i]['wordEnd']+clips[i+1]['wordStart'])/2 for i in indices[:-1]]
        boundaries=[clips[indices[0]]['start'],*seams,clips[indices[-1]]['end']]
        if any(a>=b for a,b in zip(boundaries,boundaries[1:])):
            if set(indices)&locked:raise ValueError('沿用取音与新局部切口冲突，未输出')
            continue
        for n,index in enumerate(indices):
            out[index]['start']=boundaries[n];out[index]['end']=boundaries[n+1]
    return out
