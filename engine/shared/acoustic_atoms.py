"""Complete acoustic tokens are atomic, never independent letter timestamps."""
import copy,math,re
VERSION=2

def plain(text):return ''.join(c for c in text if c.isalnum()).upper()

def annotate(words,anchors,peer):
    out=copy.deepcopy(words);offset=0;spans=[]
    for w in words:
        n=len(plain(w['word']));spans.append(list(range(offset,offset+n)));offset+=n
    if offset!=len(anchors) or len(anchors)!=len(peer):return out
    groups={}
    for n,a in enumerate(anchors):groups.setdefault(a['group'],[]).append(n)
    for group,positions in groups.items():
        if len(positions)<2:continue
        a=[anchors[n] for n in positions];b=[peer[n] for n in positions];peer_ids={x['group'] for x in b}
        complete=len(peer_ids)==1 and [n for n,x in enumerate(peer) if x['group'] in peer_ids]==positions
        exact=all(x.get('matched') and y.get('matched') and x['actual']==y['actual'] for x,y in zip(a,b))
        probability=min(x['probability'] for x in a+b);center=a[0]['time']
        stable=bool(complete and exact and probability>=.8 and all(abs(x['time']-y['time'])<=.08 for x,y in zip(a,b)))
        atom={'id':f'ctc:{group}@{center:.6f}','text':''.join(x['actual'] for x in a),'center':center,'probability':probability,'stable':stable,'characters':len(positions)}
        for i,span in enumerate(spans):
            if span and set(span).issubset(positions):out[i]['alignmentToken']=copy.deepcopy(atom)
    return out

def token_at(words,index):
    atom=words[index].get('alignmentToken')
    if not isinstance(atom,dict) or not atom.get('stable') or atom.get('probability',0)<.8:return None
    text=plain(atom.get('text',''))
    from speech_refine import FACT
    if not re.fullmatch(r'[A-Z\u4e00-\u9fff]{2,16}',text) or FACT.search(text) or text in ('NO','NOT','NEVER','WITHOUT'):return None
    center=atom.get('center')
    if not isinstance(center,(float,int)) or not math.isfinite(center):return None
    members=[i for i,w in enumerate(words) if isinstance(w.get('alignmentToken'),dict) and w['alignmentToken'].get('id')==atom['id']]
    if any(words[i]['alignmentToken']!=atom for i in members):return None
    if plain(''.join(words[i]['word'] for i in members))!=text or len(text)!=atom.get('characters'):return None
    return {**atom,'members':members}

def removal_evidence(words,indices,verified=False):
    selected=set(indices);tokens={};covered=set()
    for i,w in enumerate(words):
        if i not in selected or not plain(w['word']) or not w.get('alignmentToken'):continue
        atom=token_at(words,i)
        if not atom or not set(atom['members']).issubset(selected):return {'passed':False,'reason':'partial or weak acoustic token'}
        if verified and any(not words[n].get('alignmentVerified') or words[n].get('alignmentTokenVerified')!=atom['id'] for n in atom['members']):return {'passed':False,'reason':'token lacks actual removal audit'}
        tokens[atom['id']]=atom;covered.update(atom['members'])
    if not tokens:return {'passed':False,'reason':'no complete shared token'}
    for i in selected-covered:
        w=words[i]
        if not plain(w['word']):continue
        if not w.get('alignmentStable') or w.get('alignmentProbability',0)<.8 or plain(w.get('acousticRecognized',''))!=plain(w['word']):return {'passed':False,'reason':'weak companion removal'}
    return {'passed':True,'tokens':list(tokens.values()),'coveredIndices':sorted(covered)}
