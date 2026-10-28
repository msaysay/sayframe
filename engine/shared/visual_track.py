"""Source-word anchors and half-open 30fps visual windows. Never controls audio."""
import re,math,copy
def fail(m):raise ValueError('画面轨无效：'+m)
def key(r):return (r['pickupId'] or 'main')+':'+r['segmentId']
def asset_schema(a):
    if not isinstance(a,dict) or not isinstance(a.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',a['id']) or a.get('kind') not in ('image','video') or not isinstance(a.get('title'),str) or not a['title'].strip() or len(a['title'])>300 or a.get('usage') not in ('own','reference') or not isinstance(a.get('note'),str) or len(a['note'])>1000:fail('素材凭据')
    if any(type(a.get(k)) is not int or not 0<a[k]<=8192 for k in ('width','height')) or type(a.get('duration')) not in (int,float) or not math.isfinite(a['duration']) or not 0<=a['duration']<=1800 or a['kind']=='video' and a['duration']<=0 or a['kind']=='image' and a['duration']!=0:fail('素材时序')
    if any(not isinstance(a.get(k),str) or not re.fullmatch('[a-f0-9]{64}',a[k]) for k in ('sha256','originalSha256')) or a.get('url')!='/visual-assets/'+a['id']+'/media' or a.get('thumbnailUrl')!='/visual-assets/'+a['id']+'/thumbnail':fail('素材地址或校验')
    return {k:a[k] for k in ('id','kind','title','usage','note','width','height','duration','sha256','originalSha256','url','thumbnailUrl')}
def validate_visual_track(v,rows,kept):
    if not isinstance(v,dict) or v.get('version')!=1 or not isinstance(v.get('clips'),list) or len(v['clips'])>100:fail('轨道格式')
    ids=set();occupied=set();clips=[]
    for c in v['clips']:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',c['id']) or c['id'] in ids:fail('片段标识')
        ids.add(c['id']);r=c.get('ref')
        if not isinstance(r,dict) or 'pickupId' not in r or not (r['pickupId'] is None or isinstance(r['pickupId'],str) and re.fullmatch('[a-f0-9]{32}',r['pickupId'])) or not isinstance(r.get('segmentId'),str):fail('原段引用')
        k=key(r);s=rows.get(k)
        if not s or k not in kept:fail('原段已移除，请先解除对应画面')
        indices=c.get('indices');active=[i for i in range(len(s['words'])) if i not in s['removed']]
        if not isinstance(indices,list) or not indices or any(type(i) is not int or i not in active or n>0 and i<=indices[n-1] for n,i in enumerate(indices)):fail('绑定原词已变化，请先解除画面再编辑')
        at=active.index(indices[0])
        if active[at:at+len(indices)]!=indices or c.get('anchorText')!=''.join(s['words'][i]['word'] for i in indices):fail('绑定原词范围或文字已变化')
        for i in indices:
            q=(k,i)
            if q in occupied:fail('同一原词不能重复覆盖')
            occupied.add(q)
        if c.get('fit') not in ('cover','contain') or not isinstance(c.get('note'),str) or len(c['note'])>1000 or type(c.get('assetStart')) not in (int,float) or not math.isfinite(c['assetStart']) or c['assetStart']<0:fail('画面设置')
        a=asset_schema(c.get('asset'))
        if a['kind']=='image' and c['assetStart']!=0 or a['kind']=='video' and c['assetStart']>=a['duration']:fail('画面起点超出素材')
        clips.append({'id':c['id'],'ref':{n:r[n] for n in ('pickupId','segmentId')},'indices':indices[:],'anchorText':c['anchorText'],'asset':a,'assetStart':c['assetStart'],'fit':c['fit'],'note':c['note']})
    return {'version':1,'clips':clips}
def visual_windows(clips,track,rows):
    totals={};out=copy.deepcopy(clips)
    for c in out:
        c['visualWindows']=[]
        for v in track.get('clips',[]):
            if key(v['ref'])!=key(c):continue
            selected=[i for i in v['indices'] if c['firstIndex']<=i<=c['lastIndex']]
            if not selected:continue
            s=rows[key(v['ref'])];a=max(0,math.ceil((s['words'][selected[0]]['start']-c['start'])*30-1e-7));b=min(math.ceil((c['end']-c['start'])*30-1e-7),math.ceil((s['words'][selected[-1]]['end']-c['start'])*30-1e-7))
            if b<=a:fail('绑定范围不足一帧，请扩大选词')
            offset=totals.get(v['id'],0);start=v['assetStart']+offset/30
            if v['asset']['kind']=='video' and start+(b-a)/30>v['asset']['duration']+1e-7:fail('视频画面长度不足，请缩短绑定原词或换素材')
            c['visualWindows'].append({'id':v['id'],'asset':v['asset'],'fit':v['fit'],'startFrame':a,'endFrame':b,'start':a/30,'end':b/30,'assetStart':start});totals[v['id']]=offset+b-a
        c['visualWindows'].sort(key=lambda w:w['startFrame'])
        if any(w['startFrame']<c['visualWindows'][i-1]['endFrame'] for i,w in enumerate(c['visualWindows']) if i):fail('画面时间区间重叠')
    return out
