"""Immutable timing revisions using the exact cloud text and existing local model.

Chinese multi-character tokens retain an acoustic group: sub-character times are
display estimates, never independent automatic cutting anchors.
"""
import copy,hashlib,json,re
from pathlib import Path
VERSION=24
PUBLICATION_VERSION=1
INTERIOR_CONTEXT_VERSION=18
# Neighbor/edge calibration has not changed since v16. A context-only
# improvement must not invalidate successful cuts in an unrelated group.
NEIGHBOR_POLICY_VERSION=16

def proposal_transaction_matches(base_project,edited,pending,alignment):
    """A joint calibration cannot be committed with a different cut mask.

    Conservative all-or-nothing timing transaction. If semantic review holds
    any probed proposal, callers keep the original calibration and re-guard.
    """
    rows={r['id']:r for r in edited};base={r['id']:r for r in base_project['segments']};changed=set(alignment.get('rows',[]));held=[]
    expected={sid:set(base[sid].get('removed',[])) for sid in changed if sid in base}
    for cut in pending:
        if cut['id'] in expected:
            if alignment.get('verifiedCutMasksVersion')==1:
                sid=cut['id'];spoken_indices={i for i in cut['indices'] if any(c.isalnum() for c in base[sid]['words'][i]['word'])}
                if not spoken_indices.issubset(set(alignment.get('verifiedCutMasks',{}).get(sid,[]))):continue
            expected[cut['id']].update(cut['indices'])
    for sid in changed:
        row=rows.get(sid);original=base.get(sid)
        if row is None or original is None or row.get('deleted')!=original.get('deleted') or [w['word'] for w in row['words']]!=[w['word'] for w in original['words']]:
            held.append({'id':sid,'reason':'校准后原话或整句状态变化'});continue
        spoken={i for i,w in enumerate(row['words']) if any(c.isalnum() for c in w['word'])}
        wanted=expected[sid]&spoken;actual=set(row.get('removed',[]))&spoken
        if wanted!=actual:held.append({'id':sid,'missing':sorted(wanted-actual),'extra':sorted(actual-wanted)})
    return {'passed':not held,'held':held,'version':1}

def row_versions(record):
    """A partial revision upgrades only the rows it actually replaced."""
    revision=record.get('alignmentRevision',{})
    versions=dict(revision.get('rowVersions',{}))
    for sid in revision.get('rows',[]):versions[sid]=max(versions.get(sid,0),revision.get('version',0))
    return versions

def verify_proposals(record,project,cuts,api,key=None):
    """Audit the proposed removal, not an unrelated guessed filler.

    This is a timing probe only. Restore the user's original removal state
    before the caller reruns all sound guards and independent text review.
    """
    import repeated_takes
    probe=copy.deepcopy(project);rows={r['id']:r for r in probe['segments']}
    targets=[];proposed_fillers=[]
    for cut in repeated_takes.validate(cuts,probe['segments']):
        row=rows[cut['id']]
        if row['deleted'] or row.get('protected') or set(cut['indices'])&set(row.get('protectedIndices',[])):continue
        removed=set(row['removed'])|set(cut['indices'])
        if not any(i not in removed and any(c.isalnum() for c in w['word']) for i,w in enumerate(row['words'])):continue
        row['removed']=sorted(removed);targets.append(row['id'])
        if cut.get('kind')=='filler' and __import__('audio_delta').spoken(cut['quote']) in __import__('audio_delta').PROPOSED_DISCOURSE_FILLERS:
            proposed_fillers.append({k:copy.deepcopy(cut[k]) for k in ('id','indices','quote')})
    if not targets:return record,project,{'applied':False,'reason':'没有可校准的保留句删词建议'}
    revised,calibrated,receipt=revise(record,probe,sorted(set(targets)),api,key,base_removed={r['id']:r['removed'] for r in project['segments']},**({'proposed_fillers':proposed_fillers} if proposed_fillers else {}))
    original={r['id']:r for r in project['segments']}
    for row in calibrated['segments']:
        row['removed']=copy.deepcopy(original[row['id']]['removed'])
        row['deleted']=original[row['id']]['deleted']
    return revised,calibrated,receipt

def aligned_chars(row,groups,second,third=None):
    if ''.join(g['word'] for g in groups)!=row['text'] or [g['word'] for g in groups]!=[g['word'] for g in second]:return None
    peers=[second]
    if third and [g['word'] for g in third]==[g['word'] for g in groups]:peers.append(third)
    out=[]
    for n,(a,b) in enumerate(zip(groups,second)):
        lo=max(row['start'],min(row['end'],a['start']));hi=max(lo,min(row['end'],a['end']))
        # The first token of a cropped window often absorbs leading silence.
        # It cannot place a cut into the previous sentence.
        consensus=[p[n] for p in peers if abs(a['end']-p[n]['end'])<=.08 and (n==0 or abs(a['start']-p[n]['start'])<=.08)]
        stable=bool(consensus)
        for i,ch in enumerate(a['word']):
            out.append({'word':ch,'start':lo+(hi-lo)*i/len(a['word']),'end':lo+(hi-lo)*(i+1)/len(a['word']),'probability':a['probability'],'timingEstimated':True,'alignmentGroup':str(n),'alignmentStable':stable,'alignmentProbability':a['probability']})
    if [w['word'] for w in out]!=[w['word'] for w in row['words']]:return None
    return out

def interior_filler_context(source_row,edit):
    """An interior filler can audition its own full sentence, never less.

    This selects recognition context, not a deletion or a trusted boundary.
    Both original windows, mandatory old cuts and the exact retained-audio
    audit still apply. Edge cuts and ordinary-word restarts need neighbors.
    """
    words=source_row['words'];removed=set(edit.get('removed',[]))
    if edit.get('deleted') or not removed:return False
    if [w['word'] for w in words]!=[w['word'] for w in edit['words']]:return False
    if any(type(i) is not int or i<0 or i>=len(words) for i in removed):return False
    filler=lambda word:bool(re.fullmatch('[呃嗯啊额哦]+',word))
    if any(not filler(words[i]['word']) for i in removed):return False
    spoken=[i for i,w in enumerate(words) if any(c.isalnum() for c in w['word'])]
    for n,i in enumerate(spoken):
        if i not in removed:continue
        # Ignore punctuation, but do not hop over another cut/filler in order
        # to manufacture a pair of normal retained flank words.
        if n and spoken[n-1] in removed:continue
        last=n
        while last+1<len(spoken) and spoken[last+1] in removed:last+=1
        left=spoken[max(0,n-2):n];right=spoken[last+1:last+3]
        if len(left)!=2 or len(right)!=2:return False
        if any(j in removed or filler(words[j]['word']) for j in left+right):return False
    return True

def required_row_version(row):
    return INTERIOR_CONTEXT_VERSION if interior_filler_context(row,row) else NEIGHBOR_POLICY_VERSION

def context_groups(source,project,ids):
    """Check real adjacent retained speech on both sides of every word cut.

    These neighbors provide recognition context, never extra deletion ranges.
    Reordered or unselected neighbors must not be auditioned as continuous audio.
    """
    wanted=set(ids);source_rows=source['segments'];edits={r['id']:r for r in project['segments']};kept=[r['id'] for r in project['segments'] if not r['deleted']];groups=[]
    # A multiword restart needs its complete local witness. Do not make its
    # two peaks disappear in a transitive window built from nearby fillers.
    # Membership stays disjoint; every cut within a group is still jointly
    # auditioned, and the final composition keeps the ordinary output guards.
    def priority(item):
        n,row=item;edit=edits.get(row['id'],{});removed=edit.get('removed',[])
        return (-sum(any(c.isalnum() for c in row['words'][i]['word']) for i in removed if type(i) is int and 0<=i<len(row['words'])),n)
    for n,row in sorted(enumerate(source_rows),key=priority):
        if row['id'] not in wanted or row['id'] not in kept:continue
        # A requested cut already in a joint audition does not need another
        # layer of context. Expanding it again creates a transitive window of
        # unrelated sentences and changes the acoustic anchors unnecessarily.
        if any(row['id'] in g for g in groups):continue
        if interior_filler_context(row,edits[row['id']]):continue
        occupied={sid for g in groups for sid in g};k=kept.index(row['id']);group=[row['id']]
        previous=source_rows[n-1] if n else None
        if previous and previous['id'] not in occupied and k and kept[k-1]==previous['id'] and row['end']-previous['start']<=25 and row['start']-previous['end']<=1:group.insert(0,previous['id'])
        following=source_rows[n+1] if n+1<len(source_rows) else None
        first=source_rows[n-1] if len(group)>1 else row
        if following and following['id'] not in occupied and k+1<len(kept) and kept[k+1]==following['id'] and following['end']-first['start']<=25 and following['start']-row['end']<=1:group.append(following['id'])
        if len(group)<2:continue
        touching=[g for g in groups if set(g)&set(group)]
        merged={*group,*(v for g in touching for v in g)}
        ordered=[r for r in source_rows if r['id'] in merged]
        if ordered[-1]['end']-ordered[0]['start']>25:continue
        groups=[g for g in groups if g not in touching]+[[r['id'] for r in ordered]]
    expanded=sorted(wanted|{v for g in groups for v in g})
    return expanded,groups

def complete_original_units(source,project,ids,groups,target_ids):
    """Complete existing retained ASR units for a proposed discourse filler.

    Provenance only, not speaker/semantic evidence. Do not cross unselected or
    reordered speech, invent members, replace successful old cuts or exceed
    the existing 25-second worker limit. Expansion does not authorize a cut.
    """
    refs={r['id']:r for r in source['segments']};order=[r['id'] for r in source['segments']]
    kept=[r['id'] for r in project['segments'] if not r['deleted']];wanted=set(ids);used={sid for g in groups for sid in g}
    original=[list(g) for g in groups]+[[sid] for sid in ids if sid not in used];result=[]
    def legal(values):
        if not values or any(sid not in refs or sid not in kept for sid in values):return False
        a,b=order.index(values[0]),order.index(values[-1]);c,d=kept.index(values[0]),kept.index(values[-1])
        return order[a:b+1]==values==kept[c:d+1] and refs[values[-1]]['end']-refs[values[0]]['start']<=25
    for group in original:
        members=set(group)
        if members&set(target_ids):
            for sid in group:
                unit=refs[sid].get('sourceUnit',{});unit_ids=unit.get('members',[])
                if unit.get('origin')!='original-asr-unit' or not isinstance(unit.get('id'),str) or not isinstance(unit_ids,list) or not unit_ids or any(not isinstance(k,str) for k in unit_ids):continue
                if len(set(unit_ids))!=len(unit_ids) or sid not in unit_ids or not legal(unit_ids):continue
                if any(refs[k].get('sourceUnit',{}).get('id')!=unit['id'] or refs[k].get('sourceUnit',{}).get('members')!=unit_ids for k in unit_ids):continue
                members.update(unit_ids)
        expanded=[sid for sid in order if sid in members]
        if not legal(expanded):expanded=group
        touching=[g for g in result if set(g)&set(expanded)]
        if touching:
            union={*expanded,*(sid for g in touching for sid in g)};merged=[sid for sid in order if sid in union]
            if not legal(merged):return ids,groups
            result=[g for g in result if g not in touching];expanded=merged
        result.append(expanded)
    final_groups=[g for g in result if len(g)>1]
    return sorted(wanted|{sid for g in final_groups for sid in g}),final_groups


def publication(replacements,requested,binding,targets_only):
    if not targets_only:return replacements,binding,{}
    if not requested or not set(requested)<=set(replacements):raise ValueError('局部校准缺少目标句的声音证据，未发布')
    selected={sid:copy.deepcopy(words) for sid,words in replacements.items() if sid in requested}
    proof={'version':PUBLICATION_VERSION,'publishedTargets':sorted(selected),'auditedContextOnly':sorted(set(replacements)-set(selected))}
    # Calibration input/evidence is unchanged. A different immutable source
    # publication must own a different ID, without rerunning or falsifying it.
    digest=hashlib.sha256(json.dumps({'calibrationBinding':binding,'publication':proof},sort_keys=True).encode()).hexdigest()
    return selected,digest,proof


def revise(record,project,ids,api,key=None,base_removed=None,proposed_fillers=(),reviewed_excerpts=(),publish_targets_only=False):
    requested=set(ids)
    source=api.public_case(record,True)
    ids,groups=context_groups(source,project,ids);rows=[r for r in source['segments'] if r['id'] in ids]
    if proposed_fillers:
        ids,groups=complete_original_units(source,project,ids,groups,{c['id'] for c in proposed_fillers})
        rows=[r for r in source['segments'] if r['id'] in ids]
    if not rows or any(r['end']-r['start']>25 for r in rows):return record,project,{'applied':False,'reason':'声音窗口太长或无待校准句'}
    signature={'sourceId':source['id'],'ids':ids,'contextGroups':groups,'version':VERSION,'removed':[(r['id'],r['removed']) for r in project['segments'] if r['id'] in ids],'edges':project.get('settings',{}).get('pacing',{}).get('edges',{})}
    if base_removed is not None:signature['baseRemoved']={sid:base_removed.get(sid,[]) for sid in ids}
    if proposed_fillers:signature['proposedFillers']=proposed_fillers
    if reviewed_excerpts:signature['reviewedExcerpts']={'version':__import__('statement_edits').VERSION,'cuts':reviewed_excerpts}
    binding=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    path=api.ROOT/'recognition-cache'/('speech-alignment-v1-'+binding+'.json')
    if path.is_file():calibrated=json.loads(path.read_text('utf8'))
    else:
        import sys,uuid
        precise_python=api.ROOT.parent/'research/tools/sensevoice-python/Scripts/python.exe'
        precise_model=Path.home()/'.cache/sayframe-asr/sensevoice-2024'
        site=precise_python.parent.parent/'Lib/site-packages'
        precise=precise_python.is_file() and (precise_model/'model.int8.onnx').is_file() and all((site/package/'__init__.py').is_file() for package in ('onnxruntime','kaldi_native_fbank'))
        model=next((p for p in (api.ROOT.parent/'research/models/models--Systran--faster-whisper-small/snapshots').glob('*') if (p/'model.bin').is_file()),None)
        if not precise and model is None:return record,project,{'applied':False,'reason':'本地声音校准模型未准备好'}
        request=api.ROOT/'recognition-cache'/('alignment-request-'+uuid.uuid4().hex+'.json')
        api.save(request,{'sourceId':source['id'],'ids':ids,'contextGroups':groups,'source':source,'segments':project['segments'],'video':record['video_path'],'ffmpeg':str(api.FFMPEG),'model':str(precise_model) if precise else str(model),'cutAudioReviewVersion':__import__('cut_audio_review').VERSION,**({'baseRemoved':signature['baseRemoved']} if base_removed is not None else {}),**({'proposedFillers':proposed_fillers} if proposed_fillers else {}),**({'reviewedExcerpts':reviewed_excerpts} if reviewed_excerpts else {})})
        try:
            if key:api.TASKS.progress(key,'正在校准重说的声音位置')
            calibrated=json.loads(api.TASKS.process([str(precise_python) if precise else sys.executable,'-X','utf8',str(api.ROOT/('precise_speech_worker.py' if precise else 'speech_alignment_worker.py')),str(request)],cwd=api.ROOT,timeout=360))
        finally:request.unlink(missing_ok=True)
        api.save(path,calibrated)
    replacements={}
    for entry in calibrated.get('entries',[]) if isinstance(calibrated,dict) else calibrated:
        row=next(r for r in rows if r['id']==entry['id']);words=entry.get('words') if isinstance(calibrated,dict) and entry.get('applied') else None
        if not isinstance(calibrated,dict):words=aligned_chars(row,entry['context'],entry['single'],entry.get('surrounding'))
        if words is not None and [w['word'] for w in words]!=[w['word'] for w in row['words']]:raise ValueError('声音校准改变了原词，未应用')
        if words is not None:
            # Keep user-owned explicit cut points legal after the immutable
            # timing revision. Punctuation follows its preceding real word.
            import re
            for edge_key,edge in project.get('settings',{}).get('pacing',{}).get('edges',{}).items():
                match=re.fullmatch(r'(.+):(\d+):(\d+)',edge_key)
                if not match or match[1]!=row['id']:continue
                first,last=int(match[2]),int(match[3])
                if 'start' in edge and edge['start']>words[first]['start']:words[first]['start']=edge['start']
                if 'end' in edge and edge['end']<words[last]['end']:
                    words[last]['end']=edge['end']
                    if not any(c.isalnum() for c in words[last]['word']):
                        words[last]['start']=edge['end']
                        previous=next((i for i in range(last-1,-1,-1) if any(c.isalnum() for c in words[i]['word'])),None)
                        if previous is not None:words[previous]['end']=min(words[previous]['end'],edge['end'])
            if any(w['end']<w['start'] for w in words):words=None
        if words is not None:replacements[row['id']]=words
    if not replacements:return record,project,{'applied':False,'reason':'原字或声音组无法一致对齐','receipt':path.name}
    replacements,publication_binding,publication_proof=publication(replacements,requested,binding,publish_targets_only)
    verified_masks={e['id']:e.get('verifiedCutMasks',[]) for e in calibrated.get('entries',[]) if e['id'] in replacements and e.get('applied')} if isinstance(calibrated,dict) and calibrated.get('verifiedCutMasksVersion')==1 else None
    new=copy.deepcopy(record);flat=[w for r in source['segments'] for w in replacements.get(r['id'],r['words'])];at=0
    for block in new['segments']:
        count=len(block['words']);block['words']=copy.deepcopy(flat[at:at+count]);at+=count
        block['start']=block['words'][0]['start'];block['end']=block['words'][-1]['end']
    assert at==len(flat)
    versions=row_versions(record);versions.update({sid:VERSION for sid in replacements})
    rid='import-aligned-v1-'+publication_binding[:24];new['video_id']=rid;new['original_source_id']=source['id'];new['alignmentRevision']={'version':VERSION,'rows':list(replacements),'rowVersions':versions,'receipt':path.name,'partial':True,**({'publication':publication_proof} if publication_proof else {}),'method':calibrated.get('method') if isinstance(calibrated,dict) else 'Whisper exact-text attention alignment; left/single/surrounding boundary consensus'}
    # get_case resolves stored relative paths; keep them portable in the new file.
    from media_paths import portable_path
    for k in ('video_path','audio_path'):
        if new.get(k):new[k]=portable_path(new[k],api.ROOT.parent)
    target=api.ROOT/'data'/(rid+'.json')
    if not target.is_file():api.save(target,new)
    new_record=api.get_case(rid);new_source=api.public_case(new_record,True)
    assert [(r['id'],r['text']) for r in new_source['segments']]==[(r['id'],r['text']) for r in source['segments']]
    p=copy.deepcopy(project);p['sourceId']=rid;refs={r['id']:r for r in new_source['segments']}
    for row in p['segments']:
        row['words']=copy.deepcopy(refs[row['id']]['words']);row['start']=refs[row['id']]['start'];row['end']=refs[row['id']]['end']
    p=api.PROJECT_LIBRARY.clean_project(p,new_source)
    return new_record,p,{'applied':True,'sourceId':rid,'parentSourceId':source['id'],'rows':list(replacements),'receipt':path.name,'partial':True,**({'verifiedCutMasksVersion':1,'verifiedCutMasks':verified_masks} if verified_masks is not None else {}),**({'publication':publication_proof} if publication_proof else {})}
