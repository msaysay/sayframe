"""Expose failed physical edges without changing any audio acceptance rule."""
import copy
VERSION=2

def enrich(blocking,clips,audits):
    from source_edge_evidence import resolve
    out=copy.deepcopy(blocking)
    for issue in out:
        # The anchor worker can fail before a rendered-span audit exists.
        # Expose only the exact, uniquely identified clip edge for conservative
        # restoration. This is failed geometry context, never acoustic proof.
        if (issue.get('side') in ('start','end') and issue.get('reason') in
            ('句首或句尾原字无法稳定定位','切口附近无可靠安静区间，需回听')):
            candidates=[c for c in clips if c.get('id')==issue.get('id')]
            if len(candidates)==1:
                words=[w for w in candidates[0].get('words',[]) if any(c.isalnum() for c in w.get('word',''))]
                if words:
                    word=words[0] if issue['side']=='start' else words[-1]
                    if type(word.get('index')) is int:
                        issue['boundaryEdges']=[{'id':issue['id'],'side':issue['side'],'wordIndex':word['index'],'word':word['word'],
                                                'sourceEvidence':[],'evidenceKind':'unresolved-original-anchor'}]
        indices=issue.get('indices')
        if not isinstance(indices,list) or not indices or any(type(i) is not int or not 0<=i<len(clips) for i in indices):continue
        audit=next((a for a in audits if a.get('indices')==indices and a.get('passed') is False),None)
        if not audit or not isinstance(audit.get('expected'),str) or not isinstance(audit.get('heard'),str):continue
        checked=resolve(audit['expected'],audit['heard'],audit.get('sourceEdgeEvidence',{}));edges=[]
        for side,index in [('start',indices[0]),('end',indices[-1])]:
            if checked[side]:continue
            clip=clips[index];words=[w for w in clip.get('words',[]) if any(c.isalnum() for c in w.get('word',''))]
            if not words:continue
            word=words[0] if side=='start' else words[-1]
            if type(word.get('index')) is not int:continue
            edges.append({'id':clip['id'],'side':side,'wordIndex':word['index'],'word':word['word'],
                          'sourceEvidence':copy.deepcopy(audit.get('sourceEdgeEvidence',{}).get(side,[]))})
        if edges:issue['boundaryEdges']=edges
    return out
