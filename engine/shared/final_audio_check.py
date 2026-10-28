"""Blind recognition of the actual encoded movie; differences never edit it.

An ASR disagreement is a review cue, not proof of a missing phoneme or authority
to cut, rewrite, restore speech, or weaken the source-bound acoustic gates.
"""
import copy,difflib,hashlib,json,math,re
from pathlib import Path
import cloud_asr
import expected_audio_words
VERSION=2
REUSE_VERSION=1
NOTE='声音转写差异只是回听线索，可能是识别多写或字形差异；不据此改字、删音或认定已截字。文字一致也不代表语气词已去净或完成全部听感检查。'

def plain(text):return ''.join(c.upper() for c in text if c.isalnum())

def expected_words(project,redactions=()):
    chars=[];refs=[];cursor=float(project.get('coverDuration',0))
    tables,_=expected_audio_words.resolve(project)
    for clip,words in zip(project['clips'],tables):
        rate=clip.get('speed',project.get('settings',{}).get('speed',1))
        if type(rate) not in (float,int) or not math.isfinite(rate) or rate<=0:raise ValueError('成片声音时间记录无效')
        duration=clip.get('outputDuration',(clip['end']-clip['start'])/rate)
        if not all(type(v) in (float,int) and math.isfinite(v) for v in (duration,cursor)) or duration<=0:raise ValueError('成片声音时间记录无效')
        for word in words:
            text=plain(word['word'])
            a=cursor+max(0,min(duration,(word['start']-clip['start'])/rate))
            b=cursor+max(0,min(duration,(word['end']-clip['start'])/rate))
            if any(r.get('action')=='beep' and a<r['end'] and b>r['start'] for r in redactions):continue
            for ch in text:
                chars.append(ch);refs.append({'id':clip['id'],'wordIndex':word.get('index'),'word':word['word'],'nearSeconds':round(a,3)})
        cursor+=duration
    return ''.join(chars),refs

def compare(project,recognized,redactions=()):
    expected,refs=expected_words(project,redactions);heard=plain(recognized);issues=[]
    for op,a,b,c,d in difflib.SequenceMatcher(None,expected,heard,autojunk=False).get_opcodes():
        if op=='equal':continue
        ref=refs[min(a,len(refs)-1)] if refs else {'nearSeconds':0}
        issues.append({'kind':op,'expected':expected[a:b],'recognized':heard[c:d],
                       'before':expected[max(0,a-12):a],'after':expected[b:b+12],
                       'source':copy.deepcopy(ref),'seekSeconds':round(max(0,ref['nearSeconds']-.8),3),
                       'status':'待回听，未改声音或字幕'})
    return {'status':'review' if issues else 'matched','differences':issues,'differenceCount':len(issues),
            'expected':expected,'recognized':recognized,'note':NOTE,'changedSpeech':False,
            'intentionalRedactions':len(redactions),'expectedWordCoverage':expected_audio_words.resolve(project)[1]}

def paths(owner,result,api):
    video=result.get('video');project=result.get('project')
    if not re.fullmatch('[a-f0-9]{32}',owner) or video not in (f'/outputs/{owner}/final.mp4',f'/outputs/{owner}/edited.mp4') or project!=f'/outputs/{owner}/project.json':raise ValueError('声音检查只接受本任务的实际成片')
    folder=(api.ROOT/'outputs'/owner).resolve();media=(api.ROOT/video.lstrip('/')).resolve();draft=(api.ROOT/project.lstrip('/')).resolve()
    if media.parent!=folder or draft.parent!=folder or not media.is_file() or not draft.is_file():raise ValueError('成片或工程文件暂不可用')
    return media,draft

def inputs(owner,result,api):
    media,draft=paths(owner,result,api);project=json.loads(draft.read_text('utf8'))
    with media.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    expected,refs=expected_words(project,result.get('redactions',[]))
    import final_seams
    binding=hashlib.sha256(json.dumps({'version':VERSION,'model':cloud_asr.MODEL,'mediaSha256':digest,
        'expected':expected,'refs':refs,'expectedWordCoverageVersion':expected_audio_words.VERSION,'redactions':result.get('redactions',[]),'localSeamsVersion':final_seams.VERSION,'encodedBoundaryCuesVersion':__import__('encoded_boundary_cues').VERSION,'localSeamsModel':final_seams.MODEL,'localTargets':final_seams.targets(project,result.get('redactions',[]))},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return media,project,digest,binding

def reuse_core(value,owner,binding,digest):
    """Reuse exact encoded evidence, without borrowing another movie's owner.

    Bindings include the encoded bytes, expected words, time refs and seam
    targets. Source excerpt context belongs to the CURRENT project and must
    be rebuilt/read separately. Never rewrite an old job/cache receipt.
    """
    if (not isinstance(value,dict) or value.get('version')!=VERSION or value.get('binding')!=binding
        or value.get('mediaSha256')!=digest or value.get('actualEncodedMovie') is not True
        or value.get('status') not in ('matched','review','unavailable')):return None
    old=value.get('ownerJobId')
    if not isinstance(old,str) or not re.fullmatch('[a-f0-9]{32}',old):return None
    out=copy.deepcopy(value);out.pop('automaticAudioContext',None)
    for issue in out.get('differences',[]):issue.pop('audioContext',None)
    out.update(ownerJobId=owner,reused=True,reuseBindingVersion=REUSE_VERSION)
    if old!=owner:out['reusedFromOwner']=value.get('reusedFromOwner',old)
    return out


def cached(owner,result,api):
    try:_,_,sha,binding=inputs(owner,result,api)
    except expected_audio_words.CoverageError:return None
    path=api.ROOT/'recognition-cache'/('final-audio-check-v1-'+binding+'.json')
    if path.is_file():
        v=reuse_core(json.loads(path.read_text('utf8')),owner,binding,sha)
        if v is not None:
            import automatic_audio_context
            return automatic_audio_context.attach(v,automatic_audio_context.cached(owner,result,v,api))
    return None

def audit(key,owner,result,api):
    from tasks import Cancelled
    try:media,project,digest,binding=inputs(owner,result,api)
    except expected_audio_words.CoverageError as error:
        # No complete expected transcript means no comparison or clean result.
        # Do not call ASR, alter the movie or cache an unbound pseudo-audit.
        paths(owner,result,api)
        return {'version':VERSION,'ownerJobId':owner,'actualEncodedMovie':True,'status':'unavailable',
                'differences':[],'differenceCount':None,'changedSpeech':False,'note':NOTE,
                'expectedWordCoverage':{'version':expected_audio_words.VERSION,'status':'unavailable','reason':str(error)},
                'message':'声音检查的原字记录不完整，成片已保留，尚不能完成核对'}
    path=api.ROOT/'recognition-cache'/('final-audio-check-v1-'+binding+'.json')
    if path.is_file():
        old=reuse_core(json.loads(path.read_text('utf8')),owner,binding,digest)
        if old is not None and old.get('status') in ('matched','review'):
            receipt=api.ROOT/'outputs'/owner/f'final-audio-reuse-v1-{binding}.json'
            if not receipt.exists():api.save(receipt,old)
            import automatic_audio_context
            return automatic_audio_context.run(key,owner,result,old,api)
    api.TASKS.check(key);api.TASKS.progress(key,'正在复核最终成片的声音与原话')
    base={'version':VERSION,'binding':binding,'ownerJobId':owner,'mediaSha256':digest,'model':cloud_asr.MODEL,
          'actualEncodedMovie':True,'note':NOTE,'changedSpeech':False,'reused':False}
    try:
        answer=__import__('cloud_transcript').recognize_file(key,media,result['duration'],api,digest=digest,purpose='final-audio-check')
        if answer.get('model')!=cloud_asr.MODEL or not isinstance(answer.get('text'),str) or not answer['text'].strip():raise ValueError('成片声音识别未完成')
        if inputs(owner,result,api)[3]!=binding:raise ValueError('复核期间成片或工程已变化')
        value={**base,**compare(project,answer['text'],result.get('redactions',[]))}
        import final_seams
        try:local=final_seams.run(key,owner,result,project,api)
        except Cancelled:raise
        except Exception:local={'version':final_seams.VERSION,'status':'unavailable','targetCount':len(final_seams.targets(project,result.get('redactions',[]))),'checked':0,'differences':[]}
        value=final_seams.merge(value,local)
        if inputs(owner,result,api)[3]!=binding:raise ValueError('复核期间成片或工程已变化')
        usage=answer.get('usage',[])
        from analysis_usage import safe_usage
        for item in usage if isinstance(usage,list) else [usage]:
            api.TASKS.analysis_attempt(key,{'phase':'final-audio-check','status':'returned','usage':safe_usage(item),'requestedModel':cloud_asr.MODEL})
    except Cancelled:raise
    except Exception:
        # Never expose provider bodies, credentials or falsely report zero issues.
        value={**base,'status':'unavailable','differences':[],'differenceCount':None,'message':'成片已保留，声音复核暂未完成，可稍后重试'}
    api.TASKS.check(key);api.save(path,value)
    receipt=api.ROOT/'outputs'/owner/f'final-audio-check-v1-{binding}.json'
    if not receipt.exists():api.save(receipt,value)
    import automatic_audio_context
    return automatic_audio_context.run(key,owner,result,value,api)

def completed(video,api):
    match=re.fullmatch(r'/outputs/([a-f0-9]{32})/(?:final|edited)\.mp4',video) if isinstance(video,str) else None
    if not match:raise ValueError('请先打开已生成的成片')
    job=api.TASKS.get(match[1]);result=job.get('result') or {}
    if job.get('status')!='done' or result.get('video')!=video:raise ValueError('成片任务尚未完成或引用不匹配')
    paths(match[1],result,api)
    return match[1],result

def run(key,video,api):
    owner,result=completed(video,api)
    return {'video':video,'outputAudioAudit':audit(key,owner,result,api)}

def submit(video,api,token=None):
    owner,result=completed(video,api)
    with api.TASKS.lock:
        active=next((j for j in api.JOBS.values() if j.get('kind')=='final-audio-check' and j.get('status') in ('queued','running','cancelling') and j.get('request',{}).get('video')==video),None)
        if active:return active['id']
        return api.TASKS.submit('final-audio-check','成片声音复核',{'video':video},lambda key:run(key,video,api),request_token=token)
