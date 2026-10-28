"""Conservative lexical counterexamples to character-frequency deletion.

These holds are not a complete Chinese parser. Ambiguous normal word junctions
remain spoken; the model may still consider a genuinely restarted whole clause.
"""
import re
VERSION=3
REASON='相邻同字属于正常词组衔接，不能只按字形当作重说删除'

MODALS=('可以','能够','应该','需要')
PREDICATES=('让','用','去','把','将','做','继续','直接','通过','按照','选择','获得','得到','成为','创造')

def _text(row):
    if isinstance(row.get('text'),str):return row['text']
    return ''.join(w['word'] for i,w in enumerate(row.get('words',[])) if i not in row.get('removed',[]))

def _plain(text):return ''.join(c for c in text if c.isalnum())

def _predicate(text):
    return re.sub(r'^[\s，,。.!！?？；;、呃嗯额啊哦]+','',text)

def _bounds(row):
    if isinstance(row.get('audioRanges'),list) and row['audioRanges']:
        ranges=row['audioRanges']
        return min(x[0] for x in ranges),max(x[1] for x in ranges)
    if row.get('start') is not None and row.get('end') is not None:return row['start'],row['end']
    if row.get('words') and row['words'][0].get('start') is not None and row['words'][-1].get('end') is not None:
        return row['words'][0]['start'],row['words'][-1]['end']
    return None

def plan_issues(plan,rows,draft_rows=None):
    """A whole-caption drop/reorder cannot bypass the same narrow dependency.

    Only original adjacent, time-near rows are evidence. Both discarded rows,
    a restarted modal, explicit different speakers and pre-existing user drops
    do not establish this dependency. This rejects a plan; it never resurrects
    text or silently edits the creator's project.
    """
    originals=[r for r in rows if not r.get('deleted')]
    actual={r['id']:r for r in (draft_rows if draft_rows is not None else rows)}
    order=[sid for sid in plan['order'] if sid not in plan.get('drop',[])]
    positions={sid:i for i,sid in enumerate(order)};issues=[]
    for left,right in zip(originals,originals[1:]):
        a,b=_bounds(left),_bounds(right)
        if not a or not b or not -.2<=b[0]-a[1]<=1:continue
        if left.get('speaker') and right.get('speaker') and left['speaker']!=right['speaker']:continue
        modal=next((m for m in MODALS if _plain(_text(left)).endswith(m)),None)
        if not modal or not _predicate(_text(right)).startswith(PREDICATES):continue
        li,ri=positions.get(left['id']),positions.get(right['id'])
        if li is None and ri is None:continue
        valid=li is not None and ri==li+1
        valid=valid and left['id'] in actual and right['id'] in actual
        valid=valid and _plain(_text(actual[left['id']])).endswith(modal) and _predicate(_text(actual[right['id']])).startswith(PREDICATES)
        if not valid:
            issues.append({'id':right['id'],'kind':'caption-continuation','requiresId':left['id'],
                           'reason':'原音相邻字幕的助动词“'+modal+'”与后句谓词连续，当前删句/调序/删字拆断正常表达；保留完整连续内容组，不能把字幕分句当作失败起句'})
    return issues


def hold_reason(row,indices,segments=()):
    text='';positions=[];removed=set(row.get('removed',[]))
    for i,w in enumerate(row['words']):
        if i in removed:continue
        text+=w['word'];positions.extend([i]*len(w['word']))
    quote=''.join(row['words'][i]['word'] for i in indices if i not in removed)
    plain=''.join(c for c in quote if c.isalnum())
    # 可以 + 以某种成本/方式, 得以 + 以某身份, etc. Two grammatical roles
    # are not a failed copy. Do not invent a general ban on whole-clause edits.
    selected=set(indices)
    # In “对，是的，是我…”, the first 是 confirms the question while the
    # second introduces the answer's subject. A repeated character is not
    # evidence that either grammatical role was a failed take. Whole opening
    # edits remain possible; this narrow hold concerns a lone 是 only.
    if plain=='是':
        for match in re.finditer(r'是的[\s，,。；;、]*是(?=[我你他她它这那本])',text):
            boundary={positions[match.start()],positions[match.end()-1]}
            if selected&boundary:return '确认应答和后续判断各有语法作用，不能把单字是当成重说删除'
    if plain and len(plain)<=2 and set(plain)=={'以'}:
        for match in re.finditer(r'(?:可以|得以|足以|予以)以',text):
            boundary=set(positions[match.end()-2:match.end()])
            if selected&boundary:return REASON
    # A caption break can occur between a modal and its predicate. This narrow
    # dependency hold does not authorize restoring a deleted/reordered answer.
    if plain in ('可以','能够','应该','需要') and indices:
        if any(i>indices[-1] and i not in removed and any(c.isalnum() for c in w['word']) for i,w in enumerate(row['words'])):return None
        kept=[r for r in segments if not r.get('deleted')]
        at=next((i for i,r in enumerate(kept) if r['id']==row['id']),None)
        if at is not None and at+1<len(kept):
            following=kept[at+1]
            end=row.get('end',row['words'][-1]['end']);start=following.get('start',following['words'][0]['start'])
            if not -.2<=start-end<=1:return None
            if row.get('speaker') and following.get('speaker') and row['speaker']!=following['speaker']:return None
            next_text=''.join(w['word'] for i,w in enumerate(following['words']) if i not in following.get('removed',[]))
            next_text=re.sub(r'^[\s，,。.!！?？；;、呃嗯额啊哦]+','',next_text)
            if next_text.startswith(('让','用','去','把','将','做','继续','直接','通过','按照','选择','获得','得到','成为','创造')):
                return '后句承接助动词的完整表达，不能把字幕换行当作失败起句'
    return None
