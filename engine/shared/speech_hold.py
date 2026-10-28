"""Keep uncertain restarts audible, never declare an unsafe deletion successful.

Only already retained original words are eligible. A fresh independent review
and the unchanged downstream acoustic/integrity gates remain mandatory.
"""
import copy
VERSION=1

def validate_retained(before,after,cuts,blocking):
    old={r['id']:r for r in before};new={r['id']:r for r in after};held=[]
    if [r['id'] for r in before]!=[r['id'] for r in after]:raise ValueError('待回听处理不能改变文稿顺序')
    for issue in blocking:
        sid=issue['id'];indices=issue['indices']
        cut=next((c for c in cuts if c.get('id')==sid and c.get('indices')==indices and c.get('quote')==issue['quote']),None)
        a,b=old.get(sid),new.get(sid)
        if not cut or cut.get('automatic') is not False or cut.get('dismissed') or cut.get('kind') not in ('repeat','falseStart'):raise ValueError('待回听建议与实际保留原话不一致')
        if not a or not b or a.get('deleted') or b.get('deleted') or not indices:raise ValueError('待回听原话没有实际保留')
        if any(type(i) is not int or i<0 or i>=len(a['words']) or i>=len(b['words']) or i in a.get('removed',[]) or i in b.get('removed',[]) or a['words'][i]['word']!=b['words'][i]['word'] for i in indices):raise ValueError('不能用待回听恢复已删字或代替实际删音')
        if ''.join(b['words'][i]['word'] for i in indices)!=cut['quote']:raise ValueError('待回听引用与原字不一致')
        held.append({'id':sid,'indices':list(indices),'quote':cut['quote'],'kind':cut['kind'],'reason':cut['holdReason']})
    return held

def review_retained(key,source,before,after,speech,blocking,settings,api):
    import speech_refine
    from content_recipe import bounded_request
    from clip_calibration import CalibrationRejected
    held=validate_retained(before,after,speech['cuts'],blocking)
    folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True)
    receipt={'version':VERSION,'sourceId':source['id'],'held':held,'restoredWords':False,'acousticGateStillRequired':True}
    api.save(folder/'speech-retained-restarts.json',receipt)
    api.TASKS.progress(key,'正在保留无法安全去掉的重说，复核完整原话')
    review,usage=bounded_request(speech_refine.REVIEW+'\nheldRestarts是声音切点不确定、已经完整保留的原话，不是已删除词，也不要求为去净口吃重选主线。核对actual afterRows仍完整保留它们及必要条件/否定/数字/问答，其他实际自动删词是否安全。原稿自身重说可以保留并标待回听，不能把原稿重说误判成剪辑造成的新重复；不能因为它保留就声称已清理。',
        {'beforeRows':speech_refine.packet_rows(before),'afterRows':speech_refine.packet_rows(after),'cuts':[c for c in speech['cuts'] if c['automatic']],'heldRestarts':held},api,
        max_output_tokens=4096,key=key,thinking=settings.get('analysisThinking','disabled'),phase='speech-retained-review')
    speech_refine.receipt(api,key,'speech-retained-review',usage)
    receipt['review']=review;api.save(folder/'speech-retained-restarts.json',receipt)
    if not speech_refine.validate_review(review):raise CalibrationRejected(blocking)
    return {**copy.deepcopy(speech),'retainedRestartReview':receipt}
