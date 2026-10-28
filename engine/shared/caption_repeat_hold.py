"""Conservative restoration of a new literal restart across caption rows.

A caption boundary is not a phoneme boundary. Never erase a repeated source
anchor to force an output; restore the first original copy, then let the same
independent semantic review and acoustic preflight decide again.
"""
import re

VERSION=1


def eligible(before,edited,cut,edges,source):
    from speech_refine import FACT
    from pacing import word_index
    if cut.get('kind') not in ('repeat','falseStart'):return False
    plain=''.join(c for c in cut.get('quote','') if c.isalnum())
    if not re.fullmatch(r'[\u4e00-\u9fff]{1,6}',plain) or FACT.search(plain):return False
    indices=cut['indices'];left=next((i for i,r in enumerate(before) if r['id']==cut['id']),None)
    if left is None or left+1>=len(before):return False
    old,row=before[left],edited[left];peer_old,peer=before[left+1],edited[left+1]
    if peer_old.get('deleted') or peer.get('deleted') or any(r.get('audioFragment') for r in (old,row,peer_old,peer)):return False
    if indices!=sorted(set(indices)):return False
    if any(any(c.isalnum() for c in row['words'][i]['word']) and i not in indices for i in range(indices[0],len(row['words']))):return False
    if (len(old['words'])!=len(row['words']) or len(peer_old['words'])!=len(peer['words']) or
        any(a['word']!=b['word'] for a,b in zip(old['words'],row['words'])) or
        any(a['word']!=b['word'] for a,b in zip(peer_old['words'],peer['words']))):return False
    following=[];text=''
    for i,w in enumerate(peer['words']):
        spoken=''.join(c for c in w['word'] if c.isalnum())
        if not spoken:continue
        if i in peer_old.get('removed',[]) or i in peer.get('removed',[]):return False
        following.append(i);text+=spoken
        if len(text)>=len(plain):break
    if text!=plain or not following:return False
    # Both copies must be directly adjacent in the immutable complete source,
    # not merely next to each other after reordering/deleting other content.
    refs={r['id']:r for r in source}
    if old['id'] not in refs or peer['id'] not in refs:return False
    for r in (old,peer_old):
        if [w['word'] for w in refs[r['id']]['words']]!=[w['word'] for w in r['words']]:return False
    flat,positions=word_index(source)
    a=positions.get(f"{old['id']}:{indices[-1]}");b=positions.get(f"{peer['id']}:{following[0]}")
    if a is None or b is None or b<=a or any(any(c.isalnum() for c in w['word']) for w in flat[a+1:b]):return False
    gap=flat[b]['start']-flat[a]['end']
    if not -.12<=gap<=.9:return False
    return any(e.get('id')==peer['id'] and e.get('side')=='start' and e.get('wordIndex')==following[0]
               and e.get('word')==peer['words'][following[0]]['word'] for e in edges)
