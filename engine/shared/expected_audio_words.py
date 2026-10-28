"""Read-only coverage of intended source words in physical output clips.

An empty optional clip word table must not erase a retained sentence from the
audio check. Logical first/last indices bind the intended raw words; they do
not certify that those phonemes survived the physical cut. ASR still checks
the actual encoded movie, and caption spelling is never speech evidence.
"""
import copy,math

VERSION=1

class CoverageError(ValueError):
    pass


def lexical(word):
    return isinstance(word,str) and any(c.isalnum() for c in word)


def resolve(project):
    if not isinstance(project.get('clips'),list):raise CoverageError('成片片段记录不完整')
    rows=project.get('segments');refs=None
    if rows is not None:
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in rows):
            raise CoverageError('成片原字归属记录不完整')
        refs={r['id']:r for r in rows}
        if len(refs)!=len(rows):raise CoverageError('成片原字归属重复')
    out=[];recovered=[];used=set()
    for position,clip in enumerate(project['clips']):
        if not isinstance(clip,dict):raise CoverageError('成片片段记录无效')
        words=clip.get('words',[])
        if not isinstance(words,list) or any(not isinstance(w,dict) or not isinstance(w.get('word'),str) for w in words):raise CoverageError('成片字音表无效')
        # Older owned projects have only a populated physical word table. Keep
        # that format compatible; an empty table is never sufficient evidence.
        if refs is None:
            if not any(lexical(w.get('word')) for w in words):raise CoverageError('成片片段缺少可核对的原字')
            out.append(copy.deepcopy(words));continue
        row=refs.get(clip.get('id'))
        if row is None or row.get('deleted'):raise CoverageError('成片片段引用了未保留原句')
        raw=row.get('words');removed=row.get('removed',[])
        if (not isinstance(raw,list) or any(not isinstance(w,dict) or not isinstance(w.get('word'),str) for w in raw) or not isinstance(removed,list)
            or any(type(i) is not int or not 0<=i<len(raw) for i in removed)
            or len(set(removed))!=len(removed)):
            raise CoverageError('成片原字删减记录无效')
        first,last=clip.get('firstIndex'),clip.get('lastIndex')
        bounded=type(first) is int and type(last) is int and 0<=first<=last<len(raw)
        if not bounded:
            if not words:raise CoverageError('空字音表缺少明确的原字范围')
            if 'firstIndex' in clip or 'lastIndex' in clip:raise CoverageError('成片原字范围无效')
            # Legacy clips with source rows can still use their explicit word
            # references, but cannot reconstruct any unbound missing word.
            wanted={w.get('index') for w in words}
        else:
            wanted={i for i in range(first,last+1) if i not in removed}
        if not words:
            words=[{**copy.deepcopy(raw[i]),'index':i} for i in sorted(wanted)]
            recovered.append({'clipIndex':position,'id':row['id'],'firstIndex':first,'lastIndex':last})
        seen=set()
        for word in words:
            index=word.get('index')
            if (type(index) is not int or index not in wanted or not 0<=index<len(raw)
                or index in removed or index in seen or word.get('word')!=raw[index].get('word')):
                raise CoverageError('成片字音表与保留原字不一致')
            seen.add(index)
            if any(type(word.get(k)) not in (int,float) or not math.isfinite(word[k]) for k in ('start','end')) or word['end']<word['start']:
                raise CoverageError('成片原字时间记录无效')
            if lexical(word['word']):
                ref=(row['id'],index)
                if ref in used:raise CoverageError('同一保留原字被多个片段重复引用')
                used.add(ref)
        expected={i for i in wanted if lexical(raw[i].get('word'))}
        if not expected or {i for i in seen if lexical(raw[i].get('word'))}!=expected:
            raise CoverageError('成片字音表未覆盖完整保留原字')
        if [w['index'] for w in words]!=sorted(w['index'] for w in words):raise CoverageError('成片字音表顺序不一致')
        out.append(copy.deepcopy(words))
    return out,{'version':VERSION,'recoveredClips':recovered,'recoveredClipCount':len(recovered),'changedSpeech':False}
