"""Contiguous statement excerpts: proposed text, independent review, exact audio.

No model timestamp or deletion index is trusted. This is distinct from a
creator's explicitly quoted removal and from disfluency detection.
"""
import copy,re

VERSION=3
FALLBACK_VERSION=1
REFERENCE_REPAIR_VERSION=1
RULE='''陈述句段内精简：仅删整句不足以实现开场精简时，可建议statementEdits:[{id,keepQuote,reason}]。keepQuote必须是该保留陈述句当前可见原话中唯一、连续、逐字存在的一段完整表达；只能去掉它前后可有可无的铺垫，不能拼词改写。普通提问仍用questionEdits，不混用。没有必要则statementEdits=[]。不能删掉必要的主体、转述来源、否定、条件、数字、时间或归属；“就跟我讲说”只有在信息来源仍明确时才可能精简，不能把转述个案包装成全部人的普遍结论。工具会保护事实词和预留文字，复核实际保留全文，再核验真实删音。只在说明里说“用老板想给员工加活开场”，实际仍保留“就跟我讲说”不算已经精简；需要段内删音必须返回具体keepQuote。声音切点不可靠就保留对应原话；其余候选只能从原稿重新核验安全子集，并独立复核实际全文后继续。不能承诺全部精简或三秒已达标，不只改字幕、截字或加速。'''
RULE+='\n仅去掉字面语气词或紧邻重说，交普通声音精剪，不用statementEdits把它们捆成内容摘取；不因语气词切不准就阻止另一项独立重复词接受正常复核。它们仍是候选，不是删除许可，后续必须重新核对实际完整语义、正常邻字和真实切后声音。'


def disfluency_only(row,indices):
    """Route a literal-only proposal, never grant it any deletion permission.

    Reuse the ordinary candidate grammar, including natural reduplication and
    protected-word exclusions. A content excerpt keeps its atomic permission.
    """
    from speech_refine import literal_candidates,FACT
    selected={i for i in indices if any(c.isalnum() for c in row['words'][i]['word'])}
    if not selected or FACT.search(''.join(row['words'][i]['word'] for i in sorted(selected))):return False
    eligible={i for i in selected if re.fullmatch('[呃嗯额啊哦哎]+',row['words'][i]['word'])}
    for candidate in literal_candidates([row]):
        # Only complete nominated occurrences; no partial word or permission
        # borrowed from a larger failed restart.
        group=set(candidate['indices'])
        if candidate.get('kind')=='repeat' and group<=selected:eligible.update(group)
    return selected<=eligible


def compile(project,plan):
    from speech_refine import FACT
    raw=plan.get('statementEdits',[])
    if not isinstance(raw,list) or len(raw)>20:raise ValueError('陈述精简清单无效')
    if not raw:return []
    refs={r['id']:r for r in project['segments']}
    labels={r['id']:r.get('label') for r in plan.get('labels',[])}
    kept=set(plan['order'])-set(plan.get('drop',[]));seen=set();out=[]
    other=set()
    for field in ('wordEdits','questionEdits','questionCuts'):
        items=plan.get(field,[])
        if not isinstance(items,list):raise ValueError('其他段内编辑清单无效')
        other.update(e.get('id') for e in items if isinstance(e,dict))
    for edit in raw:
        if not isinstance(edit,dict) or set(edit)!={'id','keepQuote','reason'}:raise ValueError('陈述精简引用无效')
        sid=edit['id'];quote=edit['keepQuote'];reason=edit['reason']
        if not isinstance(sid,str) or sid in seen or sid not in refs or sid not in kept or sid not in labels or labels[sid]=='提问' or sid in other:
            raise ValueError('陈述精简须对应唯一保留陈述句，不能与其他段内编辑混用')
        seen.add(sid);row=refs[sid]
        if row['deleted'] or row.get('protected') or not isinstance(quote,str) or not 1<=len(quote)<=300 or not any(c.isalnum() for c in quote) or not isinstance(reason,str) or not reason.strip() or len(reason)>500:
            raise ValueError('预留陈述或精简原话无效')
        chars=[];positions=[]
        for i,w in enumerate(row['words']):
            if i in row['removed']:continue
            word=row.get('wordCorrections',{}).get(str(i),w['word'])
            chars.extend(word);positions.extend([i]*len(word))
        text=''.join(chars)
        if text.count(quote)!=1:raise ValueError('陈述短句不是唯一连续原话')
        start=text.index(quote);keep=set(positions[start:start+len(quote)])
        if ''.join(row.get('wordCorrections',{}).get(str(i),row['words'][i]['word']) for i in sorted(keep))!=quote:
            raise ValueError('陈述精简不能切开同一原词')
        indices=[i for i in range(len(row['words'])) if i not in keep and i not in row['removed']]
        if set(indices)&set(row.get('protectedIndices',[])):raise ValueError('陈述精简不能删除预留文字')
        removed=''.join(row['words'][i]['word'] for i in indices)
        if FACT.search(removed):raise ValueError('陈述精简不能自动删掉否定、条件、数字或时间限定')
        if indices and any(c.isalnum() for c in removed) and not disfluency_only(row,indices):
            out.append({'id':sid,'indices':indices,'keepQuote':quote,'reason':reason})
    return out


def review_rows(rows,cuts):
    # Same exact kept-quote view as the question editor; no audio is edited here.
    from question_edits import review_rows as view
    return view(rows,cuts)


def prepare(key,project,plan,api):
    """Repair one literal citation error, never waive facts or sound gates."""
    def prepared(value):
        cuts=compile(project,value);active={c['id'] for c in cuts}
        deferred=[e for e in value.get('statementEdits',[]) if e['id'] not in active]
        if not deferred:return value,cuts
        result=copy.deepcopy(value);result['statementEdits']=[e for e in result['statementEdits'] if e['id'] in active]
        api.save(api.ROOT/'recognition-cache'/('statement-disfluency-deferral-'+key+'.json'),
            {'version':VERSION,'sourceId':project.get('sourceId'),'proposals':deferred,'reason':'不产生连续内容摘取；保留原字交常规声音候选独立判断，没有新增删音权限'})
        return result,cuts
    try:return prepared(plan)
    except ValueError as error:
        if str(error) not in ('陈述短句不是唯一连续原话','陈述精简不能切开同一原词'):raise
        from content_recipe import bounded_request
        from analysis_usage import safe_usage
        raw=plan.get('statementEdits',[]);refs={r['id']:r for r in project['segments']}
        ids={e.get('id') for e in raw if isinstance(e,dict)}
        if any(not isinstance(sid,str) or sid not in refs or refs[sid]['deleted'] or sid in plan.get('drop',[]) for sid in ids):raise
        rows=[]
        for r in project['segments']:
            if r['id'] not in ids:continue
            rows.append({'id':r['id'],'text':''.join(r.get('wordCorrections',{}).get(str(i),w['word']) for i,w in enumerate(r['words']) if i not in r['removed']),
                'protected':bool(r.get('protected')),'protectedIndices':r.get('protectedIndices',[])})
        api.TASKS.progress(key,'正在核对陈述短句与实际原话')
        fixed,usage=bounded_request(RULE+'\n仅修正previousEdits中的原字引用，不换主线、顺序、删句或新增编辑对象。keepQuote含标点都须在对应当前text内唯一、连续、逐字存在，不能拼词、换连词或标点、切开原词。内部重复去词不是连续摘取，不能保留首尾却跳过中间词来造keepQuote；可放弃这项自动陈述精简，后续由重说原音流程判断。只有前后均属无信息失败起句/铺垫且不删额外正常含义时才选择另一连续完整原话；不能为凑引用丢主体、条件、数字、否定或转述归属。不确定就从statementEdits去掉该候选，保留原话。只返回JSON {statementEdits:[{id,keepQuote,reason}]}，id仅取previousEdits。后面仍会独立复核全文并校准声音。',
            {'currentStatements':rows,'previousEdits':raw,'feedback':str(error)},api,key=key,max_output_tokens=4096,thinking='disabled',phase='statement-reference-repair')
        if callable(getattr(api.TASKS,'analysis_attempt',None)):api.TASKS.analysis_attempt(key,{'phase':'statement-reference-repair','status':'returned','usage':safe_usage(usage)})
        api.save(api.ROOT/'recognition-cache'/('statement-reference-repair-'+key+'.json'),{'version':REFERENCE_REPAIR_VERSION,'previousEdits':raw,'feedback':str(error),'result':fixed})
        if not isinstance(fixed,dict) or set(fixed)!={'statementEdits'} or not isinstance(fixed['statementEdits'],list) or any(not isinstance(e,dict) or e.get('id') not in ids for e in fixed['statementEdits']):
            raise ValueError('陈述引用修正超出原候选范围，原稿保留')
        repaired={**copy.deepcopy(plan),'statementEdits':fixed['statementEdits']}
        return prepared(repaired)


def preview(segments,cuts):
    from question_edits import preview as view
    return view(segments,cuts)


def execute(key,record,source,project,plan,api,*,publish_targets_only=False):
    cuts=compile(project,plan)
    if not cuts:return record,source,project,{'version':VERSION,'applied':False,'cuts':[]}
    if plan.get('review',{}).get('passed') is not True:raise ValueError('陈述精简尚未通过实际全文复核')
    if plan.get('statementCuts')!=cuts:raise ValueError('陈述精简与已复核的原字引用不一致')
    import manual_word_edit
    # Internal keyword only: the public word-edit payload cannot grant an
    # ordinary phrase permission to use the source-bound difference audit.
    def attempt(candidates,targets_only):
        return manual_word_edit.run(key,record,{**project,'selectedWords':[{'id':e['id'],'index':i} for e in candidates for i in e['indices']]},api,reviewed_excerpts=candidates,**({'publish_targets_only':True} if targets_only else {}))
    result=attempt(cuts,publish_targets_only)
    attempts=[{'cuts':copy.deepcopy(cuts),'changed':bool(result['changed']),'calibration':copy.deepcopy(result.get('calibration')),'acousticReview':copy.deepcopy(result.get('acousticReview'))}]
    applied_cuts=cuts if result['changed'] else []
    if not result['changed']:
        # The failed joint audition's successful row IDs are only nominations.
        # Remove the failed candidates, restore the ORIGINAL source/masks, then
        # audition that exact subset once. Never publish a mixed failed timing
        # source, retry the failed candidate, or infer success from a row flag.
        safe=set(result.get('acousticReview',{}).get('passedIds',[]))
        subset=[c for c in cuts if c['id'] in safe]
        if subset and len(subset)<len(cuts):
            api.TASKS.progress(key,'保留不确定的原声，重新核验其余精简切口')
            result=attempt(subset,True)
            attempts.append({'cuts':copy.deepcopy(subset),'changed':bool(result['changed']),'calibration':copy.deepcopy(result.get('calibration')),'acousticReview':copy.deepcopy(result.get('acousticReview'))})
            if result['changed']:applied_cuts=subset
    if result['changed']:
        actual=result['project'];after=actual['segments'];before=project['segments']
        wanted={e['id']:set(e['indices']) for e in applied_cuts}
        if ([r['id'] for r in after]!=[r['id'] for r in before] or actual['settings']!=project['settings']
            or actual.get('sourceId')!=result.get('sourceId') or result['source'].get('id')!=result.get('sourceId')):
            raise ValueError('陈述精简改变了已确认的工程范围，未采用')
        for a,b in zip(before,after):
            if ([w['word'] for w in a['words']]!=[w['word'] for w in b['words']]
                or set(b['removed'])!=set(a['removed'])|wanted.get(a['id'],set())
                or any(a.get(k)!=b.get(k) for k in ('deleted','protected','protectedIndices','wordCorrections'))):
                raise ValueError('陈述精简改变了非目标原字或恢复了旧删字，未采用')
    applied_ids={c['id'] for c in applied_cuts}
    refs={r['id']:r for r in project['segments']}
    held=[{**copy.deepcopy(c),'quote':''.join(refs[c['id']]['words'][i]['word'] for i in c['indices'])} for c in cuts if c['id'] not in applied_ids]
    receipt={'version':VERSION,'fallbackVersion':FALLBACK_VERSION,'applied':bool(result['changed']),'cuts':copy.deepcopy(cuts),
             'appliedCuts':copy.deepcopy(applied_cuts),'held':held,'attempts':attempts,
             'reason':result.get('reason') if not held else '部分陈述切口不确定，保留对应原声；其余仅在新掩码重新核验通过后采用',
             'calibration':result.get('calibration')}
    folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True)
    api.save(folder/'statement-edit-execution.json',receipt)
    if not result['changed']:return record,source,project,receipt
    return api.get_case(result['sourceId']),result['source'],result['project'],receipt


def review_held(key,record,source,project,plan,receipt,api):
    """Independently review the ACTUAL mixed kept/trimmed draft, fail closed.

    A short-quote approval is not approval of restored original context. This
    check cannot change a cut mask, invent an opening or waive sound gates.
    """
    if not receipt.get('held'):return plan
    import automatic_edit,word_corrections
    api.TASKS.progress(key,'正在核对保留原声后的完整内容与衔接')
    ids=set(plan['order']);originals=[r for r in api.sentences(record) if r['id'] in ids]
    if {r['id'] for r in originals}!=ids:raise ValueError('陈述回退复核的原稿已变化，未继续成片')
    actual=[{'id':r['id'],'text':''.join(w['word'] for i,w in enumerate(word_corrections.display_words(r)) if i not in r['removed'])} for r in project['segments']]
    restored={**copy.deepcopy(plan),'statementEdits':[],'statementCuts':[],'statementEditExecution':copy.deepcopy(receipt)}
    restored['drop']=[r['id'] for r in project['segments'] if r['id'] in ids and r['deleted']]
    seconds=sum(c['end']-c['start'] for c in api.intervals(project['segments'],source['duration'],project['settings'].get('pacing'),source['segments']))/project['settings'].get('speed',1)
    intent={'statementFallback':{'policy':'只采用实际核验过的精简；heldIds对应本次候选保留原声和旧删字。按actualDraft全文独立核对来源、主体、条件、否定、指代与开场，不沿用短稿通过结论，不假称三秒开场或语气已去净；不改变已确认顺序和删句。','heldIds':[e['id'] for e in receipt['held']],'appliedIds':[e['id'] for e in receipt['appliedCuts']]},'actualRetainedSeconds':round(seconds,3)}
    reviewed,_=automatic_edit.review_edit(key,restored,originals,api,thinking='disabled',compact_labels=True,draft_override=actual,intent=intent)
    folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True)
    audit={'version':FALLBACK_VERSION,'execution':receipt,'review':reviewed.get('review'),'actualRows':actual,'actualRetainedSeconds':round(seconds,3)}
    api.save(folder/'statement-fallback-review.json',audit)
    __import__('semantic_recovery').require_actual_review('statement-fallback',reviewed,actual,restored,receipt,project)
    if reviewed.get('order')!=restored['order'] or set(reviewed.get('drop',[]))!=set(restored['drop']):raise ValueError('陈述回退复核改变了确认的顺序或删句，未继续成片')
    budget=plan.get('durationBudget')
    if budget and budget.get('target'):
        checked={**budget,'actualSeconds':round(seconds,3),'passed':seconds<=budget['target']['maxSeconds']+budget['target']['toleranceSeconds']}
        failure=__import__('editorial_policy').duration_failure(checked)
        if failure:raise ValueError(failure['reason'])
        reviewed['durationBudget']=checked
    return reviewed


def held_indices(plan,rows):
    """Bind this execution's held words to current literal indices, not times."""
    receipt=plan.get('statementEditExecution',{})
    if receipt.get('fallbackVersion')!=FALLBACK_VERSION:return set()
    refs={r['id']:r for r in rows};held=set()
    for cut in receipt.get('held',[]):
        row=refs.get(cut.get('id'));indices=cut.get('indices',[])
        if row is None or not indices or any(type(i) is not int or not 0<=i<len(row['words']) for i in indices) or ''.join(row['words'][i]['word'] for i in indices)!=cut.get('quote'):
            raise ValueError('暂留声音与当前原话不一致，未重复尝试精简')
        held.update((row['id'],i) for i in indices)
    return held


def acoustic_proposals(request,ids,refs,edits,offsets):
    """Recompile the reviewed literal excerpt against this exact worker source.

    No semantic decision is made here. The sole producer of reviewedExcerpts
    is execute(), after confirmed planning and independent full-text review.
    Old deletions remain separate; they cannot inherit this new permission.
    """
    cuts=request.get('reviewedExcerpts',[])
    if not cuts:return []
    base=request.get('baseRemoved')
    if not isinstance(cuts,list) or not isinstance(base,dict):raise ValueError('陈述声音核验缺少原删字绑定')
    relevant=[c for c in cuts if isinstance(c,dict) and c.get('id') in ids]
    if not relevant:return []
    rows=[]
    for sid in ids:
        row=copy.deepcopy(edits[sid])
        if [w['word'] for w in refs[sid]['words']]!=[w['word'] for w in row['words']]:raise ValueError('陈述声音源原词变化')
        old=base.get(sid)
        if not isinstance(old,list) or any(type(i) is not int or not 0<=i<len(row['words']) for i in old) or old!=sorted(set(old)):
            raise ValueError('陈述原删字绑定无效')
        additions={i for c in relevant if c.get('id')==sid for i in c.get('indices',[])}
        if set(row['removed'])!=set(old)|additions:raise ValueError('陈述删音范围超出已复核方案')
        row['removed']=old;rows.append(row)
    plan={'order':ids,'labels':[{'id':sid,'label':'支撑'} for sid in ids],
          'statementEdits':[{'id':c.get('id'),'keepQuote':c.get('keepQuote'),'reason':c.get('reason')} for c in relevant]}
    derived=compile({'segments':rows},plan)
    if derived!=relevant:raise ValueError('陈述声音核验与已复核原字不一致')
    return [[offsets[c['id']]+i for i in c['indices'] if any(ch.isalnum() for ch in refs[c['id']]['words'][i]['word'])] for c in derived]
