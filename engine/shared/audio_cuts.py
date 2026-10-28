"""Non-destructive intra-run original-audio removals, mirrored by audio-cuts.mjs."""
import re,math

def audio_run_key(c):return c.get('audioFragment',{}).get('runKey',f"{c['id']}:{c['firstIndex']}:{c['lastIndex']}")

def validate_audio_cuts(value,source,duration=math.inf):
    if not isinstance(value,dict) or len(value)>200:raise ValueError('段中裁除清单无效')
    segments={s['id']:s for s in source};ids=set();count=0;result={}
    for key,ranges in value.items():
        match=re.fullmatch(r'(.+):(0|[1-9]\d*):(0|[1-9]\d*)',key) if isinstance(key,str) else None
        s=segments.get(match[1]) if match else None;first,last=(int(match[2]),int(match[3])) if match else (-1,-1)
        if s is None or first>last or last>=len(s['words']) or not isinstance(ranges,list) or not 1<=len(ranges)<=20:raise ValueError('段中裁除原词组引用无效')
        previous=-math.inf;clean=[]
        for r in ranges:
            if not isinstance(r,dict) or any(k not in ('id','start','end','wordCut') for k in r) or not isinstance(r.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',r['id']) or r['id'] in ids or type(r.get('wordCut')) is not bool or any(type(r.get(k)) not in (float,int) or not math.isfinite(r[k]) for k in ('start','end')) or r['start']<s['words'][first]['start']-1e-6 or r['end']>min(duration,s['words'][last]['end'])+1e-6 or r['end']-r['start']<.001-1e-6 or r['start']<previous+.001-1e-6:raise ValueError('裁除范围须有明确授权、原音时间且不重叠，间隔至少1毫秒')
            if not r['wordCut'] and any(w['end']>w['start'] and w['start']<r['end']-1e-6 and w['end']>r['start']+1e-6 for w in s['words'][first:last+1]):raise ValueError('范围涉及ASR词，需明确允许裁除发音或完整词')
            count+=1
            if count>200:raise ValueError('段中裁除最多200个范围')
            ids.add(r['id']);previous=r['end'];clean.append({k:r[k] for k in ('id','start','end','wordCut')})
        result[key]=clean
    return result

def apply_audio_cuts(clips,source,cuts,max_clips=400):
    if not cuts:return clips
    rows={s['id']:s for s in source};out=[]
    for c in clips:
        key=audio_run_key(c);ranges=[r for r in cuts.get(key,[]) if r['end']>c['start']+1e-6 and r['start']<c['end']-1e-6]
        if not ranges:out.append(c);continue
        parts=[];at=c['start'];before=None
        for r in ranges:
            start,end=max(c['start'],r['start']),min(c['end'],r['end'])
            if start>at+1e-6:parts.append({'start':at,'end':start,'beforeId':before,'afterId':r['id']})
            at=max(at,end);before=r['id']
        if c['end']>at+1e-6:parts.append({'start':at,'end':c['end'],'beforeId':before,'afterId':None})
        if not parts or any(p['end']-p['start']<.04-1e-6 for p in parts):raise ValueError('裁除后每个保留切片至少0.04秒，整段裁除请删除句子')
        original=[dict(w,index=i) for i,w in enumerate(rows[c['id']]['words']) if c['firstIndex']<=i<=c['lastIndex']]
        removed=[{'side':'removed','index':w['index'],'word':w['word'],'originalStart':w['start'],'originalEnd':w['end'],'point':next((r['start'] for r in ranges if r['start']<w['end'] and r['end']>w['start']),w['start'])} for w in original if w['end']>w['start'] and not any(w['start']<p['end']-1e-6 and w['end']>p['start']+1e-6 for p in parts)]
        for index,p in enumerate(parts):
            words=[w for w in original if w['end']>w['start'] and w['start']<p['end']-1e-6 and w['end']>p['start']+1e-6];first=words[0] if words else None;last=words[-1] if words else None
            piece={**c,'start':p['start'],'end':p['end'],'firstIndex':first['index'] if first else c['firstIndex'],'lastIndex':last['index'] if last else c['lastIndex'],'wordStart':first['start'] if first else p['start'],'wordEnd':last['end'] if last else p['start'],'text':''.join(w['word'] for w in words),'audioFragment':{'runKey':key,'index':index,'count':len(parts),'beforeId':p['beforeId'],'afterId':p['afterId']},'captionTiming':'word-aligned-audio-cut' if words else 'silent-original'}
            if c.get('captionTiming')=='estimated':piece['captionCorrectionInactive']=True
            if 'words' in c:piece['words']=[{**w,'emphasis':any(x['index']==w['index'] and x.get('emphasis') is True for x in c['words'])} for w in words]
            partial=[]
            if first and p['start']>first['start']+1e-6:partial.append({'side':'start','index':first['index'],'word':first['word'],'originalStart':first['start'],'originalEnd':first['end'],'point':p['start']})
            if last and p['end']<last['end']-1e-6:partial.append({'side':'end','index':last['index'],'word':last['word'],'originalStart':last['start'],'originalEnd':last['end'],'point':p['end']})
            if index==0:partial.extend(removed)
            if partial:piece['partialWordCuts']=partial
            else:piece.pop('partialWordCuts',None)
            out.append(piece)
    if len(out)>max_clips:raise ValueError('裁除后最多400个保留切片，请分段处理')
    return out
