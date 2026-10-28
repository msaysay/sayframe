"""Remove contextual fillers from the current draft without re-planning it."""
import copy,re
VERSION=1

def alignment_targets(segments,stale_removed=False):
    targets=[]
    for row in segments:
        if row['deleted'] or row.get('protected'):continue
        text=''.join(w['word'] for i,w in enumerate(row['words']) if i not in row['removed'])
        uncertain=any(w.get('alignmentStable') is False or (w.get('timingEstimated') and 'alignmentGroup' not in w) for w in row['words']) or any(w['end']-w['start']<.02 for w in row['words'] if re.search(r'[呃嗯啊额哦这那]',w['word']))
        removed_estimates=any(i in row['removed'] and w.get('timingEstimated') and 'alignmentGroup' not in w for i,w in enumerate(row['words']))
        old_filler=stale_removed and any(i in row['removed'] and re.fullmatch('[呃嗯啊额哦]+',w['word']) for i,w in enumerate(row['words']))
        if old_filler or removed_estimates or (re.search(r'[呃嗯啊额哦]|这个|那个|就是说|([\u4e00-\u9fff]{1,3})\1',text) and uncertain):
            targets.append(row['id'])
    return targets[:20]

def prepare_timing(key,record,source,project,api):
    import speech_alignment
    versions=speech_alignment.row_versions(record)
    # Context-only upgrades affect interior fillers. Already verified edge
    # cuts retain their unchanged policy, so an unrelated repair cannot move
    # a good cut. Pre-v16 joint-search removals still require revalidation.
    stale=[row for row in project['segments'] if versions.get(row['id'],0)<speech_alignment.required_row_version(row)]
    # Existing removals are a mandatory transaction. Do not combine their
    # version upgrade with speculative cleanup elsewhere in the interview;
    # new proposals have their own joint verification later in the workflow.
    upgrades=[row for row in stale if not row['deleted'] and not row.get('protected') and any(i in row['removed'] and re.fullmatch('[呃嗯啊额哦]+',w['word']) for i,w in enumerate(row['words']))]
    targets=alignment_targets(upgrades,stale_removed=True) if upgrades else alignment_targets(stale)
    if not targets:return record,source,project,{'applied':False,'reason':'当前语气词已有声音范围'}
    updated,p,receipt=speech_alignment.revise(record,project,targets,api,key)
    return updated,api.public_case(updated,True),p,receipt

def run(key,record,payload,api):
    import editor_workflow,speech_refine
    source,project,_,_=editor_workflow.prepare(record,payload,api)
    record,source,project,alignment=prepare_timing(key,record,source,project,api)
    edited,speech=speech_refine.refine(key,source,project['segments'],project['settings'],{},api,scope='fillers')
    pending=speech_refine.acoustic_pending(speech)
    if pending:
        record,source,project,calibrated,speech,alignment=editor_workflow.refine_proposals(key,record,source,project,project['segments'],pending,speech,{},api,refine_scope='fillers')
        if calibrated is not None:edited=calibrated
    before={s['id']:s for s in project['segments']}
    operations={'removedFillers':sum(c['automatic'] and c['kind']=='filler' for c in speech['cuts']),
                'removedRepetitions':sum(c['automatic'] and c['kind']!='filler' for c in speech['cuts']),
                'pending':sum(not c['automatic'] for c in speech['cuts'])}
    result_project={**copy.deepcopy(project),'segments':edited}
    api.PROJECT_LIBRARY.clean_project(result_project,source)
    return {'kind':'speech-cleanup','jobId':key,'sourceId':source['id'],'source':source,'project':result_project,'cuts':speech['cuts'],'speechReview':speech['review'],'speechAlignment':alignment,'operations':operations,'reused':speech['reused']}
