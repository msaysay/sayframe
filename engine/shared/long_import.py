"""Choose one coherent short edit from an uncut long interview; retain all source."""
import copy
import automatic_edit

def validate_selection(value,rows):
    ids=value.get('ids') if isinstance(value,dict) else None
    if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):raise ValueError('长访谈选题缺少有效原句')
    originals={r['id']:r for r in rows}
    if any(sid not in originals for sid in ids):raise ValueError('长访谈选题引用了不存在的原句')
    if ids!=[r['id'] for r in rows if r['id'] in set(ids)]:raise ValueError('长访谈选题改变了原问答顺序')
    seconds=sum(originals[sid]['end']-originals[sid]['start'] for sid in ids)
    if not 15<=seconds<=180:raise ValueError('长访谈选题长度需要重新整理，原素材保留')
    if not isinstance(value.get('topic'),str) or not value['topic'].strip() or len(value['topic'])>50:raise ValueError('长访谈选题缺少主题')
    return {**value,'sourceSeconds':round(seconds,3)}

def run(key,record,opts,api):
    import editor_workflow,video_finish
    source=api.public_case(record,True);rows=source['segments']
    reviewed=api.ROOT/'recognition-cache'/('assistant-recipe-'+source['id']+'.json')
    if reviewed.is_file():
        import json,semantic_recipe
        api.TASKS.progress(key,'正在按已整理的内容方案剪辑')
        compiled=semantic_recipe.register(json.loads(reviewed.read_text('utf8')),record,api)
        result=editor_workflow.run(key,record,compiled['project'],api,music_allowed=opts['music']!='off')
        return {**result,'longSelection':{'topic':compiled['plan']['coverTitle'],'ids':compiled['plan']['order'],'origin':compiled['plan']['origin']},'options':opts}
    import content_recipe,semantic_recipe
    planned=content_recipe.plan(key,source,opts,api)
    compiled=semantic_recipe.register(planned['recipe'],record,api,persist_assistant=False)
    result=editor_workflow.run(key,record,compiled['project'],api,music_allowed=opts['music']!='off')
    selection={'topic':planned['topic'],'ids':compiled['plan']['order'],'reason':compiled['plan']['summary'],'sourceSeconds':planned['sourceSeconds'],'origin':'semantic-planner'}
    api.save(api.ROOT/'outputs'/key/'long-selection.json',{'selection':selection,'recipe':planned['recipe'],'review':planned['review'],'usage':planned['usage'],'allOriginalSentences':len(rows)})
    return {**result,'longSelection':selection,'options':opts}
