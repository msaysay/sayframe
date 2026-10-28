"""Reuse only a verified, matching movie's unaffected source ranges/notices.

This module is called after confirmed local planning, never from a client flag.
Ranges are still audited by the ordinary worker without manual-edge exemptions.
"""
import copy,hashlib,json
from pathlib import Path
import preserved_speech_context as pc,final_audio_check,frozen_clip_bounds as fb
VERSION=2


def logical(project):
    value=copy.deepcopy(project)
    for row in value.get('segments',[]):
        for name in ('caption','wordCorrections','sourceUnit'):row.pop(name,None)
    return pc.binding(value)


def row_signature(row):
    value={k:v for k,v in row.items() if k not in pc.IGNORE|{'caption','wordCorrections','sourceUnit'}}
    return hashlib.sha256(json.dumps(pc.numeric_form(value),sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def media_path(record):
    path=Path(record.get('video_path') or '')
    if not path.is_file():raise ValueError('沿用取音缺少原视频')
    return path.resolve()


def capture(key,record,project,scope,api):
    wanted=logical(project);target=set(scope['allowed'])
    if not wanted:raise ValueError('局部剪辑缺少可绑定的原稿')
    with api.TASKS.lock:history=list(api.JOBS.values())
    current_time=api.JOBS.get(key,{}).get('createdAt')
    history.sort(key=lambda j:j.get('createdAt',0),reverse=True)
    for old in history:
        result=old.get('result') or {};owner=old.get('id')
        if old.get('status')!='done' or old.get('kind') not in ('render','editor-auto','automatic-edit') or owner==key:continue
        if current_time is not None and old.get('createdAt',0)>=current_time:continue
        sid=result.get('sourceId',(old.get('request') or {}).get('sourceId'))
        if sid!=project['sourceId']:continue
        try:
            _,path=final_audio_check.paths(owner,result,api);prior=json.loads(path.read_text('utf8'))
            if logical(prior)!=wanted:continue
            prior,_sha=__import__('caption_speech_context').actual(owner,result,api)
            if media_path(api.get_case(prior['sourceId']))!=media_path(record):continue
        except (ValueError,OSError,KeyError,TypeError):continue
        # The newest exact actual movie is authoritative, even if it has no
        # assessment. Do not resurrect unrelated old holds to invent a count.
        enriched=__import__('preserved_speech_context').enrich(owner,result,api)
        context=enriched.get('preservedSpeechContext') or enriched.get('speechRefinement',{})
        cuts,rejected=pc.notices(context,project['segments'],owner)
        # A local target may contain several held sounds. Remove a notice only
        # when ALL its original indices are in the confirmed deletion, never
        # merely because another word in the same sentence is being edited.
        rows={r['id']:r for r in project['segments']}
        cuts=[c for c in cuts if not set(c['indices']) <=
              (set(rows[c['id']]['removed']) | set(scope['allowed'].get(c['id'],[])))]
        rejected=[c for c in rejected if c.get('id') in rows]
        frozen=[{k:c[k] for k in ('id','firstIndex','lastIndex','start','end')} for c in prior['clips'] if c['id'] not in target]
        # Validate keys/bounds before they reach any calibration request.
        fb.mapping(prior['clips'],frozen)
        video=media_path(record);stat=video.stat()
        lock={'version':VERSION,'ownerJobId':owner,'movieSha256':_sha,'projectSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'baselineResult':{k:result[k] for k in ('video','project')},
              'sourcePath':str(video),'sourceStat':[stat.st_size,stat.st_mtime_ns],'sourceId':project['sourceId'],
              'targets':sorted(target),'allowedRemovals':copy.deepcopy(scope['allowed']),'frozenClips':frozen,'rows':{r['id']:row_signature(r) for r in project['segments'] if r['id'] not in target},
              'targetWords':{r['id']:[w['word'] for w in r['words']] for r in project['segments'] if r['id'] in target},
              'targetBaseRemoved':{r['id']:copy.deepcopy(r['removed']) for r in project['segments'] if r['id'] in target},
              'pacing':copy.deepcopy(project['settings'].get('pacing',{})),'speed':project['settings'].get('speed',1),
              'notices':{'fromJobId':owner,'cuts':cuts,'rejected':rejected,'changedSpeech':False,'cleanupVerified':False}}
        folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True);api.save(folder/'local-clip-lock.json',lock)
        return lock
    raise ValueError('局部剪辑尚未找到与当前原稿取音完全匹配的已核验成片，原稿保留；请先保存并核对当前成片')


def bounds(key,record,payload,lock,api):
    path=api.ROOT/'outputs'/key/'local-clip-lock.json'
    if lock.get('version')!=VERSION or not path.is_file() or json.loads(path.read_text('utf8'))!=lock:raise ValueError('局部取音绑定已变化，未采用')
    old_media,old_project=final_audio_check.paths(lock['ownerJobId'],lock['baselineResult'],api)
    with old_media.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    if sha!=lock['movieSha256'] or hashlib.sha256(old_project.read_bytes()).hexdigest()!=lock['projectSha256']:raise ValueError('旧成片或取音工程已变化，未沿用边界')
    video=media_path(record);stat=video.stat()
    if str(video)!=lock['sourcePath'] or [stat.st_size,stat.st_mtime_ns]!=lock['sourceStat']:raise ValueError('原视频已变化，未沿用旧取音')
    settings=payload['settings']
    if settings.get('pacing',{})!=lock['pacing'] or settings.get('speed',1)!=lock['speed']:raise ValueError('局部气口或倍速已变化，未沿用旧取音')
    rows={r['id']:r for r in payload['segments']}
    for sid,digest in lock['rows'].items():
        if sid not in rows or row_signature(rows[sid])!=digest:raise ValueError('非目标原字或声音记录已变化，未沿用旧取音')
    for sid,words in lock['targetWords'].items():
        if (sid not in rows or [w['word'] for w in rows[sid]['words']]!=words
            or set(rows[sid]['removed'])!=set(lock['targetBaseRemoved'][sid])|set(lock['allowedRemovals'][sid])):
            raise ValueError('目标删字超出已确认范围，未沿用取音')
    # Old padding may contain the newly deleted TARGET phoneme. Only these
    # server-owned, verified exclusions can retract a preserved handle.
    source=api.public_case(record,True)
    excluded=__import__('cut_exclusions').collect(source['segments'],payload['segments'])
    excluded=[w for w in excluded if w['index'] in lock['allowedRemovals'].get(w['id'],[])]
    frozen,retractions=fb.retract(lock['frozenClips'],excluded)
    proof={'version':fb.VERSION,'baselineOwner':lock['ownerJobId'],'frozenClips':frozen,'paddingRetractions':retractions}
    effective=path.parent/'local-effective-clip-lock.json'
    if effective.is_file() and json.loads(effective.read_text('utf8'))!=proof:raise ValueError('目标删除声音或沿用范围已变化，未使用旧取音')
    api.save(effective,proof)
    return proof


def verify_result(key,result,lock,api):
    _,path=final_audio_check.paths(key,result,api);project=json.loads(path.read_text('utf8'))
    effective=bounds(key,api.get_case(project['sourceId']),project,lock,api)
    proof=fb.verify(project['clips'],effective['frozenClips'])
    proof.update(ownerJobId=lock['ownerJobId'],version=VERSION,sourceRangesPreserved=not effective['paddingRetractions'],
                 verifiedTargetPaddingRetractions=effective['paddingRetractions'],encoderRoundingIsNotSourceRange=True)
    api.save(path.parent/'local-physical-scope.json',proof)
    return proof
