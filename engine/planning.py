"""Source-bound direction proposals and reversible one-click application.

The host supplies semantic judgement. Validators prove reference/sequence
integrity, not whether an anecdote proves a claim or whether a film is good.
"""
import copy,re,uuid
from pathlib import Path
import danjie_methodology

ROLES={'opening','support','ability','audience','ending','story','bridge'}

def text(agent,value,label,limit=600):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:raise agent.UserError(label+'需要简短且有内容。')
    return value.strip()

def validate(agent,data,source):
    if not isinstance(data,dict) or set(data)!={'catalogVersion','sourceSha256','directions'} or data['catalogVersion']!=danjie_methodology.VERSION or data['sourceSha256']!=source['mediaSha256']:raise agent.UserError('方案没有绑定当前素材与方法论版本。')
    directions=data['directions'];methods={m['id']:m for m in danjie_methodology.catalog()['methods']};refs=agent.source_rows(source)
    if not isinstance(directions,list) or not 1<=len(directions)<=6:raise agent.UserError('请提出1–6个素材确实可剪的方向，不强凑数量。')
    seen=set();result=[]
    for raw in directions:
        fields={'id','title','audience','goal','methods','why','order','beats','evidence','gaps','review'}
        if not isinstance(raw,dict) or set(raw)!=fields:raise agent.UserError('方向字段不完整，不能用时间配方或自由文稿代替原片引用。')
        d=copy.deepcopy(raw);did=d['id']
        if not isinstance(did,str) or not re.fullmatch('[a-z][a-z0-9-]{0,39}',did) or did in seen:raise agent.UserError('方向编号无效或重复。')
        seen.add(did)
        for key,limit in [('title',48),('audience',160),('goal',160),('why',800)]:d[key]=text(agent,d[key],key,limit)
        selected=d['methods']
        if not isinstance(selected,list) or not selected or len(selected)!=len(set(selected)) or any(mid not in methods for mid in selected):raise agent.UserError('方案须使用目录中实际存在的方法，不能发明名称。')
        order=d['order']
        if not isinstance(order,list) or not order or len(order)>500 or any(not isinstance(sid,str) or sid not in refs for sid in order) or len(order)!=len(set(order)):raise agent.UserError('方向含未知、重复或缺少的原句。')
        evidence=d['evidence']
        if not isinstance(evidence,list) or any(not isinstance(e,dict) or set(e)!={'id','quote'} or e['id'] not in order or e['quote']!=refs[e['id']]['text'] for e in evidence) or len(evidence)!=len(order) or {e['id'] for e in evidence}!=set(order):raise agent.UserError('每个保留原句都须绑定完整原话，不能截掉条件或借教学示例。')
        if not isinstance(d['beats'],list) or not d['beats']:raise agent.UserError('请说明开场、中段与结尾实际用了哪些原话。')
        assigned=set();opening=[]
        for beat in d['beats']:
            if not isinstance(beat,dict) or set(beat)!={'role','ids','reason'} or beat['role'] not in ROLES:raise agent.UserError('段落角色无效。')
            ids=beat['ids']
            if not isinstance(ids,list) or not ids or any(sid not in order for sid in ids) or len(ids)!=len(set(ids)):raise agent.UserError('段落引用必须属于该方向的保留原话。')
            if [sid for sid in order if sid in ids]!=ids:raise agent.UserError('段落中的原句顺序与成片不一致。')
            text(agent,beat['reason'],'段落理由',500);assigned.update(ids)
            if beat['role']=='opening':opening+=ids
        if assigned!=set(order) or not opening or opening!=order[:len(opening)]:raise agent.UserError('开场必须在成片开头，所有保留内容都须说明作用。')
        if not isinstance(d['gaps'],list) or len(d['gaps'])>12 or any(not isinstance(g,str) or not g.strip() or len(g)>500 for g in d['gaps']):raise agent.UserError('素材缺口格式不正确。')
        if not isinstance(d['review'],dict) or set(d['review'])!={'opening','support','ability','ending'}:raise agent.UserError('请复核开场、支撑、绝活与结尾，缺少的环节如实说明。')
        for value in d['review'].values():text(agent,value,'方法复核',600)
        d['estimatedSeconds']=round(sum(refs[sid]['end']-refs[sid]['start'] for sid in order),2)
        d['openingSeconds']=round(sum(refs[sid]['end']-refs[sid]['start'] for sid in opening),2)
        d['warnings']=['开场超过三秒优先目标；保留完整原话，必要时重新选组，不自动截断或加速。'] if d['openingSeconds']>3 else []
        d['methodNames']=[methods[mid]['name'] for mid in selected]
        result.append(d)
    # Different titles alone do not make different cuts. Partial overlap is
    # allowed when the same genuine supporting evidence serves two questions.
    if len({tuple(d['order']) for d in result})!=len(result):raise agent.UserError('多个方向使用了完全相同的内容顺序，请合并或另找有不同答案的方向。')
    return result

def propose(agent,project,file,expect):
    p,doc,source=agent.load_project(project)
    with agent.lock(p):
        doc=agent.read(p/'sayframe-project.json')
        if agent.revision(doc)!=expect:raise agent.UserError('稿件已变，请读取当前稿后重新规划。')
        rows=validate(agent,agent.read(file),source)
        plan={'version':1,'id':uuid.uuid4().hex,'catalogVersion':danjie_methodology.VERSION,'sourceSha256':source['mediaSha256'],'sourceSignature':doc['sourceSignature'],'baseRevision':expect,'directions':rows,'verification':'引用与结构已校验；语义为宿主自检，未声称独立审查或成片验收。'}
        target=p/'plans'/(plan['id']+'.json');agent.atomic(target,plan)
        agent.atomic(p/'planning.json',{'id':plan['id'],'sha256':agent.digest(target)})
        return {'status':'directions-ready','plan':plan['id'],'revision':expect,'directions':rows,'notice':plan['verification']}

def active(agent,p,doc):
    pointer=p/'planning.json'
    if not pointer.is_file():return None
    binding=agent.read(pointer);pid=binding.get('id','')
    if not isinstance(pid,str) or not re.fullmatch('[a-f0-9]{32}',pid):raise agent.UserError('方案引用无效。')
    file=p/'plans'/(pid+'.json')
    if agent.digest(file)!=binding.get('sha256'):raise agent.UserError('保存的剪辑方案已被修改，请重新规划。')
    plan=agent.read(file)
    if plan['sourceSignature']!=doc['sourceSignature']:raise agent.UserError('方案与原片文稿不一致。')
    return plan

def selected_changes(agent,p,doc,selection):
    if not isinstance(selection,dict) or set(selection)!={'plan','direction','confirmed','captionsEnabled','titleEnabled'}:raise agent.UserError('请先确认具体方向，并分别选择字幕和标题是否添加。')
    if selection['confirmed'] is not True or any(type(selection[k])!=bool for k in ('captionsEnabled','titleEnabled')):raise agent.UserError('方向须由用户确认，字幕和标题可分别开启或关闭。')
    plan=active(agent,p,doc)
    if not plan or plan['id']!=selection['plan'] or plan['catalogVersion']!=danjie_methodology.VERSION:raise agent.UserError('该方案不再是当前有效方案，请重新查看。')
    old=agent.current(doc).get('methodology',{})
    # A different direction may be selected from the same plan after one has
    # been applied. Any subsequent edit requires fresh planning, not overwrite.
    if agent.revision(doc)!=plan['baseRevision'] and not (old.get('plan')==plan['id'] and old.get('status')=='applied'):raise agent.UserError('方案生成后稿件已有修改，请重新规划，不能覆盖较新的调整。')
    d=next((d for d in plan['directions'] if d['id']==selection['direction']),None)
    if not d:raise agent.UserError('未找到该剪辑方向。')
    state=copy.deepcopy(agent.current(doc));state['order']=d['order'];state.pop('cover',None)
    state['settings']['title']=d['title'];state['settings']['framework']=' / '.join(d['methodNames'])[:120]
    state['settings'].update({k:selection[k] for k in ('captionsEnabled','titleEnabled')});state['workflow']={'directionConfirmed':True,'plan':plan['id'],'direction':d['id']}
    state['summary']=d['why'];state['methodology']={'plan':plan['id'],'direction':d['id'],'catalogVersion':plan['catalogVersion'],'status':'applied','title':d['title'],'methods':d['methodNames'],'beats':d['beats'],'gaps':d['gaps'],'review':d['review']}
    return state

def choose(agent,project,pid,did,expect,options=None):
    p,doc,source=agent.load_project(project)
    with agent.lock(p):
        doc=agent.read(p/'sayframe-project.json')
        if agent.revision(doc)!=expect:raise agent.UserError('稿件已变，请重新读取再选择。')
        state=selected_changes(agent,p,doc,{'plan':pid,'direction':did,**(options or {})});agent.commit(p,doc,state)
        return {'status':'direction-applied','revision':agent.revision(doc),'retainedSegments':len(state['order']),'notice':'方案已应用为可撤销草稿；继续export才生成真实电影。'}

def fork(agent,project,dest):
    p,doc,source=agent.load_project(project);target=Path(dest).expanduser().resolve()
    if target.exists():raise agent.UserError('另存目标须为新的工程目录，避免覆盖旧稿。')
    target.mkdir(parents=True)
    state=copy.deepcopy(agent.current(doc));state.pop('cover',None);state.pop('methodology',None)
    agent.atomic(target/'source.json',source)
    cloned={'format':'sayframe-agent','version':agent.VERSION,'sourceSignature':agent.digest(target/'source.json'),'history':[state],'cursor':0,'forkedFrom':str(p)}
    agent.atomic(target/'sayframe-project.json',cloned);agent.atomic(target/'status.json',{'status':'done','stage':'fork','notice':'独立草稿；尚未生成成片。'})
    return {'project':str(target),'revision':agent.revision(cloned),'notice':'已另存独立工程，不复制或改动原视频；旧稿保留。'}
