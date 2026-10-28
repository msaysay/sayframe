"""Automatic bound excerpts/local waveform support after encoded sound audit.

Runs for new renders and the ordinary recheck action. No extra cloud requests,
editing authority or changed ASR verdicts. Optional failures retain the review
cue; a cancellation does not publish a false completed stage.
"""
import copy,hashlib,json
import audio_comparison,waveform_evidence
from tasks import Cancelled
VERSION=2
LIMIT=20


def identity(audit):
    issues=[{k:v for k,v in issue.items() if k!='audioContext'} for issue in audit.get('differences',[])]
    return hashlib.sha256(json.dumps(issues,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def path_for(owner,audit,api):
    return api.ROOT/'outputs'/owner/f'automatic-audio-context-v{VERSION}-{audit["binding"]}-{identity(audit)}.json'


def cached(owner,movie,audit,api):
    path=path_for(owner,audit,api)
    if not path.is_file():return None
    try:
        old=json.loads(path.read_text('utf8'));total=len(audit.get('differences',[]))
        if (old.get('version')!=VERSION or old.get('waveformVersion')!=waveform_evidence.VERSION
            or old.get('auditBinding')!=audit['binding'] or old.get('issuesSha256')!=identity(audit)
            or old.get('status') not in ('prepared','partial','not-needed') or old.get('targetCount')!=total
            or [e.get('cueIndex') for e in old.get('entries',[])]!=list(range(min(total,LIMIT)))
            or old.get('preparedCount')!=sum(e.get('status')=='prepared' for e in old.get('entries',[]))):return None
        for entry in old['entries']:
            if entry.get('status')=='unavailable':continue
            if entry.get('status')!='prepared':return None
            bound=audio_comparison.prepare_audit(owner,movie,audit,entry['cueIndex'],api)
            pair=audio_comparison.cached_pair(bound,api)
            if pair is None or {k:v for k,v in entry.get('pair',{}).items() if k!='reused'}!={k:v for k,v in pair.items() if k!='reused'}:return None
        return {**old,'reused':True}
    except (ValueError,OSError,KeyError,TypeError):return None


def attach(audit,context):
    value=copy.deepcopy(audit)
    if context is None:return value
    value['automaticAudioContext']={k:v for k,v in context.items() if k!='entries'}
    for entry in context.get('entries',[]):
        value['differences'][entry['cueIndex']]['audioContext']={k:v for k,v in entry.items() if k!='cueIndex'}
    return value


def run(key,owner,movie,audit,api):
    if audit.get('status') not in ('matched','review'):return audit
    old=cached(owner,movie,audit,api)
    if old is not None and old['status']!='partial':return attach(audit,old)
    import final_audio_check
    _,draft=final_audio_check.paths(owner,movie,api);project=json.loads(draft.read_text('utf8'))
    issues=audit.get('differences',[]);entries=[]
    for index,issue in enumerate(issues[:LIMIT]):
        api.TASKS.check(key);api.TASKS.progress(key,f'正在对照原音与成片 {index+1}/{len(issues)}')
        try:
            pair=audio_comparison.from_audit(key,owner,movie,audit,index,api)
            waveform=waveform_evidence.run(pair,project,api.ROOT)
            if audio_comparison.prepare_audit(owner,movie,audit,index,api)['binding']!=pair['binding']:raise ValueError('原音或工程已变化')
            entries.append({'cueIndex':index,'status':'prepared','pair':pair,'waveformEvidence':waveform})
        except Cancelled:raise
        except Exception:
            entries.append({'cueIndex':index,'status':'unavailable','message':'这处原音对照暂未完成，声音和文稿保持不变，可重新检查'})
    api.TASKS.check(key)
    # A changed encoded movie/project invalidates the whole stage; never
    # publish a measured result with a different source or media binding.
    if final_audio_check.inputs(owner,movie,api)[3]!=audit['binding']:raise ValueError('对照期间成片或工程已变化')
    count=sum(e['status']=='prepared' for e in entries)
    value={'version':VERSION,'waveformVersion':waveform_evidence.VERSION,'auditBinding':audit['binding'],
           'issuesSha256':identity(audit),'targetCount':len(issues),'preparedCount':count,'limit':LIMIT,
           'status':'not-needed' if not issues else 'prepared' if count==len(issues) else 'partial',
           'entries':entries,'changedSpeech':False,'extraCloudRequests':0,'reused':False}
    api.save(path_for(owner,audit,api),value)
    return attach(audit,value)
