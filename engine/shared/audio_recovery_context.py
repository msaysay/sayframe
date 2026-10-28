"""Source-owned neighbors for bounded semantic repair of unsafe seams.

These are optional original text candidates, never cutting times or automatic
restoration. Only the validated current editable transcript grants authority.
"""
import copy
VERSION=3
RULE='声音切口无法安全分开时，先看boundaryNeighbors的原音连续关系。restoreAllowed=true才可补回当前仍有编辑权限、仅本方案舍弃的完整邻句；优先考虑连贯内容组再独立复核。不恢复创作者已删字/整句，不补造台词、不使用建议时间切音、不丢失已确认内容。无法形成安全新方案就说明，不能原样重交同一问题接缝。'

def boundaries(blocking):
    """Offer original context at source mismatch ends, never word replacements."""
    out=[]
    for issue in blocking:
        if not isinstance(issue,dict):continue
        if issue.get('side') in ('start','end') and issue.get('id'):out.append(issue)
        out.extend(e for e in issue.get('boundaryEdges',[]) if isinstance(e,dict))
        ids=issue.get('ids');evidence=issue.get('sourceEvidence')
        if (issue.get('reason')=='保留原话与两次原音核对未能一致对应' and isinstance(ids,list) and ids
            and isinstance(evidence,dict) and isinstance(evidence.get('expected'),str)
            and isinstance(evidence.get('recognizedWindows'),list) and len(evidence['recognizedWindows'])==2):
            out.extend([{'id':ids[0],'side':'start'},{'id':ids[-1],'side':'end'}])
    return out

def recovery_failures(blocking):
    return [b for b in blocking if isinstance(b,dict) and
            ('无可靠安静区间' in b.get('reason','') or b.get('boundaryEdges') or
             b.get('reason')=='保留原话与两次原音核对未能一致对应')]

def neighbors(source,editable_rows,plan,blocking):
    originals=source['segments'];positions={r['id']:i for i,r in enumerate(originals)}
    editable={r['id']:r for r in editable_rows};drop=set(plan.get('drop',[]));out=[];seen=set()
    for issue in boundaries(blocking):
        sid=issue.get('id');side=issue.get('side')
        if sid not in positions or sid not in editable or side not in ('start','end'):continue
        at=positions[sid];other=at-1 if side=='start' else at+1
        if not 0<=other<len(originals):continue
        target=originals[at];adjacent=originals[other];key=(sid,side,adjacent['id'])
        if key in seen:continue
        seen.add(key)
        try:gap=target['start']-adjacent['end'] if side=='start' else adjacent['start']-target['end']
        except KeyError:continue
        if not -.2<=gap<=1:continue
        if target.get('speaker') and adjacent.get('speaker') and target['speaker']!=adjacent['speaker']:continue
        available=editable.get(adjacent['id'])
        item={'targetId':sid,'side':side,'neighborId':adjacent['id'],'sourceAdjacent':True,'originalGapSeconds':round(gap,3),
              'restoreAllowed':bool(available and adjacent['id'] in drop),
              'availability':'plan-dropped-currently-editable' if available and adjacent['id'] in drop else 'already-kept' if available else 'not-in-current-editable-transcript'}
        # Only current corrected/retained text may be proposed for restoration.
        # Never leak an original user-deleted prefix back into a candidate.
        if available:item['neighborText']=available['text']
        out.append(item)
    return out

def unchanged_unsafe_seams(context,approved_kept,new_kept,approved_plan=None,new_plan=None):
    """Do not spend another alignment/render on an identical proven bad seam.

    Only apply when the failure actually identified a no-quiet boundary and a
    permitted dropped neighbor was supplied. Other recovery changes may still
    be useful, so this does not impose a blanket 'order must change' rule.
    """
    if list(approved_kept)!=list(new_kept):return []
    if approved_plan is not None and new_plan is not None:
        if any(approved_plan.get(k,[])!=new_plan.get(k,[]) for k in ('wordEdits','questionCuts','repetitions')):return []
    return [copy.deepcopy(c) for c in context if c['restoreAllowed']]

def expand_focus(focused,all_rows,source,previous,feedback):
    """Make permitted recovery candidates legal planner inputs, not just hints.

    Recompute permission from the server's original source and current editable
    rows. Client/model restoreAllowed flags never grant new source access.
    """
    if focused is all_rows or not isinstance(previous,dict) or not isinstance(previous.get('plan'),dict) or not isinstance(feedback,dict) or feedback.get('stage')!='audio-boundaries':return focused,None
    blocking=feedback.get('blocking',[])
    if not isinstance(blocking,list):return focused,None
    candidates=neighbors(source,all_rows,previous['plan'],recovery_failures(blocking))
    existing={r['id'] for r in focused};added=[c['neighborId'] for c in candidates if c['restoreAllowed'] and c['neighborId'] not in existing]
    if not added:return focused,None
    allowed=existing|set(added)
    expanded=[r for r in all_rows if r['id'] in allowed]
    receipt={'version':VERSION,'beforeIds':[r['id'] for r in focused],'addedIds':added,'afterIds':[r['id'] for r in expanded],
             'authority':'original-source-adjacency-and-current-editable-transcript','candidates':candidates,'insertedIntoProject':False}
    return expanded,receipt
