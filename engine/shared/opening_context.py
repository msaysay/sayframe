"""Source-bound opening assessment, validated independently of speaker identity."""
VERSION=5
RULE='''开场上下文判断：只看成篇语义，不按第几句、问号、说话人或机器人身份决定留问题。回答“第一步就是别学怎么做IP”没有明确场景，独立开场不能说明是什么的第一步；原话有“企业打造IP第一步应该做什么”时保留必要短问句，去掉问句前的招呼、流程说明、编号等冗余时只能使用原词。若开头本身是明确、自洽、有场景的反认知判断，可以直接开场，不必补问题。中间问题只有引出必要主题、指代、条件、转折或转化承接时保留，回答自洽时大部分可删；不能默认保留所有第一问，也不能默认删光提问。每条依赖都需说明删后具体失去什么，未知说话人只描述提问文本和回应，不猜角色。原问题已被用户删除而仍缺上下文时，说明可恢复的原问句，不能偷偷加回或补造台词。'''
SCHEMA='''复核还必须返回openingContext:{mode:"question-answer"|"context-question-answer"|"standalone"|"missing-context"|"uncertain",firstId:实际draftRows第一句ID,questionId:所需原问句ID或null,answerId:对应回应ID或独立开场句ID,reason:说明开场场景是否明确、为何需要或不需要问句}。question-answer的questionId必须是第一句、answerId必须在后续保留稿中；standalone的answerId必须是第一句且questionId=null（反认知问句也可能独立成立）。missing-context/uncertain不能passed=true；issues写实际缺上下文的保留开场句。没有足够证据不能声称自洽。'''
RULE+='''\n优先逐字阅读当前draftRows开场，而不是先找原问句：开场自己已交代主体、场景、判断时，不能因它也提到“第一步”、原片存在相关问题或问题被删而否定独立性。对照例：“第一步就是别学怎么做IP”省略场景，需要具体问句；“企业做IP，第一步不是学方法，而是想清楚自己是谁”已明确主体与场景，应判独立开场，不需要另补问题。反认知问句“为什么说企业落地AI不要全员落地”本身含完整场景与判断，也可以作为独立观点开场；后面有解释不自动把它变成必须依赖别的问题的回答。reason引用当前开场原字说明主体、场景和指代是否完整。必须补齐的是缺失信息，而不是问句这种形式。'''
SCHEMA+='同一原句已包含完整问答、或问句本身承载完整判断时，可按独立开场判standalone；answerId在这里指独立开场句，不据此推断讲话角色。question-answer专指以短信息请求问题引出省略场景的回答，而不是任意问号加后续说明。'
SCHEMA=SCHEMA.replace('question-answer的questionId必须是第一句、answerId必须在后续保留稿中','question-answer的questionId须为实际第一句，或属于从第一句开始完整连续保留的同一个原始提问组的问尾；answerId必须在该提问后保留')
RULE+='\n年份、时间判断、代词和确认词不能代替具体讨论对象。反例：“是的，今年是一个特别重要的时点”尚未说明哪件事，不能仅凭今年和后续解释判为独立完整；应比较原稿中的必要问题或直接含AI/业务对象的完整判断。“那时候它是四十分的小朋友”仍需先交代它是谁。标题里的场景不能冒充声音已经说出。只引用actualDraft实际原话作判断。'
RULE+='''\n冷开场复核：假设观众没有看过完整访谈、标题或方案说明，只顺序听实际保留开头的一组完整表达。先说明它已经交代的对象和问题，再检查“另外一个/也是/刚才/这种做法”等是否依赖未保留的对比项。不能仅因后面能猜出主题、带数字、标签叫支撑或有一个具体人物就判开头完整。例：“另外一个朋友公司也是几个亿的规模”只交代案例背景，尚未说明拿它讨论什么；应比较原稿中的完整判断、对象明确的必要短问题，或保留能自足的完整案例引入组。反例：“另一个办法是用新业务承接空出来的人”自己已说清方法和对象，不能只因有“另一个”就判缺上下文；自足的故事也可从案例开场，不强制观点先行。不以单个连接词自动删句或恢复整场提问。reason必须对照实际开头原字说明缺的具体信息；开场清楚但吸引力偏弱时如实区分，不把审美偏好说成丢失原话。'''
SCHEMA+='''\n另支持mode="context-question-answer"：仅用于实际开头先连续交代必要对象/情境，再问短问题，紧接回答。firstId仍须实际第一句；questionId必须在开头背景之后，answerId必须是该问题后实际紧邻的一句；reason逐字引用实际背景及问题，说明为何这组能独立成立。工具将绑定从第一句到问题及紧邻回答的完整前缀。例：先说某公司在落地AI、给员工安全感，再问“他是怎么做的？”，再答具体做法；这不是question-answer模式的片首问题，也不能只引用问题却漏掉前面的背景。背景缺对象或仍需删掉前文时判missing-context/uncertain，不能用新模式绕过语义复核。此模式可能较长，不能声称已在三秒内交代完整。'''
RULE+='''\n字幕分段不是语义句界。独立开场也可以由当前稿开头连续的几段原话共同完成：先交代案例主体、紧接点明讨论场景或事件，整组自足即可，不强制第一条字幕单独包含全部信息。例：“朋友公司的员工”紧接“都在私下用AI，却不愿接正式任务”，对象和矛盾已在这组原话里说清；首段弱不等于信息缺失。但“那时他也这样”紧接“所以就失败了”仍未交代他是谁、做了什么，必须拒绝。不能把稍后解释、标题、说明文字或计划恢复的句子当作当前开场已说出。完整性与吸引力分开，超过三秒如实说明，不靠缩短字幕测量冒充短开场。'''
SCHEMA+='''\n独立表达跨多段字幕时使用mode="context-statement"，仍只返回五个字段：firstId必须为实际第一句，questionId=null，answerId为这组开场表达结束的实际后续句ID（不能等于第一句）。reason逐字引用这组开场中的主体与事件/判断，说明必要信息已在哪些保留原话里给出；若仍需缺失前文则判missing-context/uncertain。工具将绑定从firstId到answerId的实际完整前缀，不允许跳过中间句。该模式既不自动批准语义，也不允许截字、补台词或忽略其他复核问题；含提问回应的开场使用原有问答模式。'''

def question_prefix(value,original,draft):
    """Only trusted original ASR membership can bind a multi-caption question.

    Source grouping is provenance, not speaker or semantic confirmation. The
    independent reviewer still decides whether this question is necessary.
    """
    ids=[r['id'] for r in draft];q=value.get('questionId')
    if q not in ids:return None
    if q==ids[0]:return [q]
    refs={r['id']:r for r in original};first=refs.get(ids[0],{});unit=first.get('sourceUnit',{});members=unit.get('members',[])
    if unit.get('origin')!='original-asr-unit' or unit.get('terminalQuestion') is not True or not isinstance(unit.get('id'),str):return None
    if ids[0] not in members or q not in members:return None
    a=members.index(ids[0]);b=members.index(q)
    if b<=a or q!=members[-1] or ids[:ids.index(q)+1]!=members[a:b+1]:return None
    if any(refs.get(sid,{}).get('sourceUnit',{}).get('id')!=unit['id'] for sid in ids[:ids.index(q)+1]):return None
    return ids[:ids.index(q)+1]


def validate(value,original,draft):
    if not isinstance(value,dict) or set(value)!={'mode','firstId','questionId','answerId','reason'} or not draft:
        raise ValueError('开场上下文复核不完整，未执行剪辑')
    ids=[r['id'] for r in draft];known={r['id'] for r in original};mode=value['mode'];q=value['questionId'];a=value['answerId']
    if mode not in ('question-answer','context-question-answer','context-statement','standalone','missing-context','uncertain') or value['firstId']!=ids[0] or len(set(ids))!=len(ids) or any(sid not in known for sid in ids) or not isinstance(a,str) or a not in ids or not isinstance(value['reason'],str) or not value['reason'].strip() or len(value['reason'])>1200 or (q is not None and (not isinstance(q,str) or q not in known)):
        raise ValueError('开场上下文引用无效，未执行剪辑')
    if mode=='question-answer' and (question_prefix(value,original,draft) is None or a==q or ids.index(a)<=ids.index(q)):
        raise ValueError('开场提问与回应没有实际保留，未执行剪辑')
    if mode=='context-question-answer' and (q not in ids or ids.index(q)==0 or ids.index(a)!=ids.index(q)+1):
        raise ValueError('开场背景、提问与紧邻回应没有完整保留，未执行剪辑')
    if mode=='standalone' and (a!=ids[0] or q is not None):
        raise ValueError('独立开场判断与实际短稿不符，未执行剪辑')
    if mode=='context-statement' and (q is not None or ids.index(a)==0):
        raise ValueError('完整开场表达组没有实际连续保留，未执行剪辑')
    if mode in ('missing-context','uncertain') and a!=ids[0]:
        raise ValueError('开场缺失判断没有引用实际开头，未执行剪辑')
    return dict(value)

def apply(review,original,draft,plan):
    import copy
    check=validate(review.get('openingContext'),original,draft);review=copy.deepcopy(review)
    if check['mode'] in ('missing-context','uncertain'):
        review['passed']=False
        if not any(i.get('id')==check['answerId'] for i in review['issues'] if isinstance(i,dict)):
            review['issues'].append({'id':check['answerId'],'reason':check['reason']})
        review['reason']=check['reason']
    review['openingContext']=check
    result=copy.deepcopy(plan)
    result.pop('openingContextPrefix',None)
    result.pop('openingQuestionUnit',None)
    if check['mode']=='question-answer':
        prefix=question_prefix(check,original,draft)
        chain=[*prefix,check['answerId']]
        for edge in [list(pair) for pair in zip(chain,chain[1:])]:
            if edge not in result.get('dependencies',[]):result['dependencies']=[*result.get('dependencies',[]),edge]
        if len(prefix)>1:result['openingQuestionUnit']={'ids':prefix,'sourceUnitId':next(r for r in original if r['id']==prefix[0])['sourceUnit']['id']}
    if check['mode'] in ('context-question-answer','context-statement'):
        ids=[r['id'] for r in draft];prefix=ids[:ids.index(check['answerId'])+1]
        for edge in [list(pair) for pair in zip(prefix,prefix[1:])]:
            if edge not in result.get('dependencies',[]):result['dependencies']=[*result.get('dependencies',[]),edge]
        result['openingContextPrefix']={'ids':prefix,'questionId':check['questionId'],'answerId':check['answerId']}
    result['openingContext']=check;result['openingContextVersion']=VERSION
    return result,review


def group_report(plan,clips,speed=1,target=3):
    """Measure a reviewed prefix as a whole; never certify its semantics."""
    prefix=plan.get('openingContextPrefix',{}).get('ids')
    if prefix is None:return None
    if not isinstance(prefix,list) or len(prefix)<2 or len(set(prefix))!=len(prefix) or speed<=0:
        raise ValueError('完整开场组的时长引用无效')
    actual=[];selected=[]
    for clip in clips:
        sid=clip['id']
        if not actual or sid!=actual[-1]:
            if len(actual)==len(prefix):break
            actual.append(sid)
        selected.append(clip)
    if actual!=prefix or any(c['end']<c['start'] for c in selected):
        raise ValueError('完整开场组与实际取音顺序不一致')
    seconds=round(sum((c['end']-c['start'])/speed for c in selected),3)
    return {'version':1,'ids':list(prefix),'actualSeconds':seconds,'targetSeconds':target,
            'withinTarget':seconds<=target+.05,'method':'complete-reviewed-prefix-source-clips',
            'note':'整组计时，三秒为优先目标，不授权截断、加速或判定语义通过'}
