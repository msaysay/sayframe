"""Bound local edits must not silently become a fresh full-draft cleanup.

Only creator conversation grants this scope. The reviewed compilers provide
the exact allowed word indices; neither a model flag nor client times do.
All normal acoustic/render gates remain mandatory.
"""
import copy,re,shutil
VERSION=2


def request(messages):
    scoped=False;visual=False
    for message in messages:
        if message.get('role')!='user':continue
        text=message.get('content','')
        for clause in re.split('[，,。；;\n]',text):
            if re.search(r'(?:如果|比如|例如|假如)|(?:不要|不是|不必|不用|无需)(?:只|仅)',clause):continue
            reset=re.search(r'(?:另剪|换个方向|换一个方向|换主线|重新选主线)|(?:允许|可以|重新)(?:对)?(?:全稿|整稿|全文|整条)(?:自动)?(?:精剪|清理|去语气词)',clause)
            if reset and not re.search(r'(?:不要|不是|不能|不必|不用|无需|别|不允许).{0,3}$',clause[:reset.start()]):
                scoped=False;visual=False;continue
            if re.search(r'(?:可以|允许)(?:重新)?(?:改|换|调整)(?:封面|标题|画面|配乐|音乐|人物介绍)',clause):visual=False
            if re.search(r'(?:不处理|不清理)(?:其他|其它)(?:待定)?(?:弱音|语气词|声音)|(?:其他|其它)(?:待定)?(?:弱音|语气词|声音)不处理|(?:只|仅)(?:做|处理|执行|调整|精简)(?:已确认|指定|这一处|这句|该句|这一句|段内)',clause):scoped=True
            if re.search(r'(?:封面|画面设置|人物介绍|上行标题).{0,65}(?:全部|都|均)(?:保持|不变|沿用)',clause):visual=True
    return {'localOnly':True,'preserveSettings':visual} if scoped else None


def bind(messages,project,plan):
    scope=request(messages)
    if not scope:return None
    # Repetitions are applied before finish(). They must not gain implicit
    # deletion authority from a request restricted to compiled local edits.
    if plan.get('repetitions'):raise ValueError('本轮只执行已确认的段内精简，不能附带全稿重复词清理，请重新规划')
    allowed={}
    for name in ('wordEdits','questionCuts','statementCuts'):
        for cut in plan.get(name,[]):
            sid=cut.get('id');indices=cut.get('indices')
            if not isinstance(sid,str) or not isinstance(indices,list) or any(type(i) is not int for i in indices):raise ValueError('局部修改缺少已复核的原字引用')
            allowed.setdefault(sid,set()).update(indices)
    if scope['preserveSettings'] and any(plan.get(k)!=project['settings'].get(k) for k in ('coverTitle','coverSubtitle')):
        raise ValueError('本轮要求现有画面设置不变，规划不能另写封面文字，请重新分析')
    return {**scope,'version':VERSION,'preserveOrder':bool(__import__('dialogue_constraints').explicit(messages).get('order')),
            'allowed':{sid:sorted(indices) for sid,indices in allowed.items()}}


def rule(messages):
    scope=request(messages)
    if not scope:return ''
    return '\n本轮仅执行已确认的段内修改：所有删字须落到wordEdits、questionEdits或statementEdits真实原字方案，不能附带repetitions或其它整稿清理。未确定切点的原声保留，不承诺已去净。'+('创作者要求原画面设置全部沿用：封面两字段必须逐字等于当前settings，执行不重新选帧、配乐或修改展示。' if scope['preserveSettings'] else '')


def verify(before,after,settings,scope):
    refs={r['id']:r for r in before['segments']}
    if len(after)!=len(refs) or {r['id'] for r in after}!=set(refs):raise ValueError('局部执行改变了原句集合，未采用')
    if any(r.get('deleted')!=refs[r['id']].get('deleted') for r in after):raise ValueError('段内修改改变了整句保留状态，未采用')
    if scope.get('preserveOrder') and [r['id'] for r in before['segments'] if not r['deleted']]!=[r['id'] for r in after if not r['deleted']]:
        raise ValueError('局部执行改变了要求保留的成片顺序，未采用')
    allowed=scope['allowed'];actual=[]
    for row in after:
        old=refs[row['id']];wanted=set(old['removed'])|set(allowed.get(row['id'],[]))
        if ([w['word'] for w in row['words']]!=[w['word'] for w in old['words']] or set(row['removed'])!=wanted
            or any(row.get(k)!=old.get(k) for k in ('wordCorrections','caption','protected','protectedIndices'))):
            raise ValueError('局部执行改变了非目标原字或旧删字，未采用')
        if row['id'] not in allowed:
            keys=set(old)|set(row)
            ignored=__import__('speech_preservation').EDITORIAL|{'text'}
            if any(row.get(k)!=old.get(k) for k in keys-ignored):raise ValueError('局部执行改变了其他句子的声音边界，未采用')
        if allowed.get(row['id']):actual.append({'id':row['id'],'indices':allowed[row['id']]})
    for k,default in [('pacing',{}),('speed',1)]:
        if settings.get(k,default)!=before['settings'].get(k,default):raise ValueError('局部执行改变了全稿气口或倍速，未采用')
    if scope['preserveSettings'] and settings!=before['settings']:raise ValueError('局部执行改变了要求沿用的画面或声音设置，未采用')
    return {'version':VERSION,'passed':True,'allowed':copy.deepcopy(allowed),'executed':actual,'skippedGlobalCleanup':True,
            'preservedSettings':scope['preserveSettings'],'cleanupVerified':False,'originalAcousticGatesRequired':True}


def fixed_cover(key,record,settings,api):
    """Normal exporter owns validation/rendering; never sample a new frame."""
    folder=api.ROOT/'outputs'/key
    path=__import__('editor_export').cover_image(folder,record,{'settings':settings},api)
    dest=folder/'cover-0.png';shutil.copyfile(path,dest)
    return [{'image':f'/outputs/{key}/cover-0.png','frame':f'/outputs/{key}/cover-0.png','time':settings['coverTime'],'preservedFrame':True}],0
