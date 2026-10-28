"""Rollback this run's calibrated timing and its automatic word cuts together.

Never restores a prior/manual deletion, selects sentences, guesses a timestamp
or approves an output. Caller must review restored text and re-run preflight.
"""
import copy
VERSION=1
REASON='新声音校准未通过成片核对，本次保留原话和原声音边界'

def restore(project,edited,speech,alignment,blocking):
    if not alignment.get('applied') or not alignment.get('rows'):return None
    changed=set(alignment['rows'])
    edges=[e for issue in blocking for e in issue.get('boundaryEdges',[])]
    if not any(e.get('id') in changed for e in edges):return None
    before=project['segments']
    if [r['id'] for r in before]!=[r['id'] for r in edited]:return None
    originals={r['id']:r for r in before};cuts=copy.deepcopy(speech['cuts']);new_by_row={}
    for cut in cuts:
        if cut.get('automatic') is not True or cut.get('id') not in changed:continue
        row=originals.get(cut['id']);indices=cut.get('indices',[])
        if row is None or not indices or any(type(i) is not int or not 0<=i<len(row['words']) for i in indices):return None
        if set(indices)&set(row.get('removed',[])) or ''.join(row['words'][i]['word'] for i in indices)!=cut.get('quote'):return None
        new_by_row.setdefault(row['id'],set()).update(indices)
    if not new_by_row:return None
    restored=copy.deepcopy(edited)
    for row in restored:
        old=originals[row['id']]
        if row.get('deleted')!=old.get('deleted') or [w['word'] for w in row['words']]!=[w['word'] for w in old['words']]:return None
        if row['id'] in changed:
            base=set(old.get('removed',[]));actual=set(row.get('removed',[]))
            if not base<=actual or actual-base!=new_by_row.get(row['id'],set()):return None
            row['removed']=copy.deepcopy(old['removed'])
        # Reverting the immutable source means every row must use THAT source's
        # original timing, even when an unaffected row also has an auto cut.
        for name in ('words','start','end'):
            if name in old:row[name]=copy.deepcopy(old[name])
    held=[]
    for cut in cuts:
        if cut.get('automatic') is True and cut.get('id') in new_by_row:
            cut.update(automatic=False,holdReason=REASON,dismissed=False,calibrationRollback=True)
            held.append({k:copy.deepcopy(cut[k]) for k in ('id','indices','quote','kind')})
    return restored,{**copy.deepcopy(speech),'cuts':cuts},{'version':VERSION,'rows':sorted(changed),'held':held,'reason':REASON}
