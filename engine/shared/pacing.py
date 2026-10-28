"""Preserve original pauses without restoring removed or reordered speech."""
import math
import re
from audio_cuts import audio_run_key,validate_audio_cuts,apply_audio_cuts
from smart_pauses import validate_pauses,apply_pauses
def word_index(source):
    rows=[{**w,'key':str(s.get('id'))+':'+str(i)} for s in source for i,w in enumerate(s.get('words',[]))]
    return rows,{w['key']:i for i,w in enumerate(rows)}

def clip_edge_key(c):return audio_run_key(c)

def clip_edge_limits(c,source,duration=math.inf,permission=None):
    rows,positions=word_index(source);first=positions.get(str(c['id'])+':'+str(c['firstIndex']));last=positions.get(str(c['id'])+':'+str(c['lastIndex']))
    segment=next((s for s in source if s['id']==c['id']),None)
    if first is None or last is None or last<first or segment is None or c['lastIndex']>=len(segment['words']):raise ValueError('切点原词引用无效')
    a,b=rows[first],rows[last]
    permission=permission or {};before=first-1;after=last+1
    while before>=0 and rows[before]['start']==rows[before]['end'] and not any(ch.isalnum() for ch in rows[before]['word']):before-=1
    while after<len(rows) and rows[after]['start']==rows[after]['end'] and not any(ch.isalnum() for ch in rows[after]['word']):after+=1
    return {'startMin':max(0,min(a['start'],rows[before]['end'] if before>=0 else 0)),'startMax':max(a['start'],a['end']-.001) if permission.get('startWordCut') else a['start'],'endMin':min(b['end'],b['start']+.001) if permission.get('endWordCut') else b['end'],'endMax':min(duration,max(b['end'],rows[after]['start'] if after<len(rows) else duration))}

def validate_pacing(value,source,duration=math.inf):
    p=value if value is not None else {'mode':'tight','overrides':{}}
    if not isinstance(p,dict) or p.get('mode') not in ('original','tight') or not isinstance(p.get('overrides'),dict) or len(p['overrides'])>400:raise ValueError('气口设置无效')
    _,positions=word_index(source)
    for key,choice in p['overrides'].items():
        parts=key.split('>')
        if len(parts)!=2 or parts[0] not in positions or positions.get(parts[1])!=positions[parts[0]]+1 or choice not in ('keep','tight'):raise ValueError('气口引用无效')
    result={'mode':p['mode'],'overrides':dict(p['overrides'])}
    if 'sentenceGap' in p:
        if type(p['sentenceGap']) not in (int,float) or p['sentenceGap'] not in (0,.12,.2):raise ValueError('句间节奏无效')
        result['sentenceGap']=p['sentenceGap']
    if 'edges' in p:
        if not isinstance(p['edges'],dict) or len(p['edges'])>400:raise ValueError('手动切点设置无效')
        result['edges']={}
        for key,edge in p['edges'].items():
            match=re.fullmatch(r'(.+):(0|[1-9]\d*):(0|[1-9]\d*)',key) if isinstance(key,str) else None
            if not match or not isinstance(edge,dict) or not edge or any(k not in ('start','end','startWordCut','endWordCut') for k in edge):raise ValueError('手动切点引用无效')
            for side in ('start','end'):
                if side+'WordCut' in edge and (type(edge[side+'WordCut']) is not bool or side not in edge):raise ValueError('词内裁切授权无效')
            limit=clip_edge_limits({'id':match[1],'firstIndex':int(match[2]),'lastIndex':int(match[3])},source,duration,edge)
            for k,t in ((k,edge[k]) for k in ('start','end') if k in edge):
                if type(t) not in (float,int) or not math.isfinite(t) or t<limit[k+'Min']-1e-6 or t>limit[k+'Max']+1e-6:raise ValueError('切点超出原词之间的可调范围')
            result['edges'][key]=dict(edge)
    if 'audioCuts' in p:result['audioCuts']=validate_audio_cuts(p['audioCuts'],source,duration)
    if 'pauses' in p:result['pauses']=validate_pauses(p['pauses'],duration)
    return result

def apply_pacing(clips,source,duration,value,max_clips=400):
    p=validate_pacing(value,source,duration);rows,positions=word_index(source);result=[]
    for c in clips:
        copy={**c,'wordStart':c['start'],'wordEnd':c['end']}
        first=positions.get(str(c.get('id'))+':'+str(c.get('firstIndex')));last=positions.get(str(c.get('id'))+':'+str(c.get('lastIndex')))
        if p['mode']=='original' and first is not None and last is not None:
            a,b=rows[first],rows[last]
            if c['start']!=a['start'] or c['end']!=b['end']:raise ValueError('气口原词时间不匹配')
            before=rows[first-1]['end'] if first else 0;after=rows[last+1]['start'] if last+1<len(rows) else duration
            copy['start']=max(0,c['start']-min(.06,max(0,(c['start']-before)/2)))
            copy['end']=min(duration,c['end']+min(.06,max(0,(after-c['end'])/2)))
        result.append(copy)
    for left,right in zip(result,result[1:]):
        a=str(left.get('id'))+':'+str(left.get('lastIndex'));b=str(right.get('id'))+':'+str(right.get('firstIndex'));key=a+'>'+b
        if a in positions and positions.get(b)==positions[a]+1 and right['wordStart']>=left['wordEnd']:
            keep=p['overrides'].get(key,'keep' if p['mode']=='original' else 'tight')=='keep'
            keep=keep or any(q['keep'] and min(q['end'],right['wordStart'])-max(q['start'],left['wordEnd'])>.05 for q in p.get('pauses',[]))
            left['end']=right['wordStart'] if keep else left['wordEnd'];right['start']=right['wordStart']
    for c in result:
        e=p.get('edges',{}).get(clip_edge_key(c),{})
        for side in ('start','end'):
            if side in e:c[side]=e[side]
    for left,right in zip(result,result[1:]):
        a=str(left['id'])+':'+str(left['lastIndex']);b=str(right['id'])+':'+str(right['firstIndex'])
        if a in positions and positions.get(b)==positions[a]+1 and right['wordStart']>=left['wordEnd'] and left['end']>right['start']+1e-6:
            l='end' in p.get('edges',{}).get(clip_edge_key(left),{});r='start' in p.get('edges',{}).get(clip_edge_key(right),{})
            if l and r:raise ValueError('相邻手动切点重叠，请缩短前段或后移后段入点')
            if r:left['end']=right['start']
            elif l:right['start']=left['end']
    if p['mode']=='tight' and p.get('sentenceGap',0)>0:
        for index,c in enumerate(result):
            e=p.get('edges',{}).get(clip_edge_key(c),{});limit=clip_edge_limits(c,source,duration)
            prev=result[index-1] if index else None
            already=prev and prev['end']>=c['wordStart'] and positions.get(str(c['id'])+':'+str(c['firstIndex']))==positions.get(str(prev['id'])+':'+str(prev['lastIndex']))+1
            if 'start' not in e and not already:c['start']=max(limit['startMin'],c['start']-.04)
            if 'end' not in e:c['end']=min(limit['endMax'],c['end']+.04)
        for left,right in zip(result,result[1:]):
            if left['end']>right['start'] and left['wordEnd']<=right['wordStart'] and positions.get(str(right['id'])+':'+str(right['firstIndex']))==positions.get(str(left['id'])+':'+str(left['lastIndex']))+1:
                if 'end' in p.get('edges',{}).get(clip_edge_key(left),{}):right['start']=left['end']
                elif 'start' in p.get('edges',{}).get(clip_edge_key(right),{}):left['end']=right['start']
                else:left['end']=right['start']=(left['end']+right['start'])/2
    if p['mode']=='tight' and p.get('sentenceGap',0)>0:
        for left,right in zip(result,result[1:]):
            punctuation=(left.get('text','') or rows[positions[str(left['id'])+':'+str(left['lastIndex'])]]['word'])[-1:]+(right.get('text','') or rows[positions[str(right['id'])+':'+str(right['firstIndex'])]]['word'])[:1]
            if (left['id']==right['id'] and not re.search(r'[，。！？；,!?;]',punctuation)) or 'end' in p.get('edges',{}).get(clip_edge_key(left),{}) or 'start' in p.get('edges',{}).get(clip_edge_key(right),{}):continue
            existing=max(0,left['end']-left['wordEnd'])+max(0,right['wordStart']-right['start']);budget=max(0,p['sentenceGap']-existing)
            if not budget:continue
            ll=clip_edge_limits(left,source,duration);rl=clip_edge_limits(right,source,duration)
            a=max(0,ll['endMax']-left['end']);b=max(0,right['start']-rl['startMin'])
            if positions.get(str(right['id'])+':'+str(right['firstIndex']))==positions.get(str(left['id'])+':'+str(left['lastIndex']))+1:
                gap=max(0,right['start']-left['end']);a=min(a,gap/2);b=min(b,gap/2)
            take_a=min(a,budget/2);take_b=min(b,budget-take_a);extra=min(a-take_a,budget-take_a-take_b)
            left['end']+=take_a+extra;right['start']-=take_b
    for c in result:
        if c['end']-c['start']<.04-1e-6:raise ValueError('保留片段不能短于0.04秒，请重新调整首尾')
        first=rows[positions[str(c['id'])+':'+str(c['firstIndex'])]];last=rows[positions[str(c['id'])+':'+str(c['lastIndex'])]];cuts=[]
        if c['start']>first['start']+1e-6:cuts.append({'side':'start','index':c['firstIndex'],'word':first['word'],'originalStart':first['start'],'originalEnd':first['end'],'point':c['start']})
        if c['end']<last['end']-1e-6:cuts.append({'side':'end','index':c['lastIndex'],'word':last['word'],'originalStart':last['start'],'originalEnd':last['end'],'point':c['end']})
        if cuts:c['partialWordCuts']=cuts
    return apply_pauses(apply_audio_cuts(result,source,p.get('audioCuts'),max_clips=max_clips),source,p.get('pauses'),max_clips=max_clips)
