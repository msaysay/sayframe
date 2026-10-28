"""Enforce explicit creator editing limits; never infer them from media.

This deliberately recognizes narrow affirmative instructions. Unrecognized
natural language still goes through the ordinary independent semantic review.
It changes no sentence, order, word removal or source timing itself.
"""
import re
VERSION=10
PRESENTATION_VERSION=2


def _listed_reuse(text):
    item=r'(?:上行标题|视频标题|主标题|副标题|封面文字|封面文案|封面|标题|字幕字体|字体|高亮|人物介绍|人物信息|配乐|音乐|音量|字幕|姓名|介绍|设置)'
    pattern=r'(?P<items>'+item+r'(?:[、，,与和及]'+item+r'){1,10})(?:也|均|都|全部|继续|原样){0,3}(?:保持(?:不变|原样)?|不变|沿用)'
    found=[]
    for m in re.finditer(pattern,text):
        prefix=text[max(0,m.start()-32):m.start()]
        if re.search(r'(?:不|不要|不必|无需|不用|别|不想)(?:再|继续|要求|保留)?[^，,。；\n]{0,12}$|(?:如果|比如|例如|假如)[^。；\n]*$',prefix):continue
        found.append(set(re.split('[、，,与和及]',m['items'])))
    return found


def preserve_presentation(messages):
    """An explicit whole presentation lock, independent of speech cleanup.

    Style-only cover requests or partial lists do not freeze unrelated fields.
    Only the latest human request grants this execution scope.
    """
    latest=next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'),'')
    for m in re.finditer(r'(?:可以|允许)(?:重新)?(?:改|换|调整)(?:封面|标题|画面|配乐|音乐|人物介绍|字体|字幕|高亮|音量)|(?:主标题|副标题|字体|字幕|高亮|音量)(?:[：:\s]|请|再|可以|需要|要|也){0,4}(?:改|换|设|调)|重新生成封面',latest):
        if not re.search(r'(?:不|不能|不要|不是|并非|如果|比如)[^，,。；\n]{0,6}$',latest[max(0,m.start()-12):m.start()]):return False
    # Explicitly sound-only work does not authorize unrelated visual changes.
    for m in re.finditer(r'(?:只|仅)(?:重新)?(?:做|修|调整|进行)(?:声音|语音|气口)',latest):
        if not re.search(r'(?:不|不要|不是|并非|不必|不用|无需|不能|别|如果|比如|例如|假如)[^，,。；\n]{0,12}$',latest[max(0,m.start()-24):m.start()]):return True
    for items in _listed_reuse(latest):
        if all(items&group for group in ({'标题','视频标题','上行标题'},{'封面','封面文字','封面文案'},{'字体','字幕字体','字幕'},{'人物介绍','人物信息'},{'音乐','配乐'},{'音量'})):return True
    for m in re.finditer(r'(?:画面(?:与|和)声音设置|画面设置|展示设置)(?:也|均|都|全部){0,3}(?:保持(?:不变|原样)?|不变|沿用)',latest):
        prefix=latest[max(0,m.start()-24):m.start()]
        if not re.search(r'(?:不|不要|无需|不用|别|不要求|如果|比如|例如|假如)[^。；\n]*$',prefix):return True
    return False


def require_presentation(before,after):
    changed=[k for k in set(before)|set(after) if k!='pacing' and before.get(k)!=after.get(k)]
    if changed:raise ValueError('声音精剪改变了要求保留的画面或音量设置，未作为完成结果：'+','.join(sorted(changed)))
    return {'version':PRESENTATION_VERSION,'passed':True,'settingsUnchangedExceptPacing':True}


def preserve_editorial_rows(messages):
    limits=explicit(messages)
    return preserve_presentation(messages) and bool(limits.get('content') and limits.get('order'))


def presentation_rows(project,edited):
    """Keep source-bound visual anchors during explicitly sound-only work."""
    import copy
    refs={r['id']:r for r in project['segments']};out=copy.deepcopy(edited)
    for row in out:
        if row['id'] not in refs:raise ValueError('声音精剪的画面锚点缺少原句绑定')
        for field in ('label','contentValue','emphasis'):
            if field in refs[row['id']]:row[field]=copy.deepcopy(refs[row['id']][field])
            else:row.pop(field,None)
    return out


def require_presentation_rows(before,after):
    old={r['id']:r for r in before};new={r['id']:r for r in after}
    if set(old)!=set(new):raise ValueError('声音精剪改变了画面锚点原句集合')
    for sid,a in old.items():
        b=new[sid]
        if any(a.get(k)!=b.get(k) for k in ('label','emphasis')):raise ValueError('声音精剪改变了原有字幕高亮或人物介绍依据，未作为完成结果')
    return {'version':PRESENTATION_VERSION,'passed':True,'labelsAndEmphasisUnchanged':True,'identitySelectionAnchorsPreserved':True}


def explicit(messages):
    patterns=[
        (r'(?:只|仅)(?:重新)?(?:做|修|调整|进行)(?:声音|语音|气口)',{'content':True,'order':True}),
        (r'(?:保持|保留).{0,8}(?:当前|现有).{0,16}(?:内容|原句|句子|文稿|片段|段落|段).{0,8}(?:和|与|以及|及|、).{0,6}(?:成片)?顺序',{'content':True,'order':True}),
        (r'不删(?:任何)?(?:整句|句子)|不删句|不删掉当前保留的完整内容',{'content':True}),
        (r'不调序|不换顺序|顺序不(?:变|动)|保持(?:当前|现有)?(?:成片)?顺序',{'order':True}),
        (r'(?:可以|允许)(?:重新)?(?:删句|删整句|选句)',{'content':False}),
        (r'(?:可以|允许)(?:重新|自由)?(?:调整顺序|调序|重排|换序)',{'order':False}),
    ]
    result={}
    for message in messages:
        if message.get('role')!='user':continue
        text=message.get('content','');events=[]
        rules=[(r'另剪|换(?:个|一个)?方向|换主线|重新选(?:择)?主线',{'content':False,'order':False}),*patterns]
        for pattern,flags in rules:
            for match in re.finditer(pattern,text):
                # A new clip or an explicit permission releases only these
                # structural limits. A follow-up does not silently revoke them.
                prefix=text[max(0,match.start()-8):match.start()]
                if re.search(r'(?:不要|不是|并非|不必|不用|无需|不能|别|如果|比如|例如)[^，。；\n]{0,4}$',prefix) or re.search(r'(?:不|不能)$',prefix):continue
                events.append((match.start(),flags))
        for _,flags in sorted(events,key=lambda e:e[0]):result.update(flags)
    return {k:v for k,v in result.items() if v}



def preserve_speech(messages):
    """A narrow latest-human request; model flags and historical text confer no authority."""
    latest=next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'),'')
    events=[]
    rules=[
        (r'(?:不增加|不新增)(?:任何)?(?:删词|删字|声音剪切)',True),
        (r'(?:不要|不再)(?:进行|做|自动)?(?:删词|删字|声音精剪)',True),
        (r'(?:保留|保持)(?:当前|现有|现在|原有|已有|的){0,4}(?:文字和声音|文字声音|删字和声音切口|声音切口|声音边界|取音边界)',True),
        (r'(?:可以|允许)(?:继续|重新|自动)?(?:删词|删字|声音精剪|调整声音切口)',False),
    ]
    for pattern,value in rules:
        for match in re.finditer(pattern,latest):
            prefix=latest[max(0,match.start()-12):match.start()]
            if re.search(r'(?:不要|不是|并非|不必|不用|无需|如果|比如|例如|假如|不能|不允许)[^，。；\n]{0,5}$',prefix):continue
            events.append((match.start(),value))
    return sorted(events)[-1][1] if events else False


def require_speech_plan(messages,plan):
    if not preserve_speech(messages):return False
    conflicts=[k for k in ('wordEdits','questionEdits','questionCuts','statementEdits','statementCuts','repetitions') if plan.get(k)]
    if conflicts:raise ValueError('创作者明确要求保留现有删字与声音切口，不新增删词或恢复旧删字；请重新规划，清空局部声音修改清单：'+','.join(conflicts))
    return True


def check(messages,project,effective):
    limits=explicit(messages)
    if not limits:return None
    expected=[r['id'] for r in project['segments'] if not r['deleted']]
    actual=[r['id'] for r in effective if not r['deleted']]
    issues=[]
    if limits.get('content') and set(expected)!=set(actual):
        issues.append({'kind':'creator-constraint','reason':'创作者明确要求保留当前整句内容，方案却删句或恢复了未授权句子','removedIds':[sid for sid in expected if sid not in actual],'addedIds':[sid for sid in actual if sid not in expected]})
    if limits.get('order') and [sid for sid in expected if sid in actual]!=[sid for sid in actual if sid in expected]:
        issues.append({'kind':'creator-constraint','reason':'创作者明确要求保持当前成片顺序，方案却调整了原句顺序'})
    return {'version':VERSION,'limits':limits,'passed':not issues,'reason':'当前整句保留与相对顺序符合明确要求' if not issues else '方案改变了创作者明确要求保持的内容或顺序；请重新规划，不能只改说明','issues':issues,'approvedOrder':expected,'proposedOrder':actual}


def require(messages,project,effective):
    report=check(messages,project,effective)
    if report and not report['passed']:raise ValueError(report['reason'])
    return report


def require_plan(messages,rows,plan):
    """Diagnose explicit selection limits before dependency/schema repair.

    A drop ID always removes the whole row, even when its explanation says
    'only remove the filler'. Never convert that mistake into a word cut or
    silently restore the sentence. Invalid ID shapes remain schema errors.
    """
    if not isinstance(plan,dict):return None
    require_speech_plan(messages,plan)
    if not explicit(messages):return None
    ids=[r['id'] for r in rows];order=plan.get('order');drop=plan.get('drop',[])
    if (not isinstance(order,list) or not isinstance(drop,list)
        or any(not isinstance(s,str) for s in order+drop)
        or len(order)!=len(ids) or set(order)!=set(ids)
        or len(set(drop))!=len(drop) or not set(drop)<=set(ids)):
        return None
    project={'segments':[{'id':sid,'deleted':False} for sid in ids]}
    effective=[{'id':sid,'deleted':sid in drop} for sid in order]
    report=check(messages,project,effective)
    if report and not report['passed']:
        import json
        removed=[{'id':r['id'],'text':r['text']} for r in rows if r['id'] in drop]
        content_note='当前明确保留整句，drop必须为空，dropReasons必须为{}；声音精剪交由后续原音核验。' if report['limits'].get('content') else '本轮允许删句时可保留真实删句清单，但保留句的相对顺序必须符合要求。'
        raise ValueError(report['reason']+'。drop中的ID表示删除整句，不是删该句中的某个字或语气词；写“其余保留”不能抵消实际整句删除。'+content_note+'实际拟删整句：'+json.dumps(removed,ensure_ascii=False)+'；当前授权顺序：'+json.dumps(ids,ensure_ascii=False))
    return report


def preserved_cover(messages,settings):
    """Bind only explicit reuse of an existing nonempty two-line cover.

    A new cover wording request is not a reuse instruction. Unknown/blank
    old copy is not invented. No facts, timing or editorial rows are changed.
    """
    latest=next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'),'')
    if preserve_presentation(messages):
        existing={k:settings.get(k) for k in ('coverTitle','coverSubtitle')}
        if isinstance(existing['coverTitle'],str) and existing['coverTitle'].strip() and isinstance(existing['coverSubtitle'],str):return existing
    if re.search(r'(?:不|不要|无需|不用)(?:再)?沿用|(?:主标题|副标题)(?:[：:\s]|请|再|可以|需要|要|也){0,4}(?:改|换|设)',latest):return None
    scope=__import__('local_edit_scope').request(messages)
    if scope and scope['preserveSettings']:
        copy={k:settings.get(k) for k in ('coverTitle','coverSubtitle')}
        return copy if all(isinstance(v,str) and v.strip() for v in copy.values()) else None
    listed=r'(?:[、与及和]|上行标题|人物信息|字幕|配乐|音乐|标题|介绍|姓名|也|均|都|设置|原样|当前|继续|原有|的)'
    reuse=re.search(r'封面(?:文字|文案)?'+listed+r'{0,24}(?:沿用|不变)|(?:沿用|不改)(?:原|当前|之前|现有|的){0,3}封面',latest)
    if not reuse:reuse=any(items&{'封面','封面文字','封面文案'} for items in _listed_reuse(latest))
    if not reuse:
        # A separated list includes the cover copy. "封面字体沿用" does not.
        item=r'(?:上行标题|字幕字体|人物介绍|人物信息|标题|字幕|音乐|配乐|姓名|介绍|字体|设置)'
        pattern=r'封面(?:文字|文案)?(?:[、，,与和及]'+item+r'){1,10}(?:也|均|都|全部|继续){0,3}(?:沿用|不变)'
        reuse=next((m for m in re.finditer(pattern,latest) if not re.search(r'(?:不|不要|不必|无需|不用|别|不想)(?:再|继续|要求|保留)?[^，,。；\n]{0,8}$',latest[max(0,m.start()-18):m.start()])),None)
    if not reuse:
        # Explicit reuse of this cover, not merely its font/style/person.
        # Keep the existing narrow field binding; do not infer replacement copy.
        prefix=r'(?:原|当前|之前|现有|现在|这版|这个|的|标题|上行标题|副标题|[、，,与和])'
        pattern=r'(?:保留|保持)'+prefix+r'{0,14}封面(?:文字|文案)?(?!文字|文案|(?:的)?(?:风格|样式|字体|构图|效果|人物|主体|背景|颜色|配色|版式))'
        reuse=next((m for m in re.finditer(pattern,latest) if not re.search(r'(?:不|不要|不必|无需|不用|别|不想)(?:再|继续)?\s*$',latest[max(0,m.start()-8):m.start()])),None)
    if not reuse:return None
    copy={k:settings.get(k) for k in ('coverTitle','coverSubtitle')}
    return copy if all(isinstance(v,str) and v.strip() for v in copy.values()) else None


def require_cover(messages,settings,plan):
    expected=preserved_cover(messages,settings)
    if expected and any(plan.get(k)!=v for k,v in expected.items()):
        import json
        raise ValueError('创作者要求沿用现有封面文字，方案却另写了文案；只修正这两个字段，不改正文、顺序或删词。当前封面：'+json.dumps(expected,ensure_ascii=False)+'；实际方案：'+json.dumps({k:plan.get(k) for k in expected},ensure_ascii=False))
    return expected


def planning_rule(messages,rows,settings=None):
    limits=explicit(messages)
    cover=preserved_cover(messages,settings or {})
    speech=preserve_speech(messages)
    presentation=preserve_presentation(messages)
    if not limits and not cover and not speech and not presentation:return ''
    import json
    value={'preserveSpeech':speech,'preservePresentation':presentation,'limits':limits,'editableOrder':[r['id'] for r in rows],**({'preserveCoverCopy':cover} if cover else {})}
    return '\n工具解析的创作者本轮明确约束：'+json.dumps(value,ensure_ascii=False)+'。content=true表示当前可编辑整句全部保留：drop=[]、dropReasons={}，不能将局部删字写入drop。order=true表示保持这些保留句的相对顺序。preserveSpeech=true时原有删字、声音边界、气口设置不变，wordEdits/questionEdits/questionCuts/statementEdits/statementCuts/repetitions均为空，不再发起自动精剪；false时局部语气词、口吃仍交给后续原音校准。不用整句删除代替；不得只在说明中承诺保留。preserveCoverCopy非空时主副标题逐字沿用，不另拟文案，也不能在回复里说沿用却返回另一套标题。'
