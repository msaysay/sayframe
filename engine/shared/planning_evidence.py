"""A fresh assessment reads creator intent and source, not old AI explanations.

Stored conversation remains intact for the UI. Prior concrete source references
are navigation context only; they grant no editing or acoustic authority.
"""
import copy,hashlib,json

VERSION=2
RULE='''本次重新判断只以创作者conversation与当前transcript为依据。selectedDirection与previousDirections仅标识选题、人群和框架，不是人物事实或内容必要性的证据。previousProposal仅帮助理解创作者所指的旧方案，尚未授权执行；它不证明某句话必留或可删。历史助手说明与旧方向的reason/opening/strategy/tradeoff可能出错，本次不将其当事实或重新判断的前提。重新对照真实保留原话判断：不要为了与旧建议一致而重复旧理由，也不要为了显示有修改而强造删减。语义候选仍须独立全文复核和原声安全校准，不能在规划阶段声称已经安全删音。'''
RULE+='''规划阶段尚未校准声音，不等于内容不可省或已确认不能剪开。若真实保留全文支持去掉可选铺垫，且本句剩下唯一连续、完整、忠实的原话，应返回statementEdits内容候选，reason说明待原音核验；按方案成片才调用真实声音校准，失败会保留原稿。不要以“还没有真实切点”拒绝提出语义成立的候选，也不要把语义可省写成声音已经安全删除。只有相同完整候选确有旧失败证据，或当前原话/预留/必要条件不允许时才不重复提出它；孤立单字失败不等于更完整语义候选已经失败。'''


def identity(direction):
    return {k:copy.deepcopy(direction[k]) for k in ('name','audience','framework') if k in (direction or {})}


def references(plan,rows):
    known={r['id']:r['text'] for r in rows};out={}
    for field in ('order','drop'):
        out[field]=[sid for sid in plan.get(field,[]) if isinstance(sid,str) and sid in known]
    refs=[]
    for field,quote_field in [('statementEdits','keepQuote'),('questionEdits','keepQuote'),('wordEdits','requestedQuote')]:
        for edit in plan.get(field,[]):
            if not isinstance(edit,dict):continue
            sid=edit.get('id');quote=edit.get(quote_field)
            if sid in known and isinstance(quote,str) and 0<len(quote)<=300 and quote in known[sid]:
                item={'id':sid,'quote':quote,'proposalType':field}
                if item not in refs:refs.append(item)
    out['editReferences']=refs
    return out


def view(messages,previous,selected,rows,fresh):
    directions=(previous or {}).get('directions',[])
    if not fresh:
        return {'conversation':copy.deepcopy(messages),'previousDirections':[{k:copy.deepcopy(v) for k,v in d.items() if k!='plan'} for d in directions],
                'selectedDirection':{k:copy.deepcopy(v) for k,v in selected.items() if k!='plan'} if selected else None}
    return {'conversation':[copy.deepcopy(m) for m in messages if m['role']=='user'],
            'previousDirections':[identity(d) for d in directions],
            'selectedDirection':identity(selected) if selected else None,
            'previousProposal':references((selected or {}).get('plan',{}),rows),
            'planningEvidenceVersion':VERSION}


def receipt(messages,wire,fresh):
    creator=[m for m in messages if m['role']=='user']
    return {'version':VERSION,'stage':'prepared-model-input; not a quality verdict','freshAssessment':fresh,
            'conversationRoles':[m['role'] for m in wire['conversation']],
            'excludedAssistantMessages':sum(m['role']=='assistant' for m in messages) if fresh else 0,
            'creatorIntentSha256':hashlib.sha256(json.dumps(creator,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'selectedDirectionFields':sorted((wire.get('selectedDirection') or {}).keys()),
            'previousProposal':copy.deepcopy(wire.get('previousProposal'))}
