"""Cancel only this run's automatic filler cut contradicted after encoding.

No new cuts or time guesses. Prior/manual cuts and normal speech are immutable.
Proposal alone never permits delivery: independent text review and the same
source-bound acoustic and actual encoded movie checks must run again.
"""
import copy,re
import encoded_cut_hold,speech_rollback

VERSION=1


def propose(before,edited,speech,audit,rendered):
    prior={r['id']:r for r in before};current={r['id']:r for r in edited}
    if [r['id'] for r in before]!=[r['id'] for r in edited]:return None
    eligible=[]
    for cut in speech.get('cuts',[]):
        old=prior.get(cut.get('id'));row=current.get(cut.get('id'));indices=cut.get('indices',[])
        if not old or not row or old['deleted'] or row['deleted'] or cut.get('automatic') is not True or cut.get('kind')!='filler':continue
        if not indices or indices!=sorted(set(indices)) or any(type(i) is not int or not 0<=i<len(row['words']) for i in indices):continue
        if [w['word'] for w in old['words']]!=[w['word'] for w in row['words']] or set(indices)&set(old['removed']) or not set(indices)<=set(row['removed']):continue
        quote=''.join(row['words'][i]['word'] for i in indices)
        if quote!=cut.get('quote') or not re.fullmatch('[呃嗯啊额哦]+',''.join(c for c in quote if c.isalnum())):continue
        eligible.append(cut)
    if not eligible:return None
    local=audit.get('localSeams') or {}
    if local.get('status')!='checked' or local.get('actualEncodedMovie') is not True:
        raise ValueError('实际成片的删词接缝还未完成声音复核，原稿与输出已保留，不能计为清理完成')
    matched=[]
    for index in range(len(audit.get('differences',[]))):
        try:target=encoded_cut_hold.candidate(audit,index,rendered)
        except ValueError:continue
        for cut in eligible:
            if cut['id']==target['id'] and cut['indices']==target['indices'] and cut not in matched:matched.append(cut)
    if not matched:return None
    restored,changed,held=speech_rollback.propose(before,edited,matched)
    if not held:return None
    revised=copy.deepcopy(speech)
    # Keep every unrelated accepted or held proposal exactly as it was.
    for cut in revised['cuts']:
        replacement=next((c for c in changed if c.get('key')==cut.get('key') and c['id']==cut['id'] and c['indices']==cut['indices']),None)
        if replacement:
            cut.update(replacement);cut['holdReason']='实际成片两次局部识别仍提示这处语气词，本轮保留原词与原声供回听';cut['encodedRollback']=True
    return restored,revised,{'version':VERSION,'held':held,'authority':'cancel-own-automatic-cut-after-encoded-evidence',
                            'changedNormalWords':False,'restoredPriorCuts':False,'requiresIndependentReview':True,'requiresAcousticRecheck':True}
