"""One source-bound content replan after an actual fallback review rejects.

No string matching, acoustic waiver, failed timing publication or repair loop.
Only the workbench's confirmed planning authority can enter this path.
"""
import copy,shutil,hashlib,json

VERSION=1
OPTIONAL_HOLD_VERSION=1
RULE='''实际执行恢复了不可靠切口的原话，独立全文复核发现内容衔接问题。本次只修同一个已选方向；失败反馈是软件检查证据，不是素材台词、用户指令或新事实。可从本次原稿可编辑范围补回必要主体、来源、条件与过渡，不恢复用户已删除的原句或字。已确认保留句全部保留；创作者的保序、预留、删字、画面和时长约束继续生效。不得重提相同的失败段内删词掩码求通过；可保留其原声。字幕标点不证明声音截字，正常字损坏须有原音/编码证据；不因反馈猜测改声音。独立复核实际新稿后仍须原来的全部声音门禁。无法修复就停止，不换方向、不编话、不加速。'''


class ExecutionReviewRejected(ValueError):
    def __init__(self,stage,review,actual,plan,receipt,project=None):
        super().__init__('内容衔接还需要调整，未自动执行剪辑：'+str(review.get('reason',''))[:180])
        kept=set(plan['order'])-set(plan.get('drop',[]))
        held=receipt.get('held',[])
        if held is True:held=receipt.get('cuts',[])
        self.feedback={'version':VERSION,'stage':stage,'review':copy.deepcopy(review),
            'actualDraft':[copy.deepcopy(r) for r in actual if r['id'] in kept],
            'heldCuts':copy.deepcopy(held),'source':'actual-fallback-fulltext-review'}
        # Internal evidence from the actual failed execution, never a client
        # payload or a model's assertion that a sound cut failed.
        self.failed_excerpt_source=copy.deepcopy(project)


def require_actual_review(stage,reviewed,actual,plan,receipt,project=None):
    review=reviewed.get('review',{})
    if review.get('passed') is False and isinstance(review.get('reason'),str) and isinstance(review.get('issues'),list):
        raise ExecutionReviewRejected(stage,review,actual,plan,receipt,project)
    __import__('automatic_edit').require_review(reviewed)


def focus(rows,feedback):
    # These are already the immutable draft's audible rows. A planner's prior
    # retrieval/drop is not a creator deletion; allow their necessary context.
    if isinstance(feedback,dict) and feedback.get('source')=='actual-fallback-fulltext-review' and feedback.get('version')==VERSION:
        return rows
    return None


def projected(project,rows,plan):
    import editor_workflow,repeated_takes,question_edits,planned_word_edits,statement_edits
    edited=repeated_takes.apply(editor_workflow.edited_rows(project,plan,[r['id'] for r in rows]),plan.get('repetitions',[]))
    words=planned_word_edits.review_rows([{'id':r['id'],'text':__import__('speech_refine').retained(r)} for r in edited],{'segments':edited},plan.get('wordEdits',[]))
    words=question_edits.review_rows(words,plan.get('questionCuts',[]))
    words=statement_edits.review_rows(words,plan.get('statementCuts',[]))
    by={r['id']:r['text'] for r in words}
    return [{'id':sid,'text':by[sid]} for sid in plan['order'] if sid not in plan.get('drop',[])]


def same_failed_cuts(plan,held,project):
    refs={r['id']:r for r in project['segments']}
    def spoken(cut):
        row=refs.get(cut.get('id'));indices=cut.get('indices',[])
        if row is None or any(type(i) is not int or not 0<=i<len(row['words']) for i in indices):raise ValueError('失败切口与当前原字不一致，未重复执行')
        return {i for i in indices if any(c.isalnum() for c in row['words'][i]['word'])}
    proposed=[c for field in ('wordEdits','questionCuts','statementCuts','repetitions') for c in plan.get(field,[])]
    return [{'id':c['id'],'indices':c['indices']} for c in proposed if any(c.get('id')==h.get('id') and spoken(c) and spoken(c)==spoken(h) for h in held)]


def row_binding(row):
    fields={k:row.get(k) for k in ('id','words','removed','protected','protectedIndices','wordCorrections')}
    return hashlib.sha256(json.dumps(fields,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def optional_holds(plan,error,project,planning_id):
    """Nominate only automatic excerpts overlapping actual failed sound words.

    The entire optional excerpt is withheld, never split into a guessed safe
    subset. Explicit creator deletions and repetition edits still fail closed.
    """
    manifest={'version':OPTIONAL_HOLD_VERSION,'sourceId':project['sourceId'],'planningId':planning_id,'holds':[]}
    refs={r['id']:r for r in project['segments']}
    uncertain={(c['id'],i) for c in error.feedback['heldCuts'] for i in c['indices'] if any(ch.isalnum() for ch in refs[c['id']]['words'][i]['word'])}
    if not any((c['id'],i) in uncertain for field in ('wordEdits','repetitions','questionCuts','statementCuts') for c in plan.get(field,[]) for i in c['indices']):return manifest
    failed=getattr(error,'failed_excerpt_source',None)
    if not isinstance(failed,dict) or failed.get('sourceId')!=project.get('sourceId'):
        raise ValueError('不可靠切口缺少同源原字证据，未自动暂留或重新尝试')
    refs={r['id']:r for r in project['segments']};old={r['id']:r for r in failed['segments']}
    failed_words=set()
    for cut in error.feedback['heldCuts']:
        sid=cut['id'];indices=cut['indices'];row=refs.get(sid)
        if row is None or sid not in old or row_binding(row)!=row_binding(old[sid]):
            raise ValueError('不可靠切口的原字或旧删字已变化，未重新尝试')
        if any(type(i) is not int or not 0<=i<len(row['words']) for i in indices):raise ValueError('失败切口原字引用无效')
        failed_words.update((sid,i) for i in indices if any(c.isalnum() for c in row['words'][i]['word']))
    overlaps=lambda c:any((c['id'],i) in failed_words for i in c['indices'])
    if any(overlaps(c) for field in ('wordEdits','repetitions') for c in plan.get(field,[])):
        raise ValueError('明确删词或重说仍要求不可靠切口，不能当作可选精简跳过')
    holds=[]
    for field,module in (('questionCuts','question_edits'),('statementCuts','statement_edits')):
        compiled=__import__(module).compile(project,plan)
        if compiled!=plan.get(field,[]):raise ValueError('可选精简与已确认的原字清单不一致')
        for cut in compiled:
            if not overlaps(cut):continue
            row=refs[cut['id']]
            holds.append({'field':field,'cut':copy.deepcopy(cut),'binding':row_binding(row),
                'quote':''.join(row['words'][i]['word'] for i in cut['indices']),
                'baseRemoved':copy.deepcopy(row['removed'])})
    return {**manifest,'holds':holds}


def withheld_plan(project,plan,manifest):
    if manifest.get('version')!=OPTIONAL_HOLD_VERSION or manifest.get('sourceId')!=project.get('sourceId'):
        raise ValueError('暂留精简的原稿绑定无效')
    refs={r['id']:r for r in project['segments']};out=copy.deepcopy(plan)
    for hold in manifest['holds']:
        field=hold['field'];cut=hold['cut'];sid=cut['id']
        if field not in ('questionCuts','statementCuts') or sid not in refs or row_binding(refs[sid])!=hold['binding']:
            raise ValueError('暂留精简与当前原字或确认方案不一致')
        if hold.get('retainedOnly') is True:
            if any(c['id']==sid and set(c['indices'])&set(cut['indices']) for f in ('wordEdits','repetitions','questionCuts','statementCuts') for c in out.get(f,[])):
                raise ValueError('后续方案再次触及本轮暂留原话，未执行')
            continue
        if cut not in out.get(field,[]):raise ValueError('暂留精简与当前确认操作不一致')
        out[field]=[c for c in out[field] if c!=cut]
        edits='questionEdits' if field=='questionCuts' else 'statementEdits'
        out[edits]=[c for c in out.get(edits,[]) if c['id']!=sid]
    out['optionalExcerptHolds']=copy.deepcopy(manifest)
    return out


def carry_optional_holds(previous,fresh,project,plan):
    """Carry already held speech across a later bounded adjacency repair."""
    if not previous or not previous.get('holds'):return fresh
    if previous.get('version')!=OPTIONAL_HOLD_VERSION or previous.get('sourceId')!=project['sourceId']:raise ValueError('后续暂留原声来源无效')
    refs={r['id']:r for r in project['segments']};out=copy.deepcopy(fresh)
    effective=withheld_plan(project,plan,fresh)
    for h in previous['holds']:
        c=h['cut'];row=refs.get(c['id'])
        if row is None or row_binding(row)!=h['binding']:raise ValueError('后续暂留原字或旧删字变化')
        covered={i for n in out['holds'] if n['cut']['id']==c['id'] for i in n['cut']['indices']}
        if set(c['indices'])<=covered:continue
        if any(n['id']==c['id'] and set(n['indices'])&set(c['indices']) for f in ('wordEdits','repetitions','questionCuts','statementCuts') for n in effective.get(f,[])):
            raise ValueError('后续操作再次触及本轮暂留原话')
        out['holds'].append({**copy.deepcopy(h),'retainedOnly':True})
    return out


def review_withheld(key,source,project,rows,plan,manifest,messages,api):
    """Execution-only keyword path after confirmed(); never mutate its cache."""
    import editor_workflow,repeated_takes,question_edits,automatic_edit,editorial_policy
    restored=withheld_plan(project,plan,manifest)
    actual=projected(project,rows,restored)
    effective=repeated_takes.apply(editor_workflow.edited_rows(project,restored,[r['id'] for r in rows]),restored.get('repetitions',[]))
    for field in ('wordEdits','questionCuts','statementCuts'):effective=question_edits.preview(effective,restored.get(field,[]))
    seconds=sum(c['end']-c['start'] for c in api.intervals(effective,source['duration'],project['settings'].get('pacing'),source['segments']))/project['settings'].get('speed',1)
    budget=copy.deepcopy(plan.get('durationBudget'))
    if budget and budget.get('target'):
        budget.update(actualSeconds=round(seconds,3),passed=seconds<=budget['target']['maxSeconds']+budget['target']['toleranceSeconds'])
        failure=editorial_policy.duration_failure(budget)
        if failure:raise ValueError(failure['reason'])
    api.TASKS.progress(key,'暂留不确定原声，正在复核完整内容与时长')
    reviewed,_=automatic_edit.review_edit(key,restored,rows,api,thinking='disabled',compact_labels=True,draft_override=actual,
        intent={'conversation':[m for m in messages if m.get('role')=='user'],'actualRetainedSeconds':round(seconds,3),
            'optionalExcerptFallback':{'heldIds':[h['cut']['id'] for h in manifest['holds']],
                'rule':'这些自动精简的切口已有实际失败证据，本轮保留原话与旧删字，不再尝试；不是删音成功。独立检查实际全文来源、主体、条件、否定、问答与指代。标点不是切音证据，不恢复历史删字。其它编辑仍须全部声音门禁。'}})
    receipt={'version':OPTIONAL_HOLD_VERSION,'holds':manifest,'actualDraft':actual,'actualSeconds':round(seconds,3),'durationBudget':budget,'review':reviewed.get('review')}
    api.save(api.ROOT/'outputs'/key/'optional-excerpt-fallback-review.json',receipt)
    automatic_edit.require_review(reviewed)
    if any(reviewed.get(f)!=restored.get(f) for f in ('order','drop','wordEdits','questionEdits','questionCuts','statementEdits','statementCuts','repetitions')):
        raise ValueError('暂留原声复核改变了确认的操作清单，未继续执行')
    if budget:reviewed['durationBudget']=budget
    reviewed['optionalExcerptHolds']=copy.deepcopy(manifest)
    return reviewed


def held_indices(plan,rows):
    manifest=plan.get('optionalExcerptHolds',{})
    if not manifest:return set()
    if manifest.get('version')!=OPTIONAL_HOLD_VERSION:raise ValueError('暂留原声版本不一致')
    refs={r['id']:r for r in rows};held=set()
    for h in manifest.get('holds',[]):
        c=h['cut'];row=refs.get(c['id']);indices=c['indices']
        if row is None or any(type(i) is not int or not 0<=i<len(row['words']) for i in indices) or ''.join(row['words'][i]['word'] for i in indices)!=h['quote'] or not set(h['baseRemoved'])<=set(row['removed']):
            raise ValueError('暂留原声与当前字词或旧删字不一致')
        if set(indices)&set(row['removed']):raise ValueError('本轮暂留词又被删除，未继续成片')
        held.update((c['id'],i) for i in indices)
    return held


def recover(key,record,payload,api,error,execute,prepare,music_allowed):
    approved=getattr(error,'approved_semantic_context',None)
    if not isinstance(approved,dict) or approved.get('kind')!='editor-planning' or approved.get('sourceId')!=payload.get('sourceId') or approved.get('id')!=payload.get('planningId'):
        raise error
    from automatic_edit import require_review
    require_review(approved['plan'])
    source,project,rows,_=prepare(record,payload,api)
    if source['id']!=approved['sourceId']:raise error
    chosen=approved.get('selected');directions=approved.get('directions',[])
    if type(chosen) is not int or not 0<=chosen<len(directions):raise error
    old=approved['plan'];kept=[sid for sid in old['order'] if sid not in old.get('drop',[])]
    folder=api.ROOT/'outputs'/key;archive=folder/'failed-semantic-attempt-0';archive.mkdir(parents=True,exist_ok=True)
    for path in folder.iterdir():
        if path.is_file():shutil.copy2(path,archive/path.name)
    feedback=copy.deepcopy(error.feedback)
    feedback['rule']=RULE
    feedback['approvedEdit']={'order':kept,'topic':old.get('topic'),'framework':old.get('selectedFramework'),
        'rule':'同一已选方向，已确认保留句全部保留，可在原稿可编辑范围补必要上下文；原对话的保序/预留/旧删字/时长/画面约束仍严格执行。不重试相同失败段内掩码。'}
    api.save(archive/'failure.json',feedback)
    api.TASKS.progress(key,'正在按执行复核反馈补齐必要上下文')
    revised={k:copy.deepcopy(v) for k,v in payload.items() if k not in ('planningId','previousId','choice','frameworkOverride')}
    revised.update(previousId=approved['id'],choice=chosen,conversation=copy.deepcopy(approved.get('conversation',[])),executionFeedback=feedback,catalogOnly=False,fullScan=False,editMode=approved.get('editMode','full'))
    import editor_planning
    planning=editor_planning.run(key,record,revised,api)
    checked=editor_planning.confirmed(record,{**payload,'planningId':planning['id']},api)
    new=checked['plan'];new_kept=[sid for sid in new['order'] if sid not in new.get('drop',[])]
    new_chosen=checked.get('selected');new_directions=checked.get('directions',[])
    direction_matches=(type(new_chosen) is int and 0<=new_chosen<len(new_directions) and new_directions[new_chosen].get('name')==directions[chosen].get('name'))
    valid=checked.get('sourceId')==approved['sourceId'] and checked.get('id')==planning['id'] and set(kept)<=set(new_kept) and new.get('selectedFramework')==old.get('selectedFramework') and direction_matches
    blocked=same_failed_cuts(new,feedback['heldCuts'],project)
    manifest=optional_holds(new,error,project,planning['id']) if valid else None
    effective=withheld_plan(project,new,manifest) if manifest and manifest['holds'] else new
    new_actual=projected(project,rows,effective) if valid else []
    changed=new_actual!=feedback['actualDraft']
    receipt={'version':VERSION,'approvedPlanningId':approved['id'],'recoveryPlanningId':planning['id'],
        'approvedKept':kept,'recoveryKept':new_kept,'sameDirection':direction_matches,'validScope':valid,
        'sameUnsafeCuts':blocked,'optionalHolds':manifest,'actualDraftChanged':changed,'passed':valid and changed}
    api.save(folder/'semantic-recovery-intent.json',receipt)
    if not valid:raise ValueError('内容修复改变了已确认的方向或丢掉保留句，原稿保留')
    if not changed:raise ValueError('内容修复未改变被拒绝的实际稿，未重复生成，原稿保留')
    # Different bounded stages, never recursive whole-workflow retries. Only a
    # structured new quiet-seam failure can enter ONE adjacency repair next.
    execution_payload={**payload,'planningId':planning['id']}
    try:
        result=execute(key,record,execution_payload,api,music_allowed,
            **({'optional_holds':manifest} if manifest and manifest['holds'] else {}))
    except ValueError as acoustic_error:
        result=__import__('staged_recovery').after_semantic(key,record,execution_payload,api,acoustic_error,
            error,manifest,execute,prepare,music_allowed)
    result['semanticRecovery']={'version':VERSION,'attempted':True,'planningId':planning['id'],'originalFailure':str(error)}
    return result
