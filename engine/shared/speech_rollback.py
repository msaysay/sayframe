"""Restore this run's uncertain interjection or failed-edge literal-repeat cut.

Manual/previous cuts, unrelated repeats, normal wording, timings and order stay.
A caller must independently review the actual restored text and re-run the full
acoustic gate; this helper is never permission to export a failed sound edit.
"""
import copy,re
VERSION=3
REASON='合成后的声音核对未通过，本次保留原声供回听'


def edge_repeat(old,row,cut,boundary_edges):
    """Only an unchanged, freshly cut first copy next to a real failed edge.

    Restoring a repeated original phrase is not a successful cleanup or a
    phonetic equivalence. Existing cuts and nonliteral failed starts stay out.
    """
    from speech_refine import FACT
    indices=cut['indices'];plain=''.join(c for c in cut['quote'] if c.isalnum())
    if cut.get('kind')!='repeat' or not re.fullmatch(r'[\u4e00-\u9fff]{1,6}',plain) or FACT.search(plain):return False
    if indices!=sorted(set(indices)) or any(any(c.isalnum() for c in row['words'][i]['word']) and i not in indices for i in range(indices[0],indices[-1]+1)):return False
    if len(old['words'])!=len(row['words']) or any(a['word']!=b['word'] for a,b in zip(old['words'],row['words'])):return False
    following=[];text=''
    for i in range(indices[-1]+1,len(row['words'])):
        word=row['words'][i]['word'];spoken=''.join(c for c in word if c.isalnum())
        if not spoken:continue
        if i in old.get('removed',[]) or i in row.get('removed',[]):return False
        following.append(i);text+=spoken
        if len(text)>=len(plain):break
    if text!=plain:return False
    for edge in boundary_edges:
        if edge.get('id')!=row['id'] or edge.get('side') not in ('start','end'):continue
        at=edge.get('wordIndex')
        if type(at) is not int or not 0<=at<len(row['words']) or at in row.get('removed',[]) or row['words'][at]['word']!=edge.get('word'):continue
        if not any(c.isalnum() for c in row['words'][at]['word']):continue
        # A physical end before the deletion, or a physical start after it.
        if edge['side']=='end' and at<indices[0]:between=range(at+1,indices[0])
        elif edge['side']=='start' and at>indices[-1]:between=range(indices[-1]+1,at)
        else:continue
        if all(not any(c.isalnum() for c in row['words'][i]['word']) for i in between):return True
    return False

def propose(before,edited,cuts,boundary_edges=(),source_rows=()):
    original={r['id']:r for r in before};rows={r['id']:r for r in edited}
    out=copy.deepcopy(edited);lookup={r['id']:r for r in out};revised=copy.deepcopy(cuts);held=[]
    if [r['id'] for r in before]!=[r['id'] for r in edited]:return out,revised,held
    for cut in revised:
        sid=cut.get('id');old=original.get(sid);row=rows.get(sid);indices=cut.get('indices',[])
        if not old or not row or old.get('deleted') or row.get('deleted') or cut.get('automatic') is not True:continue
        if not indices or any(type(i) is not int or i<0 or i>=len(row['words']) for i in indices):continue
        quote=''.join(row['words'][i]['word'] for i in indices)
        plain=''.join(c for c in quote if c.isalnum())
        if quote!=cut.get('quote'):continue
        if set(indices)&set(old.get('removed',[])) or not set(indices)<=set(row.get('removed',[])):continue
        if any(i>=len(old['words']) or old['words'][i]['word']!=row['words'][i]['word'] for i in indices):continue
        filler=cut.get('kind')=='filler' and re.fullmatch('[呃嗯额啊哦]+',plain)
        repeat=edge_repeat(old,row,cut,boundary_edges) if boundary_edges else False
        if not repeat and boundary_edges and source_rows:
            repeat=__import__('caption_repeat_hold').eligible(before,edited,cut,boundary_edges,source_rows)
        if not (filler or repeat):continue
        lookup[sid]['removed']=[i for i in lookup[sid].get('removed',[]) if i not in indices]
        cut.update(automatic=False,holdReason=REASON,dismissed=False,acousticRollback=True)
        held.append({'id':sid,'indices':list(indices),'quote':quote,'reason':REASON,'kind':cut['kind']})
    return out,revised,held
