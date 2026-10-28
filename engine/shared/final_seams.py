"""Source-bound cues at actual encoded filler and phrase-cut joins.

Two unprompted local recognition windows may raise a listening cue. They never
authorize a cut, restore/change words, waive normal speech, or certify hearing.
"""
import copy,json,math,re
from pathlib import Path
VERSION=3
MODEL='sensevoice-int8-ctc'
FILLER=re.compile('[呃嗯啊额哦]+')


def plain(text):return ''.join(c.upper() for c in text if c.isalnum())


def timeline(project):
    words=[];cursor=float(project.get('coverDuration',0))
    for clip in project.get('clips',[]):
        rate=clip.get('speed',project.get('settings',{}).get('speed',1))
        if type(rate) not in (float,int) or not math.isfinite(rate) or rate<=0:raise ValueError('成片接缝时间无效')
        duration=clip.get('outputDuration',(clip['end']-clip['start'])/rate)
        if not all(type(v) in (float,int) and math.isfinite(v) for v in [rate,duration,cursor]) or rate<=0 or duration<=0:raise ValueError('成片接缝时间无效')
        for w in clip.get('words',[]):
            if not plain(w['word']):continue
            a=cursor+max(0,min(duration,(w['start']-clip['start'])/rate))
            b=cursor+max(0,min(duration,(w['end']-clip['start'])/rate))
            words.append({'id':clip['id'],'wordIndex':w.get('index'),'word':w['word'],'nearSeconds':round(a,6),'endSeconds':round(b,6),'clipStart':round(cursor,6),'clipEnd':round(cursor+duration,6)})
        cursor+=duration
    return words


def targets(project,redactions=()):
    audible=timeline(project);by_ref={(w['id'],w['wordIndex']):n for n,w in enumerate(audible)};out=[]
    for row in project.get('segments',[]):
        if row.get('deleted'):continue
        removed=set(row.get('removed',[]));runs=[]
        for i in sorted(removed):
            if runs and i==runs[-1][-1]+1:runs[-1].append(i)
            else:runs.append([i])
        for run in runs:
            quote=plain(''.join(row['words'][i]['word'] for i in run))
            if not quote:continue
            right=next((by_ref[(row['id'],i)] for i in range(run[-1]+1,len(row['words'])) if (row['id'],i) in by_ref),None)
            left=next((by_ref[(row['id'],i)] for i in range(run[0]-1,-1,-1) if (row['id'],i) in by_ref),None)
            if right is None and left is None:continue
            point=audible[right]['nearSeconds'] if right is not None else audible[left]['clipEnd']
            # Do not flag intentionally beeped material or silently audit it as
            # if the underlying voice were still present.
            if any(r.get('action')=='beep' and point+.3>r['start'] and point-.3<r['end'] for r in redactions):continue
            pos=right if right is not None else min(left+1,len(audible)-1);ref=audible[pos]
            neighbors=[]
            if left is not None:neighbors.extend(audible[max(0,left-2):left+1])
            if right is not None:neighbors.extend(audible[right:right+3])
            out.append({'id':row['id'],'indices':run,'quote':quote,'kind':'filler' if FILLER.fullmatch(quote) else 'phrase',
                        'neighbors':copy.deepcopy(neighbors),'nearSeconds':round(point,6),
                        'source':{k:ref[k] for k in ['id','wordIndex','word','nearSeconds']},
                        'before':''.join(w['word'] for w in audible[max(0,pos-9):pos]),'after':''.join(w['word'] for w in audible[pos:pos+9])})
    # Whole-row reorders create real encoded joins too, even with no word mask.
    # Sentence labels inside an uninterrupted source run create no sound cut.
    clips=project.get('clips',[]);cursor=float(project.get('coverDuration',0))
    for left,right in zip(clips,clips[1:]):
        rate=left.get('speed',project.get('settings',{}).get('speed',1))
        cursor+=left.get('outputDuration',(left['end']-left['start'])/rate)
        if left['id']==right['id'] or abs(left['end']-right['start'])<1e-7 or any(abs(t['nearSeconds']-cursor)<.1 for t in out):continue
        if any(r.get('action')=='beep' and cursor+.3>r['start'] and cursor-.3<r['end'] for r in redactions):continue
        before=[w for w in audible if w['nearSeconds']<cursor and w['clipEnd']<=cursor+1e-5][-3:]
        after=[w for w in audible if w['clipStart']>=cursor-1e-5][:3]
        if not before or not after:continue
        ref=after[0]
        out.append({'id':right['id'],'indices':[],'quote':'','kind':'join','neighbors':copy.deepcopy(before+after),'nearSeconds':round(cursor,6),
                    'source':{k:ref[k] for k in ('id','wordIndex','word','nearSeconds')},'before':''.join(w['word'] for w in before),'after':''.join(w['word'] for w in after)})
    return sorted(out,key=lambda t:t['nearSeconds'])


def probe(target,audio,recognizer,retained):
    """Require agreement at the join, not the same filler elsewhere in a crop."""
    import encoded_boundary_cues
    point=target['nearSeconds'];windows=[]
    for pad in [0,.4]:
        lo=max(0,point-2.5-pad);hi=min(len(audio)/16000,point+3+pad)
        trace=recognizer.trace(audio[round(lo*16000):round(hi*16000)],lo)
        hits=[]
        for token in trace:
            ch=token.get('text');time=token.get('time');probability=token.get('probability',0)
            if not isinstance(ch,str) or len(ch)!=1 or not FILLER.fullmatch(ch) or ch not in target['quote'] or type(time) not in (int,float) or not math.isfinite(time) or abs(time-point)>.4 or probability<.35:continue
            if any(ch in plain(w['word']) and w['nearSeconds']-.25<=time<=w['endSeconds']+.25 for w in retained):continue
            hits.append({'text':ch,'time':round(time,6),'probability':round(probability,6)})
        windows.append({'window':[round(lo,6),round(hi,6)],'hits':hits,'recognized':''.join(t['text'] for t in trace),
                        'boundary':encoded_boundary_cues.analyze(target,trace,retained,lo,hi)})
    issues=[]
    if windows[0]['window']!=windows[1]['window']:
        for a in windows[0]['hits']:
            b=next((b for b in windows[1]['hits'] if b['text']==a['text'] and abs(b['time']-a['time'])<=.12),None)
            if b:issues.append({'kind':'insert','expected':'','recognized':a['text'],'before':target['before'],'after':target['after'],
                                'source':copy.deepcopy(target['source']),'seekSeconds':round(max(0,point-.8),3),
                                'status':'局部两次识别疑似已删语气词残音，待回听，未改声音或字幕',
                                'evidenceKind':'encoded-local-seam','localEvidence':{'version':VERSION,'target':copy.deepcopy(target),'windows':windows}});break
    for cue in encoded_boundary_cues.agree(target,windows):
        issues.append({**cue,'before':target['before'],'after':target['after'],'seekSeconds':round(max(0,point-.8),3),
                       'status':'两次局部识别提示切口附近可能有残音或邻字差异，待回听，未改声音或字幕',
                       'evidenceKind':'encoded-local-boundary','localEvidence':{'version':VERSION,'target':copy.deepcopy(target),'windows':windows}})
    return {'target':target,'windows':windows,'differences':issues,'distinctWindows':windows[0]['window']!=windows[1]['window'],
            'neighborCoverage':all(w['boundary']['covered'] for w in windows)}


def run(key,owner,result,project,api):
    import uuid
    wanted=targets(project,result.get('redactions',[]))
    if not wanted:return {'version':VERSION,'status':'not-needed','targetCount':0,'checked':0,'differences':[]}
    python=api.ROOT.parent/'research/tools/sensevoice-python/Scripts/python.exe';model=Path.home()/'.cache/sayframe-asr/sensevoice-2024'
    if not python.is_file() or not (model/'model.int8.onnx').is_file():return {'version':VERSION,'status':'unavailable','targetCount':len(wanted),'checked':0,'differences':[]}
    request=api.ROOT/'recognition-cache'/('final-seams-request-'+uuid.uuid4().hex+'.json')
    api.save(request,{'owner':owner,'videoName':Path(result['video']).name,'ffmpeg':str(api.FFMPEG),'model':str(model),'redactions':result.get('redactions',[])})
    try:
        api.TASKS.progress(key,'正在检查删词和调序接缝的实际成片声音')
        return json.loads(api.TASKS.process([str(python),'-X','utf8',str(api.ROOT/'final_seams_worker.py'),str(request)],cwd=api.ROOT,timeout=150))
    finally:request.unlink(missing_ok=True)


def merge(value,local):
    out=copy.deepcopy(value);out['localSeams']=local
    for issue in local.get('differences',[]):
        existing=next((d for d in out['differences'] if d['recognized']==issue['recognized'] and d['expected']==issue['expected'] and abs(d['seekSeconds']-issue['seekSeconds'])<=.8),None)
        if existing is not None:existing['localEvidence']=issue['localEvidence'];existing['evidenceKind']='full-and-local-seam'
        else:out['differences'].append(issue)
    out['differenceCount']=len(out['differences'])
    if out['differences']:out['status']='review'
    elif local['status'] not in ('checked','not-needed'):
        out.update(status='unavailable',differenceCount=None,message='全文转写已完成，局部删词声音还需复核；成片已保留，可稍后重试')
    return out
