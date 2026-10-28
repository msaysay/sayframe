"""Silent picture-in-picture anchored to original words; edits never mutate media."""
import math,re,copy
from visual_track import asset_schema
def validate(value=None):
    value=[] if value is None else value
    if not isinstance(value,list) or len(value)>12:raise ValueError('画中画最多添加12项')
    ids=set();out=[]
    for v in value:
        if not isinstance(v,dict) or not isinstance(v.get('id'),str) or not re.fullmatch('[a-f0-9]{32}',v['id']) or v['id'] in ids or not isinstance(v.get('segmentId'),str) or not v['segmentId'] or type(v.get('wordIndex')) is not int or v['wordIndex']<0:raise ValueError('画中画绑定无效')
        ids.add(v['id']);asset=asset_schema(v.get('asset'))
        for k,lo,hi in [('duration',.5,7200),('assetStart',0,1800),('x',-3,3),('y',-3,3),('width',.05,3)]:
            if type(v.get(k)) not in (int,float) or not math.isfinite(v[k]) or not lo<=v[k]<=hi:raise ValueError('画中画位置或时长无效')
        if asset['kind']=='image' and v['assetStart']!=0 or asset['kind']=='video' and v['assetStart']>=asset['duration']:raise ValueError('画中画素材起点无效')
        if 'anchorOffset' in v and (type(v['anchorOffset']) not in (int,float) or not math.isfinite(v['anchorOffset']) or not -30<=v['anchorOffset']<=7200):raise ValueError('画中画时间偏移无效')
        out.append({**{k:v[k] for k in ('id','segmentId','wordIndex','duration','assetStart','x','y','width')},'asset':asset,**({'anchorOffset':v['anchorOffset']} if 'anchorOffset' in v else {})})
    return out
def windows(insets,clips,segments,speed=1,cover_duration=0):
    rows={s['id']:s for s in segments};out=[];offset=cover_duration
    for c in clips:
        for v in insets:
            if any(w['id']==v['id'] for w in out) or c['id']!=v['segmentId']:continue
            s=rows.get(v['segmentId']);w=s['words'][v['wordIndex']] if s and v['wordIndex']<len(s['words']) else None
            if not s or s['deleted'] or v['wordIndex'] in s['removed'] or not w or w['end']<=c['start'] or w['start']>=c['end']:continue
            start=max(cover_duration,offset+max(0,w['start']-c['start'])/c.get('speed',speed)+v.get('anchorOffset',0));duration=min(v['duration'],v['asset']['duration']-v['assetStart'] if v['asset']['kind']=='video' else math.inf)
            out.append({**copy.deepcopy(v),'start':start,'end':start+duration})
        offset+=c.get('outputDuration',(c['end']-c['start'])/speed)
    return [{**v,'end':min(v['end'],offset)} for v in out if min(v['end'],offset)>v['start']]
def geometry(v,width,height):
    w=v['width']*width;h=w*v['asset']['height']/v['asset']['width']
    return {'width':w,'height':h,'x':v['x']*width,'y':v['y']*height}
def composite(raw,folder,windows,width,height,assets,host):
    if not windows:return raw
    args=['-i',str(raw)];graph=[];previous='0:v'
    for i,v in enumerate(windows,1):
        actual=assets.read(v['asset']['id'],True)
        if actual!=v['asset']:raise ValueError('画中画素材凭据不匹配，请重新添加')
        span=v['end']-v['start'];image=actual['kind']=='image'
        args+=['-loop','1'] if image else ['-ss',str(v['assetStart'])]
        args+=['-t',str(span),'-i',str(assets.path(actual['id']))]
        g=geometry(v,width,height);w=max(2,round(g['width']/2)*2);h=max(2,round(g['height']/2)*2)
        graph.append(f'[{i}:v]scale={w}:{h},setsar=1,fps=30,trim=duration={span},setpts=PTS-STARTPTS+{v["start"]}/TB[inset{i}]')
        graph.append(f'[{previous}][inset{i}]overlay=x={round(g["x"])}:y={round(g["y"])}:enable=\'gte(t,{v["start"]})*lt(t,{v["end"]})\':eof_action=pass:repeatlast=0[out{i}]');previous=f'out{i}'
    dest=folder/'picture-in-picture.mkv'
    host.command(args+['-filter_complex_threads','1','-filter_complex',';'.join(graph),'-map',f'[{previous}]','-map','0:a:0?','-c:v','libx264','-preset','ultrafast','-crf','18','-pix_fmt','yuv420p','-c:a','copy',str(dest)])
    return dest
