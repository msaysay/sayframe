"""One quiet-seam regroup after one semantic recovery, never a retry loop.

Only tool-owned acoustic evidence nominates currently editable source neighbors.
No timestamps, guessed silence, creator-deleted words, or cut waivers are used.
"""
import copy,shutil

VERSION=1


def after_semantic(key,record,payload,api,error,semantic_error,prior_holds,execute,prepare,music_allowed):
    import clip_calibration,audio_recovery_context as arc,editor_planning as ep,semantic_recovery as sr,automatic_edit
    if not isinstance(error,clip_calibration.CalibrationRejected):raise error
    blocking=error.blocking
    if not blocking or any(not isinstance(b,dict) or b.get('side') not in ('start','end') or not b.get('id') or '无可靠安静区间' not in b.get('reason','') for b in blocking):raise error
    approved=getattr(error,'approved_audio_context',None)
    if not isinstance(approved,dict) or approved.get('kind')!='editor-planning' or approved.get('sourceId')!=payload.get('sourceId') or approved.get('id')!=payload.get('planningId'):raise error
    checked=ep.confirmed(record,payload,api)
    if checked.get('id')!=approved['id'] or checked.get('sourceId')!=approved['sourceId'] or checked['plan']!=approved['plan']:raise error
    source,project,rows,_=prepare(record,payload,api)
    if source['id']!=approved['sourceId']:raise error
    old=sr.withheld_plan(project,approved['plan'],prior_holds) if prior_holds and prior_holds.get('holds') else copy.deepcopy(approved['plan'])
    automatic_edit.require_review(old)
    kept=[sid for sid in old['order'] if sid not in old.get('drop',[])];context=arc.neighbors(source,rows,old,blocking)
    eligible=[c for c in context if c['restoreAllowed']]
    if any(not any(c['targetId']==b['id'] and c['side']==b['side'] for c in eligible) for b in blocking):raise error
    chosen=approved.get('selected');directions=approved.get('directions',[])
    if type(chosen) is not int or not 0<=chosen<len(directions):raise error
    folder=api.ROOT/'outputs'/key;archive=folder/'failed-acoustic-after-semantic-0';archive.mkdir(parents=True,exist_ok=True)
    for p in folder.iterdir():
        if p.is_file():shutil.copy2(p,archive/p.name)
    api.save(archive/'approved-planning.json',approved)
    feedback={'stage':'audio-boundaries','reason':str(error),'blocking':copy.deepcopy(blocking),
        'boundaryNeighbors':context,'boundaryRecoveryRule':arc.RULE,
        'heldOptionalSpeech':copy.deepcopy(prior_holds),
        'approvedEdit':{'order':kept,'framework':old.get('selectedFramework'),'topic':old.get('topic'),
            'rule':'本次只修实际静音边界失败：只可补回boundaryNeighbors中restoreAllowed的完整相邻原话，所有已保留句及相对顺序、旧删字、标题画面、段内操作不变。heldOptionalSpeech是已核验须暂留的原声，不再尝试去掉；不换主线，不把它当创作者素材指令。语义、硬时长及全部声学门禁仍须通过。'}}
    api.save(archive/'failure.json',feedback)
    api.TASKS.progress(key,'正在按实际声音接缝补齐连续内容组')
    revised={k:copy.deepcopy(v) for k,v in payload.items() if k not in ('planningId','previousId','choice','frameworkOverride')}
    revised.update(previousId=approved['id'],choice=chosen,conversation=copy.deepcopy(approved.get('conversation',[])),executionFeedback=feedback,catalogOnly=False,fullScan=False,editMode=approved.get('editMode','full'))
    planning=ep.run(key,record,revised,api)
    new_authority=ep.confirmed(record,{**payload,'planningId':planning['id']},api);new=new_authority['plan']
    new_kept=[sid for sid in new['order'] if sid not in new.get('drop',[])];allowed={c['neighborId'] for c in eligible}
    new_selected=new_authority.get('selected');new_directions=new_authority.get('directions',[])
    same_direction=type(new_selected) is int and 0<=new_selected<len(new_directions) and new_directions[new_selected].get('name')==directions[chosen].get('name')
    valid=(new_authority.get('sourceId')==approved['sourceId'] and new_authority.get('id')==planning['id'] and same_direction
        and [sid for sid in new_kept if sid in kept]==kept and set(new_kept)<=set(kept)|allowed
        and new.get('selectedFramework')==old.get('selectedFramework'))
    holds=sr.optional_holds(new,semantic_error,project,planning['id']) if valid else None
    if valid:holds=sr.carry_optional_holds(prior_holds,holds,project,new)
    effective=sr.withheld_plan(project,new,holds) if holds and holds['holds'] else new
    operations_same=valid and all(effective.get(f,[])==old.get(f,[]) for f in ('wordEdits','questionCuts','statementCuts','repetitions'))
    cover_same=valid and all(new.get(f)==old.get(f) for f in ('coverTitle','coverSubtitle'))
    def connected(c):
        if c['targetId'] not in new_kept:return False
        at=new_kept.index(c['targetId'])+(-1 if c['side']=='start' else 1)
        return 0<=at<len(new_kept) and new_kept[at]==c['neighborId']
    connected_all=bool(eligible) and all(connected(c) for c in eligible)
    audit={'version':VERSION,'stages':{'semanticReplans':1,'postSemanticAcousticReplans':1,'maxExecutions':3},
        'approvedPlanningId':approved['id'],'recoveryPlanningId':planning['id'],'approvedKept':kept,'recoveryKept':new_kept,
        'context':context,'sameDirection':same_direction,'scopeValid':valid,'operationsUnchanged':operations_same,
        'coverUnchanged':cover_same,'failedSeamsConnected':connected_all,'optionalHolds':holds,
        'passed':valid and operations_same and cover_same and connected_all}
    api.save(folder/'staged-recovery-intent.json',audit)
    if not audit['passed']:raise ValueError('连续内容组修复未保持已确认范围或仍未连接失败接缝，原稿保留')
    # No catch/re-entry: the third execution is terminal, including semantic,
    # source/normal-word, transport, duration, and further acoustic failures.
    result=execute(key,record,{**payload,'planningId':planning['id']},api,music_allowed,
        **({'optional_holds':holds} if holds and holds['holds'] else {}))
    result['postSemanticAcousticRecovery']={'version':VERSION,'planningId':planning['id'],'attempted':True}
    return result
