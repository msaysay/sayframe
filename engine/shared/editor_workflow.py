"""Front-loaded, bound semantic advice; automatic edits operate on the current draft."""
import copy,hashlib,json,re,shutil
import automatic_edit,smart_pauses,repeated_takes

def is_full_long_source(source,rows,project=None):
    if source.get('duration',0)<=300:return False
    originals={r['id']:r for r in source['segments']};audible={r['id']:r['text'] for r in rows}
    if any(sid not in originals or text!=originals[sid]['text'] for sid,text in audible.items()):return False
    if project is not None and (set(s['id'] for s in project['segments'])!=set(originals) or any(s['deleted'] or s['removed'] for s in project['segments'])):return False
    return all(sid in audible or (project is not None and row['end']-row['start']<.04) for sid,row in originals.items())

def analysis_path(source,rows,binding,api,project=None):
    return api.ROOT/'recognition-cache'/(('editor-full-long-v1-' if is_full_long_source(source,rows,project) else 'editor-plan-v1-')+binding+'.json')

def full_long_plan(key,record,source,project,api):
    import content_recipe,semantic_recipe
    # Historical hand-written demonstrations are references, not a production
    # planning provider. A normal user workflow must obtain its own reviewed
    # model plan (or the planner's validated matching cache) every time.
    opts={'framework':project['settings'].get('framework','北极星'),'font':project['settings'].get('subtitle','standard'),'music':'auto'}
    planned=content_recipe.plan(key,source,opts,api);compiled=semantic_recipe.compile_recipe(planned['recipe'],source)
    plan=copy.deepcopy(compiled['plan']);selected=set(plan['order']);unused=[r['id'] for r in project['segments'] if r['id'] not in selected]
    plan.update(order=plan['order']+unused,drop=unused,dropReasons={sid:'不属于这条完整主线，原句仍可恢复' for sid in unused})
    plan['labels'] += [{'id':r['id'],'label':r.get('label','支撑'),'reason':'本条未选用，原句保留供其他选题'} for r in project['segments'] if r['id'] not in selected]
    plan['repetitions']=repeated_takes.validate([{'id':c['id'],'indices':c['indices'],'quote':c['quote'],'kind':'falseStart','reason':'精简不必要或重复的原话开头'} for c in compiled['cuts']],project['segments'])
    plan['highlights']=[]
    for row in compiled['project']['segments']:
        if row['deleted']:continue
        words=[];marks=set(row.get('emphasis',[]))
        for i,w in enumerate(row['words']):
            if i in row['removed']:continue
            if i in marks:words.append(w['word'])
            elif words:plan['highlights'].append({'id':row['id'],'quote':''.join(words)});words=[]
        if words:plan['highlights'].append({'id':row['id'],'quote':''.join(words)})
    return plan

def prepare(record,payload,api):
    source=api.public_case(record,True)
    project=api.PROJECT_LIBRARY.clean_project({'version':1,'sourceId':source['id'],'segments':payload.get('segments'),'settings':payload.get('settings',{})},source)
    settings=project['settings'];api.music_settings({'settings':settings,'musicId':settings.get('musicId')},api.ROOT/'uploads')
    clips=getattr(api,'planning_intervals',api.intervals)(project['segments'],source['duration'],settings.get('pacing'),source['segments'])
    rows=[]
    for s in project['segments']:
        if s['deleted']:continue
        runs=[c for c in clips if c['id']==s['id']]
        if not runs:continue
        audible=set(w['index'] for c in runs for w in c.get('words',[]))
        text=''.join(w['word'] for i,w in enumerate(__import__('word_corrections').display_words(s)) if i not in s['removed'] and (not audible or i in audible))
        if text.strip():rows.append({'id':s['id'],'text':text,'audioRanges':[[c['start'],c['end']] for c in runs]})
    if not rows:raise ValueError('请至少保留一句内容')
    context={s['id']:s.get('sourceUnit') for s in source['segments']}
    rows=[{**r,**({'sourceUnit':context[r['id']]} if context.get(r['id']) else {})} for r in rows]
    binding_data={'sourceId':source['id'],'rows':rows,'removed':[(s['id'],s['removed'],s['deleted']) for s in project['segments']],'framework':settings.get('framework','北极星'),'version':6,'editorialPolicyVersion':__import__('editorial_policy').VERSION,'openingContextVersion':__import__('opening_context').VERSION}
    protected=[s['id'] for s in project['segments'] if s.get('protected')]
    if protected:binding_data['protected']=protected
    reserved=[(s['id'],s['protectedIndices']) for s in project['segments'] if s.get('protectedIndices')]
    if reserved:binding_data['protectedIndices']=reserved
    binding=hashlib.sha256(json.dumps(binding_data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return source,project,rows,binding

def analyze(key,record,payload,api):
    source,project,rows,binding=prepare(record,payload,api);path=analysis_path(source,rows,binding,api,project);path.parent.mkdir(exist_ok=True)
    if path.is_file():return json.loads(path.read_text('utf-8'))|{'reused':True}
    if is_full_long_source(source,rows,project):
        plan=full_long_plan(key,record,source,project,api)
        # Cached long-video recipes predate explicit opening checks. Re-review
        # the actual selection rather than accepting an old pass flag.
        if plan.get('openingContextVersion')!=__import__('opening_context').VERSION:
            plan,_=automatic_edit.review_edit(key,plan,rows,api,thinking='disabled',compact_labels=True)
    else:plan=automatic_edit.plan_edit(key,record,{'framework':project['settings'].get('framework','北极星')},api,rows)
    automatic_edit.require_review(plan)
    if 'repetitions' not in plan:
        api.TASKS.progress(key,'正在检查重说和口误');checked=repeated_takes.analyze(project,api);plan['repetitions']=checked['cuts'];plan['repetitionWarnings']=checked['rejected'];plan['repetitionResponse']=checked['rawProposals']
    value={'kind':'editor-analysis','sourceId':source['id'],'binding':binding,'plan':plan,'reused':False}
    api.save(path,value);return value

def cached(record,payload,api):
    source,project,rows,binding=prepare(record,payload,api);path=analysis_path(source,rows,binding,api,project)
    return json.loads(path.read_text('utf-8'))|{'reused':True} if path.is_file() else None

def edited_rows(project,plan,editable_ids=None):
    originals={s['id']:copy.deepcopy(s) for s in project['segments']};alive={s['id'] for s in project['segments'] if not s['deleted'] and any(i not in s['removed'] for i,_ in enumerate(s['words']))};tags={x['id']:x['label'] for x in plan.get('labels',[])}
    expected=alive if editable_ids is None else set(editable_ids)
    if not expected.issubset(alive) or set(plan['order'])!=expected:raise ValueError('当前文稿已变化，请重新整理')
    out=[]
    for sid in plan['order']:
        row=originals[sid];row['deleted']=sid in plan.get('drop',[]) and not row.get('protected',False) and not any(i not in row['removed'] for i in row.get('protectedIndices',[]))
        if sid in tags:row['label']=tags[sid]
        value=next((v for v in plan.get('contentSelection',[]) if v['id']==sid),None)
        if value:row['contentValue']={k:v for k,v in value.items() if k!='id'}
        out.append(row)
    # Retain user-deleted rows for undo/restore. No AI operation resurrects them.
    for index,s in enumerate(project['segments']):
        if s['id'] in plan['order']:continue
        # prepare() excludes rows without an audible playback interval. Keep
        # their original words for restore, but never re-align them into speech
        # or show them as part of the confirmed edit.
        if editable_ids is not None and s['id'] in alive:
            originals[s['id']]['deleted']=True
            # Non-audible acknowledgements have no semantic planning label, but
            # remain valid project rows so the completed film can be restored.
            originals[s['id']].setdefault('label','支撑')
        anchor=next((x['id'] for x in project['segments'][index+1:] if x['id'] in plan['order']),None)
        place=next((i for i,x in enumerate(out) if x['id']==anchor),len(out))
        out.insert(place,originals[s['id']])
    return out

def run(key,record,payload,api,music_allowed=True,*,optional_holds=None):
    source,project,rows,binding=prepare(record,payload,api)
    if payload.get('planningId'):
        analysis=__import__('editor_planning').confirmed(record,payload,api);plan=copy.deepcopy(analysis['plan']);analysis['reused']=True
        directions=analysis.get('directions',[]);selected=analysis.get('selected')
        if type(selected) is int and 0<=selected<len(directions):plan['directionName']=directions[selected]['name']
        project['settings']['framework']=plan['selectedFramework'];plan['planningId']=analysis['id']
    else:analysis=analyze(key,record,payload,api);plan=analysis['plan']
    plan=copy.deepcopy(plan);plan.pop('optionalExcerptHolds',None);plan.pop('preservePresentationRows',None)
    if optional_holds:
        if not payload.get('planningId') or optional_holds.get('planningId')!=analysis.get('id'):raise ValueError('暂留精简缺少本轮确认方案绑定')
        plan=__import__('semantic_recovery').review_withheld(key,source,project,rows,plan,optional_holds,analysis.get('conversation',[]),api)
    speech_preserved=__import__('dialogue_constraints').require_speech_plan(analysis.get('conversation',[]) if payload.get('planningId') else [],plan)
    presentation_preserved=__import__('dialogue_constraints').preserve_presentation(analysis.get('conversation',[]) if payload.get('planningId') else [])
    local_scope=__import__('local_edit_scope').bind(analysis.get('conversation',[]) if payload.get('planningId') else [],project,plan)
    automatic_edit.require_review(plan);edited=repeated_takes.apply(edited_rows(project,plan,[r['id'] for r in rows]),plan.get('repetitions',[]))
    __import__('semantic_recipe').mark_highlights(edited,plan.get('highlights',[]),strict=False)
    if __import__('dialogue_constraints').preserve_editorial_rows(analysis.get('conversation',[]) if payload.get('planningId') else []):
        edited=__import__('dialogue_constraints').presentation_rows(project,edited)
        plan={**copy.deepcopy(plan),'preservePresentationRows':True}
        refs={r['id']:r for r in edited}
        for label in plan.get('labels',[]):
            row=refs.get(label['id'])
            if row is None:continue
            label.update(label=row.get('label',label['label']),reason='本轮仅处理声音，沿用当前编辑稿的内容标签与展示依据')
            value=row.get('contentValue')
            if isinstance(value,dict):label['selection']={k:v for k,v in value.items() if k in ('priority','kind','quote','claim','status')}
            else:label.pop('selection',None)
    try:
        return finish(key,record,source,project,edited,plan,api,music_allowed,analysis['reused'],**({'preserve_speech':True} if speech_preserved else {}),**({'preserve_presentation':True} if presentation_preserved else {}),**({'local_scope':local_scope} if local_scope else {}))
    except ValueError as error:
        if isinstance(error,__import__('semantic_recovery').ExecutionReviewRejected):
            error.approved_semantic_context=copy.deepcopy(analysis)
        if str(error).startswith('部分声音切口还不能安全定位'):
            # Authority is captured only after confirmed()/analyze() and review,
            # never from an unbound previousId supplied with a render request.
            error.approved_audio_context=copy.deepcopy(analysis)
        raise

def run_with_audio_recovery(key,record,payload,api,music_allowed=True):
    result=_run_with_audio_recovery(key,record,payload,api,music_allowed)
    return save_completed_project(key,result,api)

def save_completed_project(key,result,api):
    """A successful native workbench film owns a durable reopenable snapshot.

    Previously only batch output saved one, forcing a manual extra save for 08.
    Use the exact rendered project and its calibrated source, never the old UI
    draft. Failed renders/reviews never reach this function.
    """
    path=(api.ROOT/result['project'].lstrip('/')).resolve()
    if path.parent!=(api.ROOT/'outputs'/key).resolve():raise ValueError('成片工程不属于当前任务')
    project=json.loads(path.read_text('utf8'))
    name=result.get('plan',{}).get('directionName') or result.get('plan',{}).get('topic') or result['source']['title']
    saved=api.PROJECT_LIBRARY.create(name[:60],project,result['source'])
    return {**result,'savedProjectId':saved['id'],'savedProjectName':saved['name']}

def _run_with_audio_recovery(key,record,payload,api,music_allowed=True):
    """On an unsafe audio-boundary failure, ask the bound planner once to
    choose complete semantic groups, then execute that new reviewed plan.

    This is the normal workbench path as well as a reusable runtime rule. The
    original failed attempt is retained; a second failure is surfaced without
    weakening the acoustic gate or silently changing the spoken text.
    """
    try:
        return run(key,record,payload,api,music_allowed)
    except ValueError as error:
        if isinstance(error,__import__('semantic_recovery').ExecutionReviewRejected):
            return __import__('semantic_recovery').recover(key,record,payload,api,error,run,prepare,music_allowed)
        if not str(error).startswith('部分声音切口还不能安全定位'):
            raise
        folder=api.ROOT/'outputs'/key
        archive=folder/'failed-audio-attempt-0'
        archive.mkdir(parents=True,exist_ok=True)
        for file in folder.iterdir():
            if file.is_file():shutil.copy2(file,archive/file.name)
        feedback={'stage':'audio-boundaries','reason':str(error),
                  'blocking':copy.deepcopy(getattr(error,'blocking',[]))}
        receipt_file=folder/'clip-calibration.json'
        if receipt_file.exists() and not feedback['blocking']:
            feedback['blocking']=json.loads(receipt_file.read_text('utf8')).get('blocking',[])
        api.save(archive/'failure.json',feedback)
        api.TASKS.progress(key,'正在按完整语义组调整无法安全切开的片段')
        approved=getattr(error,'approved_audio_context',None)
        if not isinstance(approved,dict) or approved.get('sourceId')!=payload.get('sourceId') or not isinstance(approved.get('plan'),dict):
            raise
        approved_plan=approved['plan'];automatic_edit.require_review(approved_plan)
        kept=[sid for sid in approved_plan['order'] if sid not in approved_plan.get('drop',[])]
        import audio_recovery_context
        quiet_failures=audio_recovery_context.recovery_failures(feedback['blocking'])
        boundary_context=[]
        if quiet_failures:
            recovery_source,_,editable_rows,_=prepare(record,payload,api)
            boundary_context=audio_recovery_context.neighbors(recovery_source,editable_rows,approved_plan,quiet_failures)
        feedback['boundaryNeighbors']=boundary_context
        feedback['boundaryRecoveryRule']=audio_recovery_context.RULE
        api.save(folder/'audio-recovery-context.json',{'version':audio_recovery_context.VERSION,'neighbors':boundary_context,'rule':audio_recovery_context.RULE})
        feedback['approvedEdit']={'order':kept,'topic':approved_plan.get('topic'),
            'framework':approved_plan.get('selectedFramework'),'summary':approved_plan.get('summary'),
            'rule':'只修声音执行：已确认保留句全部保留并保持相对顺序，可补充必要邻句；不能通过删核心内容解决切口失败。无法安全完成则保留失败，不换选题。'}
        revised={k:copy.deepcopy(v) for k,v in payload.items() if k not in ('planningId','previousId','choice','frameworkOverride')}
        revised.update(conversation=copy.deepcopy(approved.get('conversation',payload.get('conversation',[]))),
                       executionFeedback=feedback,catalogOnly=False,fullScan=False,editMode=approved.get('editMode','full'))
        if approved.get('kind')=='editor-planning':
            revised.update(previousId=approved['id'],choice=approved['selected'])
        planning=__import__('editor_planning').run(key,record,revised,api)
        # Confirm against the original immutable draft again. A model's passed
        # flag cannot authorize discarding/reordering already approved speech.
        checked=__import__('editor_planning').confirmed(record,{**payload,'planningId':planning['id']},api)
        new_plan=checked['plan'];new_kept=[sid for sid in new_plan['order'] if sid not in new_plan.get('drop',[])]
        actual=[sid for sid in new_kept if sid in set(kept)]
        valid=actual==kept and new_plan.get('selectedFramework')==approved_plan.get('selectedFramework')
        receipt={'version':1,'approvedPlanningId':approved.get('id'),'recoveryPlanningId':planning['id'],
                 'approvedOrder':kept,'recoveryOrder':new_kept,'passed':valid}
        api.save(folder/'audio-recovery-intent.json',receipt)
        if not valid:raise ValueError('声音修复方案改变了已确认的内容或顺序，已保留原稿，请在规划中调整')
        unchanged=audio_recovery_context.unchanged_unsafe_seams(boundary_context,kept,new_kept,approved_plan,new_plan)
        if unchanged:
            api.save(folder/'audio-recovery-unchanged.json',{'version':audio_recovery_context.VERSION,'neighbors':unchanged,'passed':False})
            raise ValueError('声音修复仍保留相同的不可安全切口，未重复生成；原稿保留，请重新分析完整内容组')
        result=run(key,record,{**payload,'planningId':planning['id']},api,music_allowed)
        result['acousticRegrouping']={'attempted':True,'originalFailure':str(error),
                                     'planningId':planning['id']}
        return result

def refine_proposals(key,record,source,project,speech_input,pending,speech,plan,api,refine_scope='all'):
    """Commit calibration only with the same semantically accepted cut mask."""
    import speech_alignment,speech_refine
    prior_record,prior_source,prior_project=record,source,project
    record,project,alignment=speech_alignment.verify_proposals(record,{**project,'segments':speech_input},pending,api,key)
    if not alignment['applied']:
        speech=copy.deepcopy(speech);speech['cuts']=speech_refine.audition_scope(speech['cuts'],speech_input,{})
        speech['review']={'passed':True,'issues':[],'reason':'没有执行未通过联合声音复核的新增删词，保留原话'}
        return record,source,project,copy.deepcopy(speech_input),speech,alignment
    source=api.public_case(record,True)
    options={'scope':refine_scope} if refine_scope!='all' else {}
    if alignment.get('verifiedCutMasksVersion')==1:options['audited_masks']=alignment['verifiedCutMasks']
    edited,speech=speech_refine.refine(key,source,project['segments'],project['settings'],plan,api,proposal_receipt=speech if speech.get('proposalScope') else None,**options)
    transaction=speech_alignment.proposal_transaction_matches(prior_project,edited,pending,alignment)
    if not transaction['passed']:
        record,source,project=prior_record,prior_source,prior_project
        options['audited_masks']={}
        edited,speech=speech_refine.refine(key,source,speech_input,project['settings'],plan,api,proposal_receipt=speech if speech.get('proposalScope') else None,**options)
        alignment={**alignment,'applied':False,'transaction':transaction,'reason':'未采用联合校准的全部建议，保留原声音边界'}
    return record,source,project,edited,speech,alignment

def finish(key,record,source,project,edited,plan,api,music_allowed=True,analysis_reused=False,*,preserve_speech=False,local_scope=None,preserve_presentation=False):
    """Shared upload/workbench completion; review the actual retained speech
    before covers or media output. Original media and project stay immutable."""
    automatic_edit.require_review(plan)
    presentation_settings=copy.deepcopy(project['settings']) if preserve_presentation else None
    presentation_rows=copy.deepcopy(edited) if preserve_presentation and plan.get('preservePresentationRows') else None
    import speech_refine,speech_cleanup,content_safety
    edited=content_safety.apply_drops(edited,project['settings'])
    baseline=copy.deepcopy(project) if preserve_speech or local_scope else None
    clip_lock=__import__('local_clip_lock').capture(key,record,{'sourceId':source['id'],**baseline},local_scope,api) if local_scope else None
    local_inherited=clip_lock['notices'] if clip_lock else None
    preserved_source_id=source['id']
    if preserve_speech:
        from speech_preservation import unchanged
        unchanged(baseline,edited,source['id'],preserved_source_id,project['settings'])
        word_edit_receipt={'applied':False,'edits':[]}
        statement_receipt={'version':__import__('statement_edits').VERSION,'applied':False,'cuts':[]}
        speech_input=copy.deepcopy(edited);calibration_baseline=None
        speech={'version':speech_refine.VERSION,'cuts':[],'proposals':[],'rejected':[],'usage':[],
                'review':{'passed':True,'issues':[],'method':'not-needed-no-new-cuts','reason':'按本轮明确要求保留原词与声音，未发起新精剪，不代表语气词已去净'},
                'preservedByCreator':True}
        inherited=__import__('preserved_speech_context').inherit(key,{'sourceId':source['id'],**baseline},api)
        speech.update(inheritance=inherited,cuts=inherited['cuts'],rejected=inherited['rejected'])
    else:
        record,source,project,word_edit_receipt=__import__('planned_word_edits').execute(key,record,source,{**project,'segments':edited},plan,api)
        edited=project['segments']
        if word_edit_receipt['applied']:plan={**plan,'wordEditExecution':word_edit_receipt}
        record,source,project,statement_receipt=__import__('statement_edits').execute(key,record,source,project,plan,api,**({'publish_targets_only':True} if local_scope else {}))
        edited=project['segments']
        if statement_receipt['applied']:plan={**plan,'statementEditExecution':statement_receipt}
        if statement_receipt.get('held'):
            plan=__import__('statement_edits').review_held(key,record,source,project,plan,statement_receipt,api)
        record,source,project,question_receipt=__import__('question_edits').execute(key,record,source,project,plan,api)
        edited=project['segments']
        if question_receipt['applied']:plan={**plan,'questionEditExecution':question_receipt}
        elif question_receipt.get('held'):
            plan=__import__('question_edits').review_held(key,record,source,project,plan,question_receipt,api)
        record,source,project,filler_alignment=(record,source,project,{'applied':False}) if local_scope else speech_cleanup.prepare_timing(key,record,source,{**project,'segments':edited},api)
        edited=project['segments']
        if filler_alignment['applied']:
            plan=copy.deepcopy(plan);plan['fillerAlignment']=filler_alignment
        speech_input=copy.deepcopy(edited)
        if local_scope:
            cuts,rejected=__import__('preserved_speech_context').notices(local_inherited,edited,local_inherited.get('fromJobId',''))
            speech={'version':speech_refine.VERSION,'cuts':cuts,'rejected':rejected,'proposals':[],'usage':[],
                    'review':{'passed':True,'issues':[],'method':'no-global-cleanup-local-plan-only','reason':'仅执行已复核段内方案，其他待定原声保留；不代表去净'},'localScope':copy.deepcopy(local_scope)}
        else:edited,speech=speech_refine.refine(key,source,edited,project['settings'],plan,api)
        pending=[] if local_scope else speech_refine.acoustic_pending(speech)
        calibration_baseline=None
        if pending:
            calibration_baseline=(record,source,copy.deepcopy(project))
            record,source,project,calibrated_edit,speech,alignment=refine_proposals(key,record,source,project,speech_input,pending,speech,plan,api)
            if calibrated_edit is not None:edited=calibrated_edit
            plan=copy.deepcopy(plan);plan['speechAlignment']=alignment
            if not alignment.get('applied'):calibration_baseline=None
        blocking=speech_refine.unresolved_restarts(speech['cuts'])
        if blocking and not local_scope:
            failure_folder=api.ROOT/'outputs'/key;failure_folder.mkdir(parents=True,exist_ok=True)
            api.save(failure_folder/'speech-uncertain.json',{'sourceId':source['id'],'cuts':speech['cuts'],'review':speech['review'],'blocking':blocking})
            # No unsafe deletion has been applied for these holds. Keeping the
            # actual original speech is preferable to repeatedly changing a valid
            # topic to chase uncertain word boundaries. Review the retained text;
            # every downstream sound gate still runs, and pending counts remain.
            speech=__import__('speech_hold').review_retained(key,source,speech_input,edited,speech,blocking,project['settings'],api)
    # Keep an unproposed optional trim visible too: absence from the later
    # filler model is not proof its uncertain sound was successfully removed.
    statement_holds=__import__('statement_edits').held_indices(plan,edited)|__import__('semantic_recovery').held_indices(plan,edited)
    for sid in sorted({sid for sid,i in statement_holds}):
        row=next(r for r in edited if r['id']==sid)
        indices={i for held_sid,i in statement_holds if held_sid==sid}
        if not row['deleted'] and indices-set(row['removed']) and not any(c['id']==sid and indices.intersection(c['indices']) for c in speech['cuts']) and not any(c.get('id')==sid for c in speech.get('rejected',[])):
            speech.setdefault('rejected',[]).append({'id':sid,'reason':'这处精简的声音切点未确定，保留原话供回听','statementFallbackVersion':__import__('statement_edits').FALLBACK_VERSION})
    plan=copy.deepcopy(plan);plan['speechReview']=speech['review'];plan['speechCuts']=speech['cuts'];plan['speechRefineVersion']=speech_refine.VERSION
    if speech.get('retainedRestartReview'):plan['retainedRestartReview']=speech['retainedRestartReview']
    if local_scope:
        settings=copy.deepcopy(baseline['settings'])
        if not local_scope['preserveSettings']:settings.update(coverTitle=plan['coverTitle'],coverSubtitle=plan['coverSubtitle'])
    elif preserve_presentation:
        settings=copy.deepcopy(presentation_settings)
    elif preserve_speech:
        settings={**project['settings'],'coverTitle':plan['coverTitle'],'coverSubtitle':plan['coverSubtitle'],'coverTemplate':'classic'}
    else:
        pauses=smart_pauses.detect(record,api,key)['pauses'];saved={r['id']:r for r in project['settings'].get('pacing',{}).get('pauses',[])}
        settings={**project['settings'],'pacing':{**project['settings'].get('pacing',{}),'mode':'tight','sentenceGap':project['settings'].get('pacing',{}).get('sentenceGap',.12),'overrides':{},'pauses':[saved.get(r['id'],r) for r in pauses]},'coverTitle':plan['coverTitle'],'coverSubtitle':plan['coverSubtitle'],'coverTemplate':'classic'}
    tracks=api.music_catalog() if music_allowed else [];tone=plan.get('tone','clear');hint={'warm':'温暖','clear':'沉稳','energetic':'利落'}.get(tone,'沉稳')
    track=next((t for t in tracks if t['id']==settings.get('musicId')),None)
    fixed_settings=bool(preserve_presentation or local_scope and local_scope['preserveSettings'])
    if fixed_settings and settings.get('musicId') and track is None:raise ValueError('要求沿用的配乐暂不可用，未自动替换')
    if track is None and not fixed_settings:track=__import__('music_library').choose(tracks,tone)
    volume=settings.get('musicVolume',.1) if settings.get('musicId') else __import__('music_library').recommended_volume(track)
    if not fixed_settings:settings.update(musicId=track['id'] if track else None,musicVolume=volume if track else 0,musicDucking=True,peakProtection=True)
    # Alignment may alter clip boundaries after planning. Check the actual edit
    # again before paid cover/visual work; never shorten it mechanically.
    # A new uncertain automatic interjection may be restored, but never an old
    # user cut. A failed-edge literal prefix may be held with its original
    # neighboring copy; that is not successful cleanup. The SAME acoustic gate
    # must pass before any visual work; restoration is not a success waiver.
    record,source,project,edited,speech=preflight_calibration_transaction(key,record,source,project,speech_input,edited,speech,settings,plan.get('speechAlignment',{}),calibration_baseline,api)
    plan['speechReview']=speech['review'];plan['speechCuts']=speech['cuts']
    if speech.get('acousticRollback'):plan['speechAcousticRollback']=speech['acousticRollback']
    if speech.get('calibrationRollback'):plan['speechAlignment']={**plan['speechAlignment'],'applied':False,'calibrationRollback':speech['calibrationRollback']}
    # Final word removals/restorations may invalidate an earlier quote. Do not
    # present a pre-cut capability/priority as if it described the kept film.
    selection=__import__('content_selection')
    edited,selection_binding=selection.rebind_rows(edited)
    plan=selection.rebind_plan(plan,edited,selection_binding)
    budget=plan.get('durationBudget')
    if budget and budget.get('target'):
        actual=sum(c['end']-c['start'] for c in api.intervals(edited,source['duration'],settings['pacing'],source['segments']))/settings.get('speed',1)
        checked={**budget,'actualSeconds':round(actual,3),'passed':actual<=budget['target']['maxSeconds']+budget['target']['toleranceSeconds']}
        failure=__import__('editorial_policy').duration_failure(checked)
        if failure:raise ValueError(failure['reason'])
        plan['durationBudget']=checked
    # Fail unsafe sound before paid image/copy work. The renderer still checks
    # the exact same source-bound signature, reusing only an identical receipt.
    # This never trusts a planner's timings or changes the editorial selection.
    import visual_brief
    plan['contentReview']=content_safety.analyze(key,[{'id':s['id'],'text':speech_refine.retained(s)} for s in edited if not s['deleted']],settings,api)
    if not fixed_settings:settings,plan=visual_brief.prepare(key,edited,settings,plan,api)
    folder=api.ROOT/'outputs'/key;folder.mkdir(exist_ok=True);api.save(folder/'project.json',{'sourceId':source['id']})
    # Reuse a matching vision layout from earlier jobs to avoid another model call.
    if 'coverDesign' not in plan:
        for old in sorted(api.JOBS.values(),key=lambda r:r['createdAt'],reverse=True):
            result=old.get('result') or {}
            if result.get('sourceId')==source['id'] and result.get('plan',{}).get('coverDesign'):
                plan=copy.deepcopy(plan);plan['coverDesign']=result['plan']['coverDesign'];break
    api.TASKS.progress(key,'正在保留当前封面' if fixed_settings else '正在选真人封面')
    covers,chosen=__import__('local_edit_scope').fixed_cover(key,record,settings,api) if fixed_settings else automatic_edit.make_covers(key,record,plan,api,settings)
    settings['coverTime']=covers[chosen]['time']
    if preserve_presentation:
        proof={**__import__('dialogue_constraints').require_presentation(presentation_settings,settings),'preservedCover':True,'speechCleanupStillEnabled':not preserve_speech}
        if presentation_rows is not None:proof['visualAnchors']=__import__('dialogue_constraints').require_presentation_rows(presentation_rows,edited)
        api.save(folder/'presentation-preservation.json',proof);plan['presentationPreservation']=proof
    without=api.intervals(edited,source['duration'],{**settings['pacing'],'mode':'original','pauses':[]},source['segments'])
    after=api.intervals(edited,source['duration'],settings['pacing'],source['segments'])
    plan['questionReview']=__import__('content_selection').question_report(plan,after,settings.get('speed',1))
    reduced=max(0,sum(c['end']-c['start'] for c in without)-sum(c['end']-c['start'] for c in after))
    if preserve_speech:
        proof=__import__('speech_preservation').unchanged(baseline,edited,source['id'],preserved_source_id,settings)
        api.save(folder/'speech-preservation.json',proof);plan['speechPreservation']=proof
    if local_scope:
        proof=__import__('local_edit_scope').verify(baseline,edited,settings,local_scope)
        api.save(folder/'local-edit-scope.json',proof);plan['localEditScope']=proof
    result=api.render(key,record,{'sourceId':source['id'],'segments':edited,'settings':settings,'subtitle':settings.get('subtitle','standard'),'musicId':settings['musicId'],'includeCover':True,'coverImage':covers[chosen]['image']},**({'clip_lock':clip_lock} if clip_lock else {}))
    result,edited,speech,plan=hold_encoded_fillers(key,record,source,project,speech_input,edited,speech,settings,plan,result,covers[chosen]['image'],api)
    if preserve_presentation:
        actual_settings=json.loads((api.ROOT/result['project'].lstrip('/')).read_text('utf8'))['settings']
        actual_proof=__import__('dialogue_constraints').require_presentation(presentation_settings,actual_settings)
        proof={**plan['presentationPreservation'],'actualRenderedProject':actual_proof}
        if presentation_rows is not None:
            actual_rows=json.loads((api.ROOT/result['project'].lstrip('/')).read_text('utf8'))['segments']
            proof['actualRenderedVisualAnchors']=__import__('dialogue_constraints').require_presentation_rows(presentation_rows,actual_rows)
        api.save(folder/'presentation-preservation.json',proof);plan['presentationPreservation']=proof
    if local_scope:
        __import__('local_edit_scope').verify(baseline,edited,settings,local_scope)
        plan['localPhysicalScope']=__import__('local_clip_lock').verify_result(key,result,clip_lock,api)
    if plan.get('openingContextPrefix'):
        actual_project=json.loads((folder/'project.json').read_text('utf8'))
        if actual_project.get('sourceId')!=source['id'] or not isinstance(actual_project.get('clips'),list):
            raise ValueError('完整开场组缺少实际成片的取音依据')
        group=__import__('opening_context').group_report(plan,actual_project['clips'],settings.get('speed',1))
        api.save(folder/'opening-group-report.json',group)
        plan['openingGroupReport']=group;result['openingGroupReport']=group
    frame=folder/'visual-check-frame.png'
    api.command(['-ss',str(min(3,result['duration']/2)),'-i',str(api.ROOT/result['video'].lstrip('/')),'-frames:v','1',str(frame)])
    at=min(3,result['duration']/2)
    expected=next((c['text'] for c in result.get('captions',[]) if c['start']<=at<c['end']),'')
    plan['visualReview']=visual_brief.review(key,[folder/'cover.png',frame],edited,settings,api,expected_caption=expected)
    # Review the actual AAC/mixed/concatenated result as well as each source
    # span. A disagreement remains a cue, never an automatic normal-word cut.
    if not result.get('outputAudioAudit'):result['outputAudioAudit']=__import__('final_audio_check').audit(key,key,result,api)
    return {**result,'kind':'editor-auto','jobId':key,'sourceId':source['id'],'source':source,'plan':plan,'covers':covers,'selectedCover':chosen,'segments':edited,'musicName':track['name'] if track else '原声','speechRefinement':speech,'operations':{'deletedSentences':sum(s['deleted'] for s in edited),'removedPauseSeconds':round(reduced,2),'music':bool(track),'singleLineCaptions':True,'coverIntegrated':True,'requestedWordEdits':len(word_edit_receipt['edits']) if word_edit_receipt['applied'] else 0,'shortenedStatements':len(statement_receipt.get('appliedCuts',statement_receipt['cuts'])) if statement_receipt['applied'] else 0,'removedFillers':sum(c['automatic'] and c['kind']=='filler' for c in speech['cuts'])+sum(bool(re.fullmatch('[呃嗯啊额哦]+',''.join(ch for ch in e['quote'] if ch.isalnum()))) for e in word_edit_receipt['edits']),'removedRepetitions':sum(c['automatic'] for c in plan.get('repetitions',[]))+sum(c['automatic'] and c['kind']!='filler' for c in speech['cuts']),'pendingRepetitions':speech_refine.pending_count(edited,[*plan.get('repetitions',[]),*speech['cuts']],speech.get('rejected',[]))+len(result.get('clipCalibration',{}).get('extraRestarts',[]))},'analysisReused':analysis_reused}


def audio_preflight(key,record,source,edited,settings,api):
    import clip_calibration,audio_integrity
    clips=api.intervals(edited,source['duration'],settings.get('pacing'),source['segments'])
    checked,receipt=clip_calibration.calibrate(key,record,clips,{'segments':edited,'settings':settings},api)
    integrity=audio_integrity.check(checked)
    folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True)
    api.save(folder/'audio-preflight.json',{'version':1,'sourceId':source['id'],'calibration':receipt,'integrity':integrity,'beforeVisualWork':True})
    if not integrity['passed']:raise clip_calibration.CalibrationRejected(integrity['blocking'])
    return receipt


def preflight_with_filler_hold(key,record,source,before,edited,speech,settings,api):
    from clip_calibration import CalibrationRejected
    import speech_rollback,speech_refine
    try:
        audio_preflight(key,record,source,edited,settings,api)
        return edited,speech
    except CalibrationRejected as error:
        edges=[edge for issue in error.blocking for edge in issue.get('boundaryEdges',[])]
        restored,cuts,held=speech_rollback.propose(before,edited,speech['cuts'],boundary_edges=edges,source_rows=source.get('segments',[]))
        if not held:raise
        folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True)
        failure={'version':speech_rollback.VERSION,'sourceId':source['id'],'blocking':copy.deepcopy(error.blocking),'held':held}
        path=folder/'clip-calibration.json'
        if path.is_file():failure['originalCalibration']=json.loads(path.read_text('utf8'))
        api.save(folder/'audio-preflight-before-filler-hold.json',failure)
        api.TASKS.progress(key,'正在保留无法安全删去的原话，重新核对全文与声音')
        from content_recipe import bounded_request
        review,usage=bounded_request(speech_refine.REVIEW+'\nrestoredSpeech是本轮自动删除后切口不可靠而完整恢复的原话，原稿自带重说可以保留并标待回听，不能算作新剪出来的重复或已清理。只评估实际仍执行的删除与全文衔接。',{'beforeRows':speech_refine.packet_rows(before),'afterRows':speech_refine.packet_rows(restored),'cuts':[c for c in cuts if c['automatic']],'restoredSpeech':held},api,max_output_tokens=4096,key=key,thinking=settings.get('analysisThinking','disabled'),phase='speech-review-after-acoustic-rollback')
        speech_refine.receipt(api,key,'speech-review-after-acoustic-rollback',usage)
        failure['review']=review;api.save(folder/'speech-acoustic-rollback.json',failure)
        if not speech_refine.validate_review(review):raise error
        # No loop or force-pass. A remaining normal-word/negative/number or
        # boundary mismatch still fails and follows the existing recovery path.
        audio_preflight(key,record,source,restored,settings,api)
        return restored,{**copy.deepcopy(speech),'cuts':cuts,'review':review,'acousticRollback':{'version':speech_rollback.VERSION,'held':held,'review':review,'rechecked':True}}

def preflight_calibration_transaction(key,record,source,project,before,edited,speech,settings,alignment,baseline,api):
    from clip_calibration import CalibrationRejected
    try:
        checked,receipt=preflight_with_filler_hold(key,record,source,before,edited,speech,settings,api)
        return record,source,project,checked,receipt
    except CalibrationRejected as error:
        if baseline is None:raise
        original_record,original_source,original_project=baseline
        rollback=__import__('calibration_transaction').restore(original_project,edited,speech,alignment,error.blocking)
        if rollback is None:raise
        restored,revised,proof=rollback
        folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True)
        path=folder/'clip-calibration.json'
        proof.update(sourceId=source['id'],restoredSourceId=original_source['id'],blocking=copy.deepcopy(error.blocking))
        if path.is_file():proof['originalCalibration']=json.loads(path.read_text('utf8'))
        api.save(folder/'audio-preflight-before-calibration-hold.json',proof)
        api.TASKS.progress(key,'正在恢复原声音边界，保留删不准的词并重新核对')
        import speech_refine
        from content_recipe import bounded_request
        review,usage=bounded_request(speech_refine.REVIEW+'\ncalibrationRollback是本轮校准未通过实际连续段检查后，恢复的原话与原声音边界；不当作去词成功。仅复核实际仍执行的删除与全文衔接。',{'beforeRows':speech_refine.packet_rows(original_project['segments']),'afterRows':speech_refine.packet_rows(restored),'cuts':[c for c in revised['cuts'] if c['automatic']],'calibrationRollback':proof['held']},api,max_output_tokens=4096,key=key,thinking=settings.get('analysisThinking','disabled'),phase='speech-review-after-timing-rollback')
        speech_refine.receipt(api,key,'speech-review-after-timing-rollback',usage)
        proof['review']=review
        if not speech_refine.validate_review(review):
            api.save(folder/'speech-calibration-rollback.json',proof);raise error
        # Same strict physical-span gate, original immutable media and timing.
        # No retries or semantic replanning may turn its failure into a pass.
        try:audio_preflight(key,original_record,original_source,restored,settings,api)
        except CalibrationRejected:
            proof['rechecked']=False;api.save(folder/'speech-calibration-rollback.json',proof);raise
        proof['rechecked']=True;api.save(folder/'speech-calibration-rollback.json',proof)
        revised.update(review=review,calibrationRollback=proof)
        return original_record,original_source,original_project,restored,revised


def hold_encoded_fillers(key,record,source,project,before,edited,speech,settings,plan,result,cover_image,api):
    """Preserve the failed encoded attempt, cancel own cut once, recheck fully."""
    if not any(c.get('automatic') is True and c.get('kind')=='filler' for c in speech.get('cuts',[])):return result,edited,speech,plan
    import encoded_speech_transaction,final_audio_check,speech_refine,content_safety
    folder=api.ROOT/'outputs'/key
    rendered=json.loads((folder/'project.json').read_text('utf8'))
    audit=result.get('outputAudioAudit') or {}
    proposal=encoded_speech_transaction.propose(before,edited,speech,audit,rendered)
    if proposal is None:return result,edited,speech,plan
    # Only the exact media/project audit produced in this invocation is authority.
    _,_,digest,binding=final_audio_check.inputs(key,result,api)
    if audit.get('binding')!=binding or audit.get('mediaSha256')!=digest:raise ValueError('成片声音证据已变化，未自动恢复原词')
    restored,revised,proof=proposal
    archive=folder/'failed-encoded-attempt-0'
    if archive.exists():raise ValueError('本任务已保留一次合成复核失败输出，不重复自动改动；请回听原稿')
    archive.mkdir(exist_ok=False)
    archived=[]
    for file in list(folder.iterdir()):
        if not file.is_file():continue
        # Windows MAX_PATH: long context receipt names fit the output root
        # but may no longer fit one directory deeper. Preserve bytes, map names.
        name=file.name if len(str((archive/file.name).resolve()))<=240 else hashlib.sha256(file.name.encode('utf8')).hexdigest()[:24]+file.suffix
        shutil.copy2(file,archive/name);archived.append({'originalName':file.name,'savedName':name})
    api.save(archive/'archive-files.json',archived)
    api.save(archive/'result.json',result)
    api.TASKS.progress(key,'合成声音仍提示残音，保留原词并重新核对')
    from content_recipe import bounded_request
    review,usage=bounded_request(speech_refine.REVIEW+'\nencodedRollback是本轮自动去词后，实际编码音轨两次局部识别仍提示该语气词，故取消该自动删除并保留原词。不是删音成功，不改正常字或恢复历史手动删字。只核对实际仍执行的删除与完整原话衔接。',
        {'beforeRows':speech_refine.packet_rows(before),'afterRows':speech_refine.packet_rows(restored),'cuts':[c for c in revised['cuts'] if c['automatic']],'encodedRollback':proof['held']},
        api,key=key,phase='speech-review-after-encoded-rollback',max_output_tokens=4096,thinking=settings.get('analysisThinking','disabled'))
    speech_refine.receipt(api,key,'speech-review-after-encoded-rollback',usage)
    if not speech_refine.validate_review(review):raise ValueError('保留原声后的全文复核未通过，已保留成片与失败回执')
    revised.update(review=review,encodedRollback=proof)
    audio_preflight(key,record,source,restored,settings,api)
    selection=__import__('content_selection');restored,selection_binding=selection.rebind_rows(restored);plan=selection.rebind_plan(plan,restored,selection_binding)
    plan=copy.deepcopy(plan);plan.update(speechReview=review,speechCuts=revised['cuts'],encodedSpeechRollback=proof)
    budget=plan.get('durationBudget')
    if budget and budget.get('target'):
        actual=sum(c['end']-c['start'] for c in api.intervals(restored,source['duration'],settings['pacing'],source['segments']))/settings.get('speed',1)
        checked={**budget,'actualSeconds':round(actual,3),'passed':actual<=budget['target']['maxSeconds']+budget['target']['toleranceSeconds']}
        failure=__import__('editorial_policy').duration_failure(checked)
        if failure:raise ValueError(failure['reason'])
        plan['durationBudget']=checked
    plan['contentReview']=content_safety.analyze(key,[{'id':s['id'],'text':speech_refine.retained(s)} for s in restored if not s['deleted']],settings,api)
    # Same cover/layout/settings, no new proposals, source rewrite or re-timing.
    second=api.render(key,record,{'sourceId':source['id'],'segments':restored,'settings':settings,'subtitle':settings.get('subtitle','standard'),'musicId':settings['musicId'],'includeCover':True,'coverImage':cover_image})
    final_draft=json.loads((folder/'project.json').read_text('utf8'))
    if second.get('outputAudioAudit',{}).get('status') not in ('matched','review') or second.get('outputAudioAudit',{}).get('actualEncodedMovie') is not True:raise ValueError('保留原声后的实际成片声音复核未完成，已保留输出，不计清理成功')
    again=encoded_speech_transaction.propose(before,restored,revised,second.get('outputAudioAudit') or {},final_draft)
    if again is not None:raise ValueError('合成后的删词接缝仍需回听，已保留两次实际输出，不继续自动裁音')
    proof.update(rechecked=True,independentReview=review,failedAttempt='failed-encoded-attempt-0',newCutProposals=0)
    api.save(folder/'encoded-speech-rollback.json',proof)
    second['encodedSpeechRollback']=proof
    return second,restored,revised,plan
