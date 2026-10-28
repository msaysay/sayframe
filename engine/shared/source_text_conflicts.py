"""Read-only source transcript conflicts, never permission to cut a word.

Duplicated ASR text can straddle two caption rows while the underlying source
is played only once. Overlapping word estimates are a reason to review the
transcript, not evidence of either one or two real spoken occurrences.
"""
import math,re
VERSION=1
NOTE='识别时间是估计值，不能证明只说了一遍。先对照原音与文字，不按这两个字的估计时间切音；本次没有修改文字或声音。'


def inspect(project,source,ref):
    if project.get('sourceId')!=source.get('id') or not isinstance(ref,dict):return None
    key=(ref.get('id'),ref.get('wordIndex'))
    if not isinstance(key[0],str) or type(key[1]) is not int:return None
    rows=source.get('segments',[]);edited=project.get('segments',[])
    if len({r['id'] for r in rows})!=len(rows) or len({r['id'] for r in edited})!=len(edited):return None
    originals={r['id']:r for r in rows};current={r['id']:r for r in edited}
    flat=[(r['id'],i,w) for r in rows for i,w in enumerate(r['words']) if any(c.isalnum() for c in w['word'])]
    positions=[i for i,(sid,index,_) in enumerate(flat) if (sid,index)==key]
    if len(positions)!=1:return None
    at=positions[0]
    if ref.get('word') is not None and ref['word']!=flat[at][2]['word']:return None
    for n in (at-1,at):
        if not 0<=n<len(flat)-1:continue
        left,right=flat[n:n+2];word=left[2]['word']
        # Whole Chinese words only; never manufacture a per-letter interval
        # inside a shared Latin/multi-character acoustic token.
        if not re.fullmatch(r'[\u4e00-\u9fff]',word) or right[2]['word']!=word:continue
        refs=[];clips=[];valid=True
        for sid,index,w in (left,right):
            row=current.get(sid)
            if (row is None or row.get('deleted') or index in row.get('removed',[])
                or row.get('caption') is not None or str(index) in row.get('wordCorrections',{})
                or [v['word'] for v in row['words']]!=[v['word'] for v in originals[sid]['words']]):valid=False;break
            values=(w.get('start'),w.get('end'))
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in values) or not 0<=values[0]<values[1]:valid=False;break
            occurrences=[(i,c) for i,c in enumerate(project.get('clips',[])) if c['id']==sid and any(v.get('index')==index and v.get('word')==word for v in c.get('words',[]))]
            if len(occurrences)!=1:valid=False;break
            clips.append(occurrences[0]);refs.append({'id':sid,'wordIndex':index,'word':word,'start':values[0],'end':values[1]})
        if not valid:continue
        overlap=min(refs[0]['end'],refs[1]['end'])-max(refs[0]['start'],refs[1]['start'])
        if overlap<=.001:continue
        a,b=clips
        if a[0]!=b[0]:
            if b[0]!=a[0]+1:continue
            # Real source-range reuse is a different audio-integrity failure.
            # It must never be explained away as a transcript-only issue.
            if min(a[1]['end'],b[1]['end'])-max(a[1]['start'],b[1]['start'])>.001:continue
            if b[1]['start']<a[1]['end']-.001:continue
        return {'version':VERSION,'status':'overlapping-transcript-estimates','sourceId':source['id'],
                'word':word,'refs':refs,'sourceEstimateOverlapSeconds':round(overlap,6),
                'physicalSourceReuse':False,'changedSpeech':False,'changedTranscript':False,
                'message':f'相邻两个“{word}”的识别时间重叠，但成片没有重复取用这段原音。可能是识别多写，也可能是声音定位不准，先核对文字。',
                'note':NOTE}
    return None
