"""Owned audio worker. No server imports, project generation or model rewrite."""
import copy,json,re,subprocess,sys
from pathlib import Path
import numpy as np
from precise_speech import CharacterAcoustics,matched_anchors,coordinate_words,spoken

def edge_anchor_allowed(anchors,peers,at,selected):
    a=anchors[at];b=peers[at]
    if not a.get('matched',True) or not b.get('matched',True) or min(a['probability'],b['probability'])<.55 or abs(a['time']-b['time'])>.08:return False
    # A jointly recognized AI/MCN/SOP token is safe as a WHOLE endpoint, never
    # as a guessed independent letter. Both contexts must retain its group.
    for trace,anchor in ((anchors,a),(peers,b)):
        if anchor['shared'] and any(i not in selected for i,t in enumerate(trace) if t['group']==anchor['group']):return False
    return True

def boundary_text_matches(expected,heard):
    """Compare the two physical edges without rejecting interior ASR homophones."""
    from speech_boundary_text import matches
    return matches(expected,heard)

def choose_quiet_run(runs,center,neighbor,side,reference=None):
    if not runs:return None
    point=sum(runs[0])/2
    if reference is None or abs(point-reference)<=1.2:return point
    # A long pause fragmented by room noise is not the next word's onset.
    # Keep the usual FIRST-gap strategy for ordinary seams. Only when that
    # strategy would fail the existing displacement guard, look for the first
    # sustained (>=120ms) quiet run near the independently anchored next word.
    # Exclude its last 150ms: a weak consonant before the CTC emission must not
    # become the cut. No nearby broad gap means refusal, not a peak fallback.
    if side!='start' or center-neighbor<=1.2:return point
    lo=max(neighbor+.07,center-.8);hi=center-.15
    for a,b in runs:
        a=max(a,lo);b=min(b,hi)
        if b-a>=.12-1e-6:
            candidate=(a+b)/2
            if abs(candidate-reference)<=1.2:return candidate
    return None


def quiet_cut(audio,offset,center,neighbor,side,reference=None):
    # Find a sustained quiet interval between recognized token occurrences.
    # CTC peaks are not phoneme boundaries; do not cut at the peak itself.
    # Leave room for consonants before a CTC emission and for voiced release
    # after it. A low-energy consonant must not be mistaken for the gap.
    lo,hi=(neighbor+.07,center-.07) if side=='start' else (center+.07,neighbor-.07)
    lo=max(offset,lo);hi=min(offset+len(audio)/16000,hi)
    if hi-lo<.04:return None
    levels=[]
    for i in range(0,len(audio)-159,160):
        levels.append(float(np.sqrt(np.mean(audio[i:i+160]**2))))
    levels=np.asarray(levels);floor=float(np.quantile(levels,.15)) if len(levels) else 0
    # Raw interview noise is often far above digital silence. Use this
    # window's noise floor, bounded below its typical spoken energy.
    threshold=max(.002,min(floor*1.8,float(np.median(levels))*.75))
    a=max(0,int(np.ceil((lo-offset)*100)));b=min(len(levels),int(np.floor((hi-offset)*100)))
    runs=[];start=None
    for n in range(a,b+1):
        quiet=n<b and levels[n]<=threshold
        if quiet and start is None:start=n
        if not quiet and start is not None:
            if n-start>=4:runs.append((offset+start*.01,offset+n*.01))
            start=None
    return choose_quiet_run(runs,center,neighbor,side,reference)

def groups_for(clips,source):
    positions={r['id']:i for i,r in enumerate(source)};groups=[]
    for i,c in enumerate(clips):
        if groups:
            prev=clips[groups[-1][-1]]
            adjacent=positions[c['id']] in (positions[prev['id']],positions[prev['id']]+1)
            if adjacent and c['start']>=prev['start'] and c['end']-clips[groups[-1][0]]['start']<45:
                groups[-1].append(i);continue
        groups.append([i])
    return groups

def calibrate(request):
    model=CharacterAcoustics(request['model']);source=request['source'];refs={r['id']:r for r in source['segments']}
    result=copy.deepcopy(request['clips']);entries=[];blocking=[];extras=[];edges=request.get('edges',{});source_edges={}
    frozen=request.get('frozenClips',[])
    frozen_indices=__import__('frozen_clip_bounds').indices(result,frozen) if frozen else set()
    from source_edge_evidence import trace as source_trace,observation,resolve
    from clip_calibration import continuity_links,source_links,source_mismatch
    continuous=continuity_links(result,source['segments'],edges)
    adjacent=source_links(result,source['segments'],edges)
    preserved={p['id']:p for p in request.get('preservedOuterEdges',[])}
    verified_preserved={}
    for indices in groups_for(result,source['segments']):
        ids=list(dict.fromkeys(result[i]['id'] for i in indices));members=[refs[sid] for sid in ids];offsets={};words=[]
        for r in members:offsets[r['id']]=len(words);words.extend(r['words'])
        row={'start':members[0]['start'],'end':members[-1]['end'],'words':words,'text':''.join(w['word'] for w in words)}
        def window(pad):
            start=max(0,row['start']-pad);end=min(source['duration'],row['end']+pad)
            data=subprocess.check_output([request['ffmpeg'],'-v','error','-ss',str(start),'-i',request['video'],'-t',str(end-start),'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'])
            audio=np.frombuffer(data,dtype='<f4').copy();return audio,start,source_trace(model,audio,start)
        audio,start,trace=window(1.3);other,other_start,second=window(.9)
        a=matched_anchors(row,trace);b=matched_anchors(row,second)
        if (a is None or b is None) and indices[-1] in continuous:
            # A 45-second model window is an implementation boundary, not an
            # audio cut. Include the next continuously retained source row when
            # a terminal erhua syllable was omitted by local recognition.
            next_row=refs[result[indices[-1]+1]['id']]
            if next_row['id'] not in ids:
                offsets[next_row['id']]=len(words);words.extend(next_row['words']);row={**row,'end':next_row['end'],'words':words}
                audio,start,trace=window(1.3);other,other_start,second=window(.9)
                a=matched_anchors(row,trace);b=matched_anchors(row,second)
        if (a is None or b is None) and ids[-1] in preserved:
            candidate=next((c for c in result if c['id']==ids[-1]),None)
            from preserved_edge_recovery import eligible
            from preserved_edge_review import verify
            proof=preserved[ids[-1]]
            if candidate and eligible(candidate,refs[ids[-1]],edges,frozen) and verify(proof,{**candidate,'end':proof['point']},request['video'],request['ffmpeg'],Path(__file__).resolve().parent/'recognition-cache',model=model):
                a=matched_anchors(row,trace,provisional_end=True);b=matched_anchors(row,second,provisional_end=True)
                if a is not None and b is not None:verified_preserved[ids[-1]]=proof
        if a is None or b is None:
            blocking.append(source_mismatch(ids,row,trace,second));continue
        timed=coordinate_words(row,a,b)
        if timed is None:blocking.append({'ids':ids,'reason':'原词声音定位不一致'});continue
        char_offsets=[];n=0
        for w in words:char_offsets.append(n);n+=len(spoken(w['word']))
        from acoustic_restarts import detect
        for restart in detect(''.join(w['word'] for w in words),''.join(t['text'] for t in trace),''.join(t['text'] for t in second)):
            at=min(restart['offset'],n-1)
            word_index=next((i for i,w in enumerate(words) if char_offsets[i]<=at<char_offsets[i]+len(spoken(w['word']))),None)
            if word_index is None:continue
            for index in indices:
                c=result[index];base=offsets[c['id']]
                if base+c['firstIndex']<=word_index<=base+c['lastIndex']:
                    extras.append({**restart,'id':c['id'],'sourceWordIndex':word_index-base,'status':'待声音校准，不自动删字或强切'})
                    break
        for index in indices:
            c=result[index];r=refs[c['id']];base=offsets[c['id']]
            for wi in range(c['firstIndex'],c['lastIndex']+1):
                at=char_offsets[base+wi];chars=spoken(r['words'][wi]['word'])
                source_edges[(c['id'],wi)]=[observation(ch,a[at+n],b[at+n],trace,second) for n,ch in enumerate(chars)]
            if c.get('audioFragment'):
                entries.append({'id':c['id'],'skipped':'用户段中裁除保持原设置'});continue
            local=timed[base:base+len(r['words'])]
            new_words=[]
            for w in c.get('words',[]):
                new_words.append({**w,**local[w['index']]})
            first=next((i for i in range(c['firstIndex'],c['lastIndex']+1) if spoken(r['words'][i]['word'])),None)
            last=next((i for i in range(c['lastIndex'],c['firstIndex']-1,-1) if spoken(r['words'][i]['word'])),None)
            if first is None:continue
            if index in frozen_indices:
                __import__('frozen_clip_bounds').guard_margin(c,local,first,last,request.get('frozenPaddingRetractions',[]))
            # Only physical run edges need silence. Interior adjacent kept
            # speech is decoded together, never clipped at each sentence label.
            key=f"{c['id']}:{c['firstIndex']}:{c['lastIndex']}";manual=edges.get(key,{})
            before_spoken=next((i for i in range(c['firstIndex']-1,-1,-1) if spoken(r['words'][i]['word'])),None)
            after_spoken=next((i for i in range(c['lastIndex']+1,len(r['words'])) if spoken(r['words'][i]['word'])),None)
            protected_start=before_spoken is not None or c.get('audioFragment') or 'start' in manual or index in frozen_indices
            protected_end=after_spoken is not None or c.get('audioFragment') or 'end' in manual or index in frozen_indices
            points={};note={'id':c['id'],'indices':[c['firstIndex'],c['lastIndex']],'before':[c['start'],c['end']]}
            for side,wi,protected in [('start',first,protected_start),('end',last,protected_end)]:
                if protected:continue
                if (index-1 if side=='start' else index) in continuous:
                    # No sound cut exists here. Keep the full continuous source
                    # and calibrate only the actual run edges; caption alignment
                    # uncertainty cannot justify cutting or duplicating sound.
                    note.setdefault('continuousSides',[]).append(side);continue
                at=char_offsets[base+wi]+(len(spoken(r['words'][wi]['word']))-1 if side=='end' else 0)
                anchor=a[at];peer=b[at]
                kept_chars=set(range(char_offsets[base+first],char_offsets[base+last]+len(spoken(r['words'][last]['word']))))
                if side=='end' and c['id'] in verified_preserved:
                    points[side]=verified_preserved[c['id']]['point']
                    note['preservedOuterEdge']=verified_preserved[c['id']]
                    continue
                if not edge_anchor_allowed(a,b,at,kept_chars):
                    blocking.append({'id':c['id'],'side':side,'reason':'句首或句尾原字无法稳定定位'});continue
                center=anchor['time'];neighbors=[t['time'] for t in trace if t['time']<center-.02] if side=='start' else [t['time'] for t in trace if t['time']>center+.02]
                neighbor=max(neighbors,default=center-.7) if side=='start' else min(neighbors,default=center+.7)
                point=quiet_cut(audio,start,center,neighbor,side,c[side])
                # Continuous retained neighbors may share a non-quiet word
                # seam: the encoder will never cut there after normalization.
                internal=(index!=indices[0] if side=='start' else index!=indices[-1])
                if point is None and internal:point=(neighbor+center)/2
                if point is None:
                    blocking.append({'id':c['id'],'side':side,'reason':'切口附近无可靠安静区间，需回听'});continue
                # Coarse attention timestamps can invent a long gap between
                # adjacent source words. Two agreeing, directly neighboring
                # token anchors can join them; that seam is never encoded as
                # a physical cut, so no phoneme is trimmed at its midpoint.
                link=(index-1 if side=='start' else index)
                acoustic_join=internal and link in adjacent and abs(neighbor-center)<=.5
                if abs(point-c[side])>1.2 and not acoustic_join:
                    blocking.append({'id':c['id'],'side':side,'reason':'切口偏移过大，需核对原文归属'});continue
                points[side]=point
                note.setdefault('edgeEvidence',{})[side]={'center':center,'peerCenter':peer['time'],'neighbor':neighbor,'point':point,'displacement':point-c[side]}
            c.update(points);c['words']=new_words
            c['wordStart']=local[first]['start'];c['wordEnd']=local[last]['end']
            note['after']=[c['start'],c['end']];entries.append(note)
    from clip_calibration import normalize_seams
    from render_spans import render_spans
    result=normalize_seams(result,source['segments'],edges,frozen)
    import cut_exclusions
    result,exclusion_report=cut_exclusions.constrain(result,request.get('verifiedExclusions',[]))
    if frozen:__import__('frozen_clip_bounds').verify(result,frozen)
    blocking.extend(exclusion_report['blocking'])
    audits=[]
    if not blocking:
        physical_spans=render_spans(result)
        for span_number,span in enumerate(physical_spans):
            if any(result[i].get('audioFragment') for i in span['indices']):
                audits.append({'indices':span['indices'],'skipped':'段中裁除已由用户设置，不改裁除边界'});continue
            raw=subprocess.check_output([request['ffmpeg'],'-v','error','-ss',str(span['start']),'-i',request['video'],'-t',str(span['end']-span['start']),'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'])
            heard=''.join(t['text'] for t in model.trace(np.frombuffer(raw,dtype='<f4')))
            expected=spoken(''.join(w['word'] for i in span['indices'] for w in refs[result[i]['id']]['words'][result[i]['firstIndex']:result[i]['lastIndex']+1]))
            # An interjection may be inaudible to ASR. It is still retained in
            # the audio; it is not replaced by an unrelated recognized prefix.
            left=result[span['indices'][0]];right=result[span['indices'][-1]]
            edge_for=lambda c:edges.get(f"{c['id']}:{c['firstIndex']}:{c['lastIndex']}",{})
            observations=[e for i in span['indices'] for wi in range(result[i]['firstIndex'],result[i]['lastIndex']+1) for e in source_edges.get((result[i]['id'],wi),[])]
            edge_evidence={'start':observations[:2],'end':observations[-2:]}
            checked=resolve(expected,heard,edge_evidence)
            start_match,end_match=checked['start'],checked['end']
            preserved_witness=verified_preserved.get(right['id'])
            if not end_match and preserved_witness and abs(span['end']-preserved_witness['point'])<1e-7:
                end_match=__import__('preserved_edge_review').verify(preserved_witness,right,request['video'],request['ffmpeg'],Path(__file__).resolve().parent/'recognition-cache',model=model)
            witness=None
            if not end_match:
                # This is not a missing-normal-word waiver: only a retained
                # literal interjection, two strong normal source words, and
                # the SAME actual pre-reviewed physical cut can qualify.
                witness=__import__('audited_cut_edges').resolve_end(expected,heard,observations,span,physical_spans[span_number+1] if span_number+1<len(physical_spans) else None,request.get('verifiedExclusions',[]),request['video'],Path(__file__).resolve().parent/'recognition-cache')
                if witness['passed']:end_match=True
            passed=('start' in edge_for(left) or start_match) and ('end' in edge_for(right) or end_match)
            audits.append({'indices':span['indices'],'expected':expected,'heard':heard,'passed':passed,'start':span['start'],'end':span['end'],'sourceEdgeEvidence':edge_evidence,'orthographyOnly':checked['orthographyOnly'],**({'sourceBoundCutWitness':witness} if witness is not None else {})})
            if not passed:blocking.append({'indices':span['indices'],'reason':'剪后原音句首或句尾与保留原话不一致'})
    return {'version':17,'method':'source-time-anchored-context-and-physical-run-quiet-edges','preservedOuterEdges':list(verified_preserved),'sourceAudioWitnessVersion':1,'clips':result,'entries':entries,'audits':audits,'blocking':blocking,'extraRestarts':extras,'verifiedExclusionBounds':exclusion_report,**({'frozenClipBoundsVersion':__import__('frozen_clip_bounds').VERSION} if frozen else {})}

if __name__=='__main__':
    path=Path(sys.argv[1]).resolve();root=Path(__file__).resolve().parent
    if path.parent!=root/'recognition-cache' or not re.fullmatch('clip-calibration-request-[a-f0-9]{32}\\.json',path.name):raise ValueError('切口请求路径无效')
    print(json.dumps(calibrate(json.loads(path.read_text('utf8'))),ensure_ascii=False))
