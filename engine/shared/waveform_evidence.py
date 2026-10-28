"""Local waveform support for interior speech; never a word/cut verdict.

No phoneme labels or homophone equivalence. A fixed source core is compared
to nearby encoded sound with one global offset. No per-frame warping that
could hide a missing/repeated syllable. Boundary and speed cases abstain.
"""
import math,wave
import final_seams
VERSION=2
NOTE='只比较这一小段的声音形状，不判断具体字或整片质量。混音、降噪和位置误差也会造成差异；结果不授权删音。'


def measure(original,movie,original_point,movie_point,rate=16000):
    import numpy as np
    if rate!=16000 or any(not math.isfinite(float(n)) for n in [original_point,movie_point]):raise ValueError('波形位置无效')
    a=round((original_point-.35)*rate);b=a+round(.7*rate)
    lo=round((movie_point-.6)*rate);hi=lo+round(1.2*rate)
    if min(a,lo)<0 or b>len(original) or hi>len(movie):return {'status':'not-measured','reason':'可对照的上下文不足'}
    x=np.asarray(original[a:b],dtype=np.float64);y=np.asarray(movie[lo:hi],dtype=np.float64)
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):raise ValueError('波形采样无效')
    x=x-x.mean();norm=np.linalg.norm(x)
    if norm<1e-8:return {'status':'not-measured','reason':'这一小段没有足够人声能量'}
    n=len(x);s=np.r_[0,np.cumsum(y)];ss=np.r_[0,np.cumsum(y*y)]
    variance=np.maximum(0,(ss[n:]-ss[:-n])-(s[n:]-s[:-n])**2/n)
    scores=np.correlate(y,x,mode='valid')/np.maximum(1e-12,np.sqrt(variance)*norm)
    peak=int(np.argmax(scores));best=y[peak:peak+n];frames=[]
    for offset in range(0,n,800):
        u=x[offset:offset+800];v=best[offset:offset+800]
        if len(u)<800 or np.sqrt(np.mean(u*u))<.004:continue
        u=u-u.mean();v=v-v.mean();den=np.linalg.norm(u)*np.linalg.norm(v)
        frames.append(float(np.clip(np.dot(u,v)/max(den,1e-12),-1,1)))
    if len(frames)<6:return {'status':'not-measured','reason':'这一小段可用人声不足'}
    outside=np.abs(np.arange(len(scores))-peak)>round(.05*rate)
    contrast=float(scores[peak]-np.max(scores[outside])) if np.any(outside) else 0
    score=float(np.clip(scores[peak],-1,1));minimum=min(frames)
    return {'status':'measured','sourceCoreSeconds':[a/rate,b/rate],'movieCoreSeconds':[(lo+peak)/rate,(lo+peak+n)/rate],
            'peakCorrelation':round(score,6),'peakContrast':round(contrast,6),'voicedFrameCount':len(frames),
            'minimumFrameCorrelation':round(minimum,6),'medianFrameCorrelation':round(float(np.median(frames)),6),
            'summary':'这一小段的原音与成片波形接近，仍需结合回听' if score>=.98 and minimum>=.95 and contrast>=.1 else '这一小段的波形对照仍不确定，不能据此认定丢字'}


def run(pair,project,root):
    base={'version':VERSION,'note':NOTE,'changedSpeech':False}
    if project.get('settings',{}).get('noiseReduction','off')!='off':return {**base,'status':'not-measured','reason':'这段声音经过降噪，不能直接用波形判断是否丢字'}
    target=pair['target'];rows=[r for r in project['segments'] if r['id']==target['id']]
    if len(rows)!=1:return {**base,'status':'not-measured','reason':'原词记录不唯一'}
    word=rows[0]['words'][target['wordIndex']];point=word.get('acousticCenter',(word['start']+word['end'])/2)
    if type(point) not in (int,float) or not math.isfinite(point) or not word['start']<=point<=word['end']:point=(word['start']+word['end'])/2
    matches=[(i,c) for i,c in enumerate(project['clips']) if c['id']==target['id'] and any(w.get('index')==target['wordIndex'] for w in c.get('words',[]))]
    refs=[w for w in final_seams.timeline(project) if w['id']==target['id'] and w['wordIndex']==target['wordIndex']]
    if len(matches)!=1 or len(refs)!=1:return {**base,'status':'not-measured','reason':'实际取音记录不唯一'}
    _,clip=matches[0];ref=refs[0]
    if abs(clip.get('speed',project.get('settings',{}).get('speed',1))-1)>1e-6:return {**base,'status':'not-measured','reason':'倍速声音不能用同速波形直接对照'}
    if point-.35<clip['start'] or point+.35>clip['end'] or ref['nearSeconds']-.35<ref['clipStart'] or ref['nearSeconds']+.35>ref['clipEnd']:return {**base,'status':'not-measured','reason':'靠近剪切接缝，不能用段内波形代替切口检查'}
    audio={};excerpts={e['kind']:e for e in pair['excerpts']}
    import audio_comparison
    import numpy as np
    for kind,e in excerpts.items():
        path=root/e['url'].lstrip('/')
        if audio_comparison.digest(path)!=e['sha256']:raise ValueError('声音对照已变化')
        with wave.open(str(path),'rb') as w:
            if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000) or w.getnframes()>16000*7:raise ValueError('声音采样格式无效')
            audio[kind]=np.frombuffer(w.readframes(w.getnframes()),'<i2').astype(np.float64)/32768
        if audio_comparison.digest(path)!=e['sha256']:raise ValueError('声音对照已变化')
    value=measure(audio['original'],audio['movie'],point-excerpts['original']['window'][0],ref['nearSeconds']-excerpts['movie']['window'][0])
    if value['status']=='measured':
        a,b=value['movieCoreSeconds'];offset=excerpts['movie']['window'][0]
        if a+offset<ref['clipStart'] or b+offset>ref['clipEnd']:return {**base,'status':'not-measured','reason':'匹配落在剪切接缝附近，不能作段内对照'}
    return {**base,**value}
