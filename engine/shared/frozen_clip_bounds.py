"""Immutable source ranges; never a manual-edge ASR exemption."""
import copy,math
VERSION=2


def key(clip):return (clip.get('id'),clip.get('firstIndex'),clip.get('lastIndex'))


def mapping(clips,frozen):
    for c in [*clips,*frozen]:
        if (not isinstance(c.get('id'),str) or type(c.get('firstIndex')) is not int or type(c.get('lastIndex')) is not int
            or not 0<=c['firstIndex']<=c['lastIndex']):raise ValueError('取音原字范围无效')
    refs={key(c):i for i,c in enumerate(clips)};out={}
    if len(refs)!=len(clips):raise ValueError('取音片段归属不唯一，不能沿用边界')
    for item in frozen:
        k=key(item)
        if k not in refs or k in out:raise ValueError('沿用取音与当前选词不一致')
        if any(type(item.get(n)) not in (int,float) or not math.isfinite(item[n]) for n in ('start','end')) or not 0<=item['start']<item['end']:
            raise ValueError('沿用取音边界无效')
        out[k]=item
    return refs,out


def apply(clips,frozen):
    _,wanted=mapping(clips,frozen);out=copy.deepcopy(clips)
    for c in out:
        if key(c) in wanted:c.update({n:wanted[key(c)][n] for n in ('start','end')})
    return out


def indices(clips,frozen):
    refs,wanted=mapping(clips,frozen)
    return {refs[k] for k in wanted}


def verify(clips,frozen):
    _,wanted=mapping(clips,frozen)
    if any(c[n]!=wanted[key(c)][n] for c in clips if key(c) in wanted for n in ('start','end')):
        raise ValueError('局部执行改变了非目标实际取音，未输出')
    return {'version':VERSION,'passed':True,'frozenClipCount':len(wanted),'manualEdgeExemption':False}


def retract(frozen,excluded):
    """Subtract only server-verified NEW target deletions from old handles.

    It never authorizes an interior split; the worker still proves normal
    neighbor margins and audits the actual source run without exemptions.
    """
    out=copy.deepcopy(frozen);changes=[]
    for c in out:
        before=[c['start'],c['end']];reasons=[]
        for w in excluded:
            a,b=w['start'],w['end'];lo,hi=c['start'],c['end']
            if min(hi,b)-max(lo,a)<=.000001:continue
            if lo<a and hi<=b:c['end']=a
            elif a<=lo and b<hi:c['start']=b
            else:raise ValueError('已删目标声音穿过非目标取音内部，不能拆正常字')
            reasons.append(copy.deepcopy(w))
        if before!=[c['start'],c['end']]:
            if not c['start']<c['end']:raise ValueError('目标声音与完整保留片段冲突，未输出')
            changes.append({'id':c['id'],'firstIndex':c['firstIndex'],'lastIndex':c['lastIndex'],'before':before,'after':[c['start'],c['end']],'excluded':reasons})
    return out,changes


def guard_margin(clip,local,first,last,retractions):
    entry=next((e for e in retractions if key(e)==key(clip)),None)
    if entry is None:return
    for side,n in [('start',0),('end',1)]:
        if entry['before'][n]==entry['after'][n]:continue
        gap=local[first]['start']-clip['start'] if side=='start' else clip['end']-local[last]['end']
        if not math.isfinite(gap) or round(gap,9)<.06:raise ValueError('目标声音与正常邻字不足60毫秒安全气口，保留原稿')
