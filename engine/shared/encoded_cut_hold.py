"""An explicit user action can retain a source-bound uncertain filler.

Never treats ASR as deletion authority. No guessed cutting times, old movie
changes, row restores, normal-word edits or automatic restoration of user cuts.
"""
import copy,json,re,uuid
import final_audio_check,final_seams
VERSION=1


def candidate(audit,index,rendered):
    if (not isinstance(audit,dict) or audit.get('actualEncodedMovie') is not True
        or audit.get('status')!='review' or type(index) is not int
        or not 0<=index<len(audit.get('differences',[]))):raise ValueError('这处声音检查已变化，请重新打开当前成片')
    local=audit.get('localSeams') or {}
    if local.get('status')!='checked' or local.get('actualEncodedMovie') is not True:raise ValueError('这处尚无实际成片的局部声音检查')
    issue=audit['differences'][index];evidence=issue.get('localEvidence') or {};target=evidence.get('target')
    if (issue.get('evidenceKind') not in ('encoded-local-seam','full-and-local-seam') or issue.get('expected')!=''
        or not isinstance(target,dict) or not re.fullmatch('[呃嗯啊额哦]+',issue.get('recognized',''))
        or target not in final_seams.targets(rendered)
        or not re.fullmatch('[呃嗯啊额哦]+',target.get('quote',''))
        or issue['recognized'] not in target.get('quote','')):raise ValueError('这里只能保留已标删且局部待核对的语气词，不能据此改正常字')
    windows=evidence.get('windows',[])
    if len(windows)!=2 or windows[0].get('window')==windows[1].get('window'):raise ValueError('局部声音证据不足')
    # Cached recognition is bound to the exact encoded media by cached(). Keep
    # the original two-window criteria rather than accepting client targets.
    def hits(window):
        return [h for h in window.get('hits',[]) if h.get('text')==issue['recognized']
                and type(h.get('time')) in (int,float) and abs(h['time']-target['nearSeconds'])<=.4
                and type(h.get('probability')) in (int,float) and h['probability']>=.35]
    if not any(abs(a['time']-b['time'])<=.12 for a in hits(windows[0]) for b in hits(windows[1])):raise ValueError('两次局部声音证据未对应同一接缝')
    return copy.deepcopy(target)


def run(payload,api):
    owner,movie=final_audio_check.completed(payload.get('video'),api)
    audit=final_audio_check.cached(owner,movie,api)
    if not audit or audit.get('binding')!=payload.get('auditBinding'):raise ValueError('声音检查与当前成片不一致，请重新打开后再操作')
    _,path=final_audio_check.paths(owner,movie,api);rendered=json.loads(path.read_text('utf8'))
    target=candidate(audit,payload.get('cueIndex'),rendered)
    source=api.public_case(api.get_case(rendered['sourceId']),True)
    expected=api.PROJECT_LIBRARY.clean_project(rendered,source)
    current=api.PROJECT_LIBRARY.clean_project({'version':1,'sourceId':payload.get('sourceId'),'segments':payload.get('segments'),'settings':payload.get('settings',{})},source)
    if current!=expected:raise ValueError('文稿或设置已变化，请先生成当前成片，再处理这处声音')
    project=copy.deepcopy(current);row=next((r for r in project['segments'] if r['id']==target['id']),None);indices=target['indices']
    if (not row or row['deleted'] or not set(indices)<=set(row['removed'])
        or final_seams.plain(''.join(row['words'][i]['word'] for i in indices))!=target['quote']):raise ValueError('对应原词已变化，未恢复任何内容')
    row['removed']=[i for i in row['removed'] if i not in indices]
    row['protectedIndices']=sorted(set(row.get('protectedIndices',[]))|set(indices))
    project=api.PROJECT_LIBRARY.clean_project(project,source)
    receipt={'version':VERSION,'ownerJobId':owner,'auditBinding':audit['binding'],'mediaSha256':audit['mediaSha256'],
             'id':target['id'],'indices':indices,'quote':target['quote'],'authority':'explicit-user-retain-audited-filler',
             'oldMovieUnchanged':True,'requiresRender':True,'reason':'这处删音尚不可靠，按你的操作保留原词与原声；不计为清理成功'}
    api.save(api.ROOT/'outputs'/owner/('held-filler-'+uuid.uuid4().hex+'.json'),receipt)
    return {'project':project,'receipt':receipt}
