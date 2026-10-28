"""Verified removed audio remains excluded across later boundary calibration.

Only server-owned source anchors authorize bounds. Client timing/verification
flags are never evidence, and restored words create no exclusion.
"""
import copy,math
VERSION=2

def collect(source,edits):
    refs={r['id']:r for r in source};out=[]
    for row in edits:
        original=refs.get(row.get('id'))
        if not original:continue
        removed=set(row.get('removed',[]))
        for index,w in enumerate(original['words']):
            if not row.get('deleted') and index not in removed:continue
            if not w.get('alignmentVerified') or not any(c.isalnum() for c in w['word']):continue
            a,b=w.get('start'),w.get('end')
            if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (a,b)) or not 0<=a<b:continue
            if w.get('alignmentToken') and w.get('alignmentTokenVerified')!=w['alignmentToken'].get('id'):continue
            out.append({'id':row['id'],'index':index,'word':w['word'],'start':a,'end':b,**({'cutAudioWitness':copy.deepcopy(w['cutAudioWitness'])} if isinstance(w.get('cutAudioWitness'),dict) else {})})
    return out

def constrain(clips,excluded):
    """Only retract leaked handles; never split speech or guess a word edge."""
    result=copy.deepcopy(clips);changes=[];blocking=[]
    for index,c in enumerate(result):
        before=[c['start'],c['end']];reasons=[]
        for word in excluded:
            a,b=word['start'],word['end'];lo,hi=c['start'],c['end']
            if min(hi,b)-max(lo,a)<=.000001:continue
            if lo<a and hi<=b:c['end']=a
            elif a<=lo and b<hi:c['start']=b
            else:
                blocking.append({'id':c['id'],'clipIndex':index,'reason':'保留片段穿过已核验删除原音，不能拆字或恢复已删声音','excluded':word});continue
            reasons.append(word)
        if before!=[c['start'],c['end']]:
            changes.append({'id':c['id'],'clipIndex':index,'before':before,'after':[c['start'],c['end']],'excluded':reasons})
            spoken=[w for w in c.get('words',[]) if any(ch.isalnum() for ch in w['word'])]
            centres=[w.get('acousticCenter') for w in spoken]
            if not c['start']<c['end'] or not spoken or any(not isinstance(t,(int,float)) or not c['start']<=t<=c['end'] for t in centres):
                blocking.append({'id':c['id'],'clipIndex':index,'reason':'已删声音区间与正常保留字冲突或证据不足，保留原稿待核'})
    return result,{'version':VERSION,'changes':changes,'blocking':blocking}

def leaks(clips,excluded):
    return [{'clipIndex':i,'id':c['id'],'excluded':w,'reason':'最终取音仍包含已核验删除原音'} for i,c in enumerate(clips) for w in excluded if min(c['end'],w['end'])-max(c['start'],w['start'])>.000001]
