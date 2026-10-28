"""Carry unresolved notices across an exactly unchanged audio edit.

Not an editing authority: inherited suggestions are always nonautomatic.
Read-time legacy enrichment never rewrites a job, project, or media file.
"""
import copy,hashlib,json,math,re
from contextlib import nullcontext
import final_audio_check,repeated_takes

VERSION=1
IGNORE={'label','contentValue','emphasis','discardReason','text'}
AUDIO=('pacing','speed','voiceGain','noiseReduction','voiceDenoise','musicId','musicVolume','musicDucking','peakProtection','contentSafety')
NOTE='沿用完全相同的原词、删字、声音切口和声音设置；旧待回听提示仍有效，不代表本轮重新精剪或已去净。'


def numeric_form(value):
    # Browser JSON writes 501.0 as 501. This is lossless normalization only;
    # nearby floating values, boolean flags and large unequal integers differ.
    if type(value) is float and math.isfinite(value) and value.is_integer():return int(value)
    if isinstance(value,dict):return {k:numeric_form(v) for k,v in value.items()}
    if isinstance(value,list):return [numeric_form(v) for v in value]
    return value


def binding(project):
    rows=project.get('segments');sid=project.get('sourceId')
    if not isinstance(sid,str) or not sid or not isinstance(rows,list) or not rows:return None
    if any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in rows):return None
    if len({r['id'] for r in rows})!=len(rows):return None
    settings=project.get('settings',{})
    value={'sourceId':sid,'segments':[{k:v for k,v in r.items() if k not in IGNORE} for r in rows],
           'audio':{k:settings.get(k,1 if k=='speed' else {} if k=='pacing' else None) for k in AUDIO}}
    try:return hashlib.sha256(json.dumps(numeric_form(value),ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    except (ValueError,TypeError):return None


def actual(owner,result,api):
    media,draft=final_audio_check.paths(owner,result,api)
    audit=result.get('outputAudioAudit',{})
    digest=audit.get('mediaSha256')
    if audit.get('actualEncodedMovie') is not True or audit.get('status') not in ('matched','review') or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
        raise ValueError('旧提示缺少实际成片音轨的绑定证据')
    with media.open('rb') as handle:
        if hashlib.file_digest(handle,'sha256').hexdigest()!=digest:raise ValueError('旧提示对应的成片文件已改变')
    project=json.loads(draft.read_text('utf8'))
    if project.get('sourceId')!=result.get('sourceId'):raise ValueError('旧提示来源与实际工程不一致')
    return project,digest


def notices(speech,rows,owner):
    cuts=[];seen=set();invalid=[]
    for cut in speech.get('cuts',[]):
        if not isinstance(cut,dict) or cut.get('automatic') is not False or cut.get('dismissed'):continue
        try:valid=repeated_takes.validate([cut],rows)[0]
        except (ValueError,TypeError,KeyError):
            invalid.append({'id':cut.get('id'),'reason':'旧待回听记录无法按当前原词绑定，保留原声并请重新核对'})
            continue
        if valid['key'] in seen:continue
        seen.add(valid['key'])
        valid.pop('dismissed',None)
        valid.update(automatic=False,holdReason=cut.get('holdReason') or '原声音尚未确认可安全删减，本次继续保留供回听',
                     inheritedFrom=owner)
        cuts.append(valid)
    rejected=[{k:c[k] for k in ('id','reason') if k in c} for c in speech.get('rejected',[])
              if isinstance(c,dict) and isinstance(c.get('reason'),str) and c['reason'].strip()]
    return cuts,[*rejected,*invalid]


def inherit(owner,project,api):
    digest=binding(project)
    base={'version':VERSION,'binding':digest,'status':'no-matching-history','cuts':[],'rejected':[],
          'changedSpeech':False,'cleanupVerified':False,'note':'本轮保留原声音，尚未找到完全匹配的旧复核记录；不代表已去净。'}
    jobs=getattr(api,'JOBS',None)
    if digest is None or not isinstance(jobs,dict) or owner not in jobs:return base
    with getattr(getattr(api,'TASKS',None),'lock',nullcontext()):items=list(jobs.values())
    at=jobs[owner].get('createdAt')
    if type(at) not in (float,int) or not math.isfinite(at):return base
    items.sort(key=lambda j:j['createdAt'] if type(j.get('createdAt')) in (int,float) and math.isfinite(j['createdAt']) else float('-inf'),reverse=True)
    for job in items:
        result=job.get('result') or {};speech=result.get('speechRefinement') or {}
        if job.get('id')==owner or job.get('status')!='done' or result.get('kind')!='editor-auto' or result.get('sourceId')!=project['sourceId']:continue
        when=job.get('createdAt')
        if type(when) not in (float,int) or not math.isfinite(when) or when>=at:continue
        # A preservation-only run cannot clear earlier unresolved notices.
        if speech.get('preservedByCreator') or speech.get('review',{}).get('passed') is not True or not isinstance(speech.get('cuts'),list):continue
        try:
            old,media_sha=actual(job['id'],result,api)
            if binding(old)!=digest:continue
        except (ValueError,OSError,KeyError,TypeError):continue
        cuts,rejected=notices(speech,project['segments'],job['id'])
        # Stop at the newest matching actual assessment, even if it cleared
        # every notice. Do not pull obsolete holds from an older assessment.
        return {**base,'status':'matched','note':NOTE,'fromJobId':job['id'],'sourceMediaSha256':media_sha,
                'cuts':cuts,'rejected':rejected}
    return base


def enrich(owner,result,api):
    speech=result.get('speechRefinement') or {}
    if not speech.get('preservedByCreator'):
        return __import__('caption_speech_context').enrich(owner,result,api)
    if 'inheritance' in speech:return result
    try:project,_=actual(owner,result,api)
    except (ValueError,OSError,KeyError,TypeError):return result
    receipt=inherit(owner,project,api)
    value=copy.deepcopy(result);speech=value['speechRefinement']
    speech['inheritance']=receipt
    if receipt['status']!='matched':return value
    existing=speech.get('cuts',[])
    cuts=list({c['key']:c for c in [*existing,*receipt['cuts']]}.values())
    speech.update(cuts=cuts,rejected=[*speech.get('rejected',[]),*receipt['rejected']])
    value.setdefault('plan',{})['speechCuts']=copy.deepcopy(cuts)
    from speech_refine import pending_count
    count=pending_count(project['segments'],[*value['plan'].get('repetitions',[]),*cuts],speech['rejected'])
    count+=len(value.get('clipCalibration',{}).get('extraRestarts',[]))
    operations=value.setdefault('operations',{})
    reported=operations.get('pendingRepetitions',0)
    operations['pendingRepetitions']=max(reported if type(reported) is int and reported>=0 else 0,count)
    return value


def public_job(job,api):
    if job.get('status')!='done' or not isinstance(job.get('result'),dict):return job
    result=enrich(job['id'],job['result'],api)
    return job if result is job['result'] else {**job,'result':result}
