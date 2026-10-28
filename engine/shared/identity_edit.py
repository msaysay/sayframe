import math
def validate_ranges(rows):
    if not isinstance(rows,list) or len(rows)>3:raise ValueError('人物介绍最多安排三次')
    result=[];end=-1
    for r in rows:
        if not isinstance(r,dict) or set(r)!={'start','end'} or any(type(r[k]) not in (float,int) or not math.isfinite(r[k]) for k in ('start','end')) or r['start']<0 or r['end']>7200 or r['end']-r['start']<.5-1e-6 or r['start']<end-1e-6:raise ValueError('人物介绍时间无效，至少半秒且不能重叠')
        result.append(dict(r));end=r['end']
    return result
