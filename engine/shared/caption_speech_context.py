"""Read-only unresolved notices for manual renders with the same speech edit.

Display spelling/caption changes never certify that old speech holds were fixed.
No edit permissions and no clean-audio claim; actual current and old media are
still bound separately, and original words/masks/physical ranges must match.
"""
import copy,hashlib,json,math
import final_audio_check,preserved_speech_context as pc
VERSION=1


def speech_binding(project):
    value=copy.deepcopy(project)
    for row in value.get('segments',[]):
        row.pop('caption',None);row.pop('wordCorrections',None)
        # Browser restore decorates legacy rows with their original ASR unit.
        # This is grouping metadata, never a word/time or audio authority.
        # Physical clips and all raw words, masks and settings remain exact.
        row.pop('sourceUnit',None)
    base=pc.binding(value);clips=project.get('clips')
    if base is None or not isinstance(clips,list) or not clips:return None
    physical=[{k:c.get(k) for k in ('id','firstIndex','lastIndex','start','end','speed','outputDuration')} for c in clips]
    try:return hashlib.sha256(json.dumps(pc.numeric_form({'base':base,'clips':physical,'coverDuration':project.get('coverDuration',0)}),sort_keys=True,allow_nan=False).encode()).hexdigest()
    except (ValueError,TypeError):return None


def actual(owner,result,api):
    _,path=final_audio_check.paths(owner,result,api)
    project=json.loads(path.read_text('utf8'));sid=project.get('sourceId')
    if result.get('sourceId',sid)!=sid:raise ValueError('声音提示来源不匹配')
    return pc.actual(owner,{**result,'sourceId':sid},api)


def enrich(owner,result,api):
    jobs=getattr(api,'JOBS',{});current=jobs.get(owner,{})
    if current.get('kind')!='render' or current.get('status')!='done' or 'preservedSpeechContext' in result:return result
    try:project,_=actual(owner,result,api)
    except (ValueError,OSError,TypeError,KeyError):return result
    binding=speech_binding(project);when=current.get('createdAt')
    if binding is None or type(when)not in(int,float) or not math.isfinite(when):return result
    context={'version':VERSION,'binding':binding,'status':'no-matching-history','cuts':[],'rejected':[],
             'changedSpeech':False,'cleanupVerified':False,'note':'本轮未找到相同原音编辑的旧复核记录，不代表语气和重说已去净。'}
    with api.TASKS.lock:history=list(jobs.values())
    history.sort(key=lambda j:j['createdAt']if type(j.get('createdAt'))in(int,float)and math.isfinite(j['createdAt'])else float('-inf'),reverse=True)
    for old in history:
        prior=old.get('result')or{};speech=prior.get('speechRefinement')or{};at=old.get('createdAt')
        if old.get('id')==owner or old.get('status')!='done' or prior.get('kind')!='editor-auto' or prior.get('sourceId')!=project['sourceId'] or type(at)not in(int,float) or not math.isfinite(at) or at>=when:continue
        if speech.get('preservedByCreator') or speech.get('review',{}).get('passed')is not True or not isinstance(speech.get('cuts'),list):continue
        try:
            other,sha=actual(old['id'],prior,api)
            if speech_binding(other)!=binding:continue
        except (ValueError,OSError,KeyError,TypeError):continue
        cuts,rejected=pc.notices(speech,project['segments'],old['id'])
        context.update(status='matched',fromJobId=old['id'],sourceMediaSha256=sha,cuts=cuts,rejected=rejected,
                       note='相同原词、删字、取音范围和声音设置的待回听记录继续保留；校正字幕不表示这些声音已经处理好。')
        break
    value=copy.deepcopy(result);value['sourceId']=project['sourceId'];value['preservedSpeechContext']=context
    if context['status']=='matched':
        count=__import__('speech_refine').pending_count(project['segments'],context['cuts'],context['rejected'])
        operations=value.setdefault('operations',{});reported=operations.get('pendingRepetitions',0)
        operations['pendingRepetitions']=max(reported if type(reported)is int and reported>=0 else 0,count)
    return value
