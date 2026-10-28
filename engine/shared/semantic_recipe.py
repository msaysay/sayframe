"""Compile a reviewed content outline into reversible source-bound edits."""
import copy,unicodedata

LABELS={'观点','支撑','肌肉词','人群','转化','提问'}

def mark_highlights(segments,highlights,strict=True):
    if not strict:
        from word_corrections import display_words
        refs=[{'id':r['id'],'text':''.join(w['word'] for i,w in enumerate(display_words(r)) if i not in r.get('removed',[]))} for r in segments if not r.get('deleted')]
        highlights,_=__import__('editorial_policy').normalize_highlights(highlights,refs)
    if not isinstance(highlights,list) or len(highlights)>12:raise ValueError('重点词建议无效')
    edits={r['id']:r for r in segments if not r.get('deleted')}
    for mark in highlights:
        row=edits.get(mark.get('id')) if isinstance(mark,dict) else None
        quote=mark.get('quote') if isinstance(mark,dict) else None
        if row is None or not isinstance(quote,str) or not quote:
            if not strict:continue
            raise ValueError('重点词缺少对应保留原话')
        kept=[(i,w) for i,w in enumerate(__import__('word_corrections').display_words(row)) if i not in row.get('removed',[])]
        retained=''.join(w['word'] for _,w in kept)
        if retained.count(quote)!=1:
            if not strict:continue
            raise ValueError('重点词不在保留原话中或存在歧义')
        start=retained.index(quote);end=start+len(quote);offset=0;indices=[]
        for i,w in kept:
            if offset<end and offset+len(w['word'])>start:indices.append(i)
            offset+=len(w['word'])
        row['emphasis']=sorted(set(row.get('emphasis',[]))|set(indices))
    return segments

def compile_recipe(recipe,source):
    if not isinstance(recipe,dict) or recipe.get('sourceId')!=source['id']:raise ValueError('内容方案与原素材不匹配')
    parts=recipe.get('parts');originals={s['id']:s for s in source['segments']}
    if not isinstance(parts,list) or not parts or len(parts)>30:raise ValueError('内容方案需要有效段落')
    order=[];edits={};labels=[];cuts=[]
    for part in parts:
        if not isinstance(part,dict) or part.get('label') not in LABELS or not isinstance(part.get('reason'),str) or not part['reason'].strip():raise ValueError('内容段落需要说明保留理由')
        references=part.get('sentences')
        if not isinstance(references,list) or not references:raise ValueError('内容段落缺少原句引用')
        for ref in references:
            sid=ref.get('id');row=originals.get(sid)
            if row is None or sid in edits or ref.get('quote')!=row['text']:raise ValueError('原句引用已变化、缺失或重复，未应用方案')
            edited=copy.deepcopy(row);edited.update(deleted=False,label=part['label'])
            removed=set(row.get('removed',[]))
            for quote in ref.get('removePrefixes',[]):
                if not isinstance(quote,str) or not quote or not row['text'].startswith(quote):raise ValueError('精简内容不是对应原句的起始原话')
                indices=[];offset=0
                for i,w in enumerate(row['words']):
                    if offset<len(quote):
                        if offset+len(w['word'])>len(quote):raise ValueError('精简范围切进了未对齐的原词')
                        indices.append(i)
                    offset+=len(w['word'])
                if any(w['end']<=w['start'] for i,w in enumerate(row['words']) if i in indices and any(not c.isspace() and not unicodedata.category(c).startswith('P') for c in w['word'])):raise ValueError('精简原话时间不可靠，请先核对切口')
                removed.update(indices);cuts.append({'id':sid,'quote':quote,'indices':indices})
            edited['removed']=sorted(removed)
            if len(removed)>=len(row['words']):raise ValueError('精简不能把保留原句全部删除')
            edits[sid]=edited;order.append(sid);labels.append({'id':sid,'label':part['label'],'reason':part['reason']})
    text=''.join(''.join(w['word'] for i,w in enumerate(edits[sid]['words']) if i not in edits[sid]['removed']) for sid in order)
    for quote in recipe.get('protectedQuotes',[]):
        if not isinstance(quote,str) or not quote or quote not in text:raise ValueError('内容方案丢失了必须保留的限定或事实原话')
    highlights=recipe.get('highlights',[])
    mark_highlights(list(edits.values()),highlights)
    segments=[edits[sid] for sid in order]+[{**copy.deepcopy(s),'deleted':True} for s in source['segments'] if s['id'] not in edits]
    settings=copy.deepcopy(recipe.get('settings',{}))
    plan={'order':order,'drop':[],'dropReasons':{},'dependencies':[[a,b] for a,b in zip(order,order[1:])],'summary':recipe['summary'],'coverTitle':settings['coverTitle'],'coverSubtitle':settings['coverSubtitle'],'tone':'warm','labels':labels,'repetitions':[],'origin':'gpt-editor','review':{'passed':True,'reason':'依据原文整理并核对上下文的内容方案；这不是医学或业绩核验。','origin':'gpt-editor'}}
    plan['protectedQuotes']=copy.deepcopy(recipe.get('protectedQuotes',[]))
    origin=recipe.get('origin','gpt-editor')
    if origin not in ('gpt-editor','semantic-planner'):raise ValueError('内容方案来源无效')
    if origin=='semantic-planner':
        review=recipe.get('review')
        if not isinstance(review,dict) or review.get('passed') is not True or not isinstance(review.get('reason'),str) or not review['reason'].strip():raise ValueError('自动内容方案尚未通过独立复核')
        plan.update(origin=origin,review=copy.deepcopy(review),tone=recipe.get('tone','clear'),highlights=copy.deepcopy(highlights),frameworkFit=recipe.get('frameworkFit'),usage=recipe.get('usage',[]),formattingWarnings=copy.deepcopy(recipe.get('formattingWarnings',[])),editWarnings=copy.deepcopy(recipe.get('editWarnings',[])))
    return {'project':{'version':1,'sourceId':source['id'],'title':source['title'],'segments':segments,'settings':settings},'plan':plan,'cuts':cuts,'retainedText':text}

def register(recipe,record,api,persist_assistant=True):
    import editor_workflow,automatic_edit
    source=api.public_case(record,True);compiled=compile_recipe(recipe,source)
    project=api.PROJECT_LIBRARY.clean_project(compiled['project'],source)
    _,_,rows,binding=editor_workflow.prepare(record,project,api)
    automatic_edit.validate_plan(compiled['plan'],rows)
    value={'kind':'editor-analysis','sourceId':source['id'],'binding':binding,'plan':compiled['plan'],'reused':True,'origin':compiled['plan']['origin']}
    cache=api.ROOT/'recognition-cache';cache.mkdir(exist_ok=True)
    path=cache/('editor-plan-v1-'+binding+'.json')
    if path.is_file() and compiled['plan']['origin']=='semantic-planner':
        import json
        previous=json.loads(path.read_text('utf8'))
        if previous.get('origin')=='gpt-editor':
            value=previous;compiled['plan']=copy.deepcopy(previous['plan'])
        else:api.save(path,value)
    else:api.save(path,value)
    if persist_assistant:api.save(cache/('assistant-recipe-'+source['id']+'.json'),recipe)
    return {**compiled,'project':project,'analysis':value}
