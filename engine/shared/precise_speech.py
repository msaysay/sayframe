"""Local character anchors plus recognition of proposed retained audio.

CTC peaks locate token occurrences, not exact phoneme edges. Boundaries remain
estimates until the specific removed range survives an output-audio check.
"""
import copy,json,re,time
from pathlib import Path
import numpy as np

JOINT_SEARCH_VERSION=2

def joint_padding_candidates():
 """Keep previous decisions, then fill missing left/right combinations.

 Every trial auditions all requested cuts together from the original audio;
 separately passing single cuts never authorize their composition.
 """
 legacy=((0,0),(.04,0),(.08,0),(0,-.04),(.04,-.04),(.08,-.04),(0,-.08),(.04,-.08),(.08,-.08),(0,-.12),(.04,-.12),(.08,-.12),(0,.04),(.04,.04),(0,.08),(.04,.08),(0,.12),(.04,.12),(0,.16),(0,.20),(0,.24),(0,.28),(0,.32))
 missing=tuple((left,right) for right in [0,-.04,-.08,-.12,.04,.08,.12,.16,.20,.24,.28,.32] for left in [0,.04,.08] if (left,right) not in legacy)
 return legacy+missing

def spoken(text):return ''.join(c for c in text if c.isalnum()).upper()

class CharacterAcoustics:
 def __init__(self,folder):
  import onnxruntime as ort,kaldi_native_fbank as knf
  self.knf=knf;folder=Path(folder);opts=ort.SessionOptions();opts.intra_op_num_threads=4;opts.inter_op_num_threads=1
  self.session=ort.InferenceSession(str(folder/'model.int8.onnx'),sess_options=opts,providers=['CPUExecutionProvider']);self.meta=self.session.get_modelmeta().custom_metadata_map
  self.tokens={int(line.rsplit(' ',1)[1]):line.rsplit(' ',1)[0] for line in (folder/'tokens.txt').read_text('utf8').splitlines()}
  self.mean=np.fromstring(self.meta['neg_mean'],sep=',',dtype=np.float32);self.scale=np.fromstring(self.meta['inv_stddev'],sep=',',dtype=np.float32)
 def trace(self,audio,offset=0):
  opts=self.knf.FbankOptions();opts.frame_opts.dither=0;opts.frame_opts.snip_edges=False;opts.frame_opts.window_type='hamming';opts.mel_opts.num_bins=80
  bank=self.knf.OnlineFbank(opts);bank.accept_waveform(16000,(np.asarray(audio,dtype=np.float32)*32768).tolist());bank.input_finished()
  if not bank.num_frames_ready:return []
  features=np.stack([bank.get_frame(i) for i in range(bank.num_frames_ready)]);m=int(self.meta['lfr_window_size']);shift=int(self.meta['lfr_window_shift']);left=(m-1)//2
  indices=np.clip(np.arange(0,len(features),shift)[:,None]+np.arange(-left,m-left)[None,:],0,len(features)-1)
  features=np.ascontiguousarray((features[indices].reshape(-1,80*m)+self.mean)*self.scale)
  scores=self.session.run(['logits'],{'x':features[None],'x_length':np.array([len(features)],dtype=np.int32),'language':np.array([int(self.meta['lang_zh'])],dtype=np.int32),'text_norm':np.array([int(self.meta['without_itn'])],dtype=np.int32)})[0][0]
  ids=scores.argmax(-1);out=[]
  for frame,token in enumerate(ids):
   if not token or (frame and token==ids[frame-1]):continue
   text=self.tokens[int(token)]
   if text.startswith('<|'):continue
   text=spoken(text.replace('▁',''))
   if text:out.append({'text':text,'time':offset+(frame-4)*shift*.01,'probability':float(np.exp(scores[frame,token]-np.logaddexp.reduce(scores[frame]))),'frame':frame})
  return out

def anchored_context_matches(target,heard,chars,start):
 """Resolve repeated *context* without inventing a missing first syllable.

 A literal first character must occur uniquely within the existing 900ms
 source-time guard. Keep the 85% textual coverage and exact terminal anchor;
 substituted/interpolated characters remain probability zero below. This is
 alignment only: a weak observed first token is still unsafe as a cut edge.
 """
 import difflib
 candidates=[]
 if not target:return None
 for at,ch in enumerate(heard):
  if ch!=target[0] or abs(chars[at]['time']-start)>.9:continue
  matches={0:at}
  for a,b,size in difflib.SequenceMatcher(a=target[1:],b=heard[at+1:],autojunk=False).get_matching_blocks():
   for k in range(size):matches[a+k+1]=at+b+k+1
  if len(matches)>=len(target)*.85 and len(target)-1 in matches:candidates.append(matches)
 return candidates[0] if len(candidates)==1 else None

def matched_anchors(row,trace,*,provisional_end=False):
 target=spoken(''.join(w['word'] for w in row['words']));heard=''.join(t['text'] for t in trace)
 places=[m.start() for m in re.finditer('(?='+re.escape(target)+')',heard)] if target else []
 chars=[]
 for n,t in enumerate(trace):
   chars.extend([{**t,'group':str(n),'shared':len(t['text'])>1,'actual':ch,'matched':True} for ch in t['text']])
 if not places:
  # Local recognition can confuse a non-cut word (e.g. 这/的). Keep original
  # spelling and distrust that word; independently matching repeated tokens
  # can still be located. Missing repeated copies must never become trusted.
  import difflib
  matches={};matcher=difflib.SequenceMatcher(a=target,b=heard,autojunk=False)
  for a,b,size in matcher.get_matching_blocks():
   for k in range(size):matches[a+k]=b+k
  if 0 not in matches or abs(chars[matches[0]]['time']-row['start'])>.9:
   bounded=anchored_context_matches(target,heard,chars,row['start'])
   if bounded is not None:matches=bounded
  if len(matches)<len(target)*.85 or not matches:return None
  first=min(matches);last=max(matches)
  if first>1 or last<len(target)-2 or abs(chars[matches[first]]['time']-row['start'])>.9:return None
  chosen=[]
  for index in range(len(target)):
   if index in matches:chosen.append(chars[matches[index]]);continue
   left=max((i for i in matches if i<index),default=None);right=min((i for i in matches if i>index),default=None)
   if right is None and left is not None and provisional_end and index==len(target)-1 and matches[left]+1<len(chars):
    # Only locate an UNTRUSTED terminal event for an independently audited
    # whole-word edge. This is not a phonetic match or deletion authority.
    chosen.append({**chars[matches[left]+1],'probability':0,'matched':False,'provisionalTerminal':True});continue
   if left is None or right is None:return None
   pos=round(matches[left]+(matches[right]-matches[left])*(index-left)/(right-left));pos=max(0,min(pos,len(chars)-1))
   chosen.append({**chars[pos],'probability':0,'matched':False})
  if any(a['time']>b['time'] for a,b in zip(chosen,chosen[1:])):return None
  return chosen
 # A repeated quote in a context window must be located by its original time.
 at=min(places,key=lambda i:abs(chars[i]['time']-row['start']));chosen=chars[at:at+len(target)]
 if any(a['time']>b['time'] for a,b in zip(chosen,chosen[1:])):return None
 return chosen

def coordinate_words(row,anchors,other):
 import copy
 words=copy.deepcopy(row['words']);n=0;matches=[]
 for i,w in enumerate(words):
  count=len(spoken(w['word']));group=anchors[n:n+count];peer=other[n:n+count];n+=count
  if not count:continue
  if not group or len(group)!=len(peer):return None
  matches.append((i,group,peer))
 for k,(i,group,peer) in enumerate(matches):
  center=group[0]['time'];previous=matches[k-1][1][-1]['time'] if k else center-.16;following=matches[k+1][1][0]['time'] if k+1<len(matches) else center+.16
  lo=max(0,(previous+center)/2);hi=max(lo,(group[-1]['time']+following)/2)
  shared=any(g['shared'] for g in group)
  if shared:
   # Never advertise independent timing for letters inside a single token.
   lo=words[i]['start'];hi=words[i]['end']
  stable=not shared and min(g['probability'] for g in group)>=.55 and all(abs(g['time']-p['time'])<=.08 for g,p in zip(group,peer)) and hi-lo>=.04
  words[i].update(start=lo,end=hi,timingEstimated=True,alignmentGroup='ctc:'+group[0]['group'],alignmentStable=stable,alignmentProbability=min(g['probability'] for g in group),alignmentMethod='two-window CTC token anchors',acousticCenter=center,acousticRecognized=''.join(g['actual'] for g in group))
 # Keep punctuation instantaneous at the preceding acoustic boundary.
 last=words[0]['start']
 for w in words:
  if not spoken(w['word']):w['start']=w['end']=last
  else:last=w['end']
 return __import__('acoustic_atoms').annotate(words,anchors,other)

def removal_runs(indices):
 runs=[]
 for index in sorted(set(indices)):
  if runs and index==runs[-1][-1]+1:runs[-1].append(index)
  else:runs.append([index])
 return runs

def audit_removal(row,words,audio,offset,recognizer,indices,deadline=None,proposed_fillers=(),reviewed_excerpts=(),cut_reviewer=None):
 """Search only a small local range; retain all meaningful expected characters."""
 expected=spoken(''.join(w['word'] for i,w in enumerate(words) if i not in indices))
 if not expected:return None,{'passed':False,'indices':indices,'reason':'整句删除不需要单字校准'}
 runs=removal_runs(indices)
 audible=[i for i,w in enumerate(words) if spoken(w['word'])]
 removed=[i for i in audible if i in indices]
 if not removed:return None,{'passed':False,'indices':indices,'reason':'删除字没有独立可靠声音锚点'}
 # Layout punctuation has no sound. Without merging these ranges, two cuts
 # share the same retained left/right word and the later cut overwrites its
 # earlier edge, restoring an already removed filler into the final movie.
 merged=[]
 for run in runs:
  if merged and all(not spoken(words[i]['word']) for i in range(merged[-1][-1]+1,run[0])):
   merged[-1].extend(run)
  else:merged.append(list(run))
 runs=merged
 unstable=[i for i in removed if not words[i].get('alignmentStable')]
 # A low-confidence leading interjection need not have its own strong peak
 # if two following real syllables agree in both windows. We still require
 # exact retained-audio recognition below; never extend this to a negation,
 # number, interior token, or a missing repeated copy.
 prefix_filler=removed==audible[:len(removed)] and all(re.fullmatch('[呃嗯额啊哦]+',words[i]['word']) for i in removed)
 following=[i for i in audible if i not in removed][:2]
 prefix_verified=prefix_filler and len(following)==2 and all(words[i].get('alignmentStable') and words[i].get('alignmentProbability',0)>=.8 for i in following)
 # A complete failed restart can be bounded by reliable retained words even
 # when one of its own weak/overlapped syllables lacks an independent peak.
 # This does not allow a single missing repeated copy: both retained flanks,
 # the restarted wording, and the exact resulting audio must all agree.
 def strong(i):return words[i].get('alignmentStable') and words[i].get('alignmentProbability',0)>=.8
 first,last=removed[0],removed[-1]
 left=next((i for i in reversed(audible) if i<first and i not in indices),None)
 right=[i for i in audible if i>last and i not in indices][:2]
 quote=spoken(''.join(words[i]['word'] for i in removed))
 restart=quote
 for _ in range(4):
  collapsed=re.sub(r'(.{1,6})\1+',r'\1',restart)
  if collapsed==restart:break
  restart=collapsed
 suffix=spoken(''.join(w['word'] for i,w in enumerate(words) if i>last and i not in indices))
 whole_run=all(i in indices or not spoken(words[i]['word']) for i in range(first,last+1))
 flanked_restart=len(removed)>=2 and whole_run and left is not None and len(right)==2 and strong(left) and all(strong(i) for i in right) and bool(restart) and suffix.startswith(restart)
 atom_evidence=__import__('acoustic_atoms').removal_evidence(words,indices)
 if unstable and not (prefix_verified or flanked_restart or atom_evidence['passed']):return None,{'passed':False,'indices':indices,'reason':'删除字没有独立可靠声音锚点'}
 boundaries=[]
 for run in runs:
  members=[i for i in run if i in audible]
  if not members:continue
  first,last=members[0],members[-1];left=next((i for i in reversed(audible) if i<first and i not in indices),None);right=next((i for i in audible if i>last and i not in indices),None)
  boundaries.append((first,last,left,right))
 def apply_verified(cuts):
  import copy
  result=copy.deepcopy(words)
  # Synchronize adjacent retained words and intervening punctuation so their
  # playback clips cannot leak the removed syllable's early/late tails.
  for (first,last,left,right),(start,end) in zip(boundaries,cuts):
   result[first]['start']=start;result[last]['end']=end
   # Shared CTC letters have only one whole-token interval. A cut clamped
   # by a retained neighbor can start after an estimated first-letter end.
   # Never leave that display estimate behind as an invalid physical span.
   if atom_evidence['passed']:
    for atom in atom_evidence['tokens']:
     if set(atom['members']).issubset(range(first,last+1)):
      for i in atom['members']:
       result[i]['start']=start;result[i]['end']=end
   for i in range(first,last+1):
    if not spoken(result[i]['word']):result[i]['start']=result[i]['end']=start
   if left is not None:
    result[left]['end']=start
    for i in range(left+1,first):
     if not spoken(result[i]['word']):result[i]['start']=result[i]['end']=start
   if right is not None:
    result[right]['start']=end
    for i in range(last+1,right):
     if not spoken(result[i]['word']):result[i]['start']=result[i]['end']=end
  for i in removed:
   result[i]['alignmentVerified']=True
   if cut_reviewer is not None:result[i]['cutAudioReviewVersion']=__import__('cut_audio_review').VERSION
   if result[i].get('alignmentToken'):
    # A verified complete token still has no independent letter timestamps.
    result[i]['alignmentStable']=False
    if atom_evidence['passed']:result[i]['alignmentTokenVerified']=result[i]['alignmentToken']['id']
   else:result[i]['alignmentStable']=True
  if cut_reviewer is not None:
   witness=next((t.get('localAudioReview') for t in reversed(attempts) if t.get('passed') and t.get('localAudioReview',{}).get('passed')),None)
   if witness:
    witness=copy.deepcopy(witness);witness['removedWords']=[{k:result[i][k] for k in ('word','start','end')} for i in removed]
    for i in removed:result[i]['cutAudioWitness']=copy.deepcopy(witness)
  return result
 attempts=[]
 # CTC centers describe token peaks, not the extent of the whole utterance.
 # Keep the source sentence boundaries in the audition; otherwise a retained
 # final interjection can disappear from the test before any cut is made.
 begin=max(offset,min(row['start'],words[audible[0]]['start']-.12))
 finish=min(offset+len(audio)/16000,max(row['end'],words[audible[-1]]['end']+.12))
 # CTC peaks are often late in a short negation. Search *earlier* right
 # boundaries too, so deleting 都 never clips the following 不 syllable.
 proposals=cut_reviewer.suggest(words,indices) if cut_reviewer is not None else []
 trials=([('qwen-source-bound',proposals)] if proposals and len(proposals)==len(boundaries) else [])+[('ctc-padding',(a,b)) for a,b in joint_padding_candidates()]
 for origin,trial in trials:
  if cut_reviewer is not None and getattr(cut_reviewer,'exhausted',False):
   return None,{'passed':False,'indices':indices,'attempts':attempts,'reason':'局部声音复核预算已用完，保留原话'}
  if deadline is not None and time.monotonic()>=deadline:
   return None,{'passed':False,'indices':indices,'attempts':attempts,'reason':'声音核验预算已用完，保留原话'}
  cuts=[]
  for n,(first,last,left,right) in enumerate(boundaries):
   if origin=='qwen-source-bound':start=max(offset,trial[n]['start']);end=min(offset+len(audio)/16000,trial[n]['end'])
   else:
    left_pad,right_pad=trial;start=max(offset,words[first]['start']-left_pad);end=min(offset+len(audio)/16000,words[last]['end']+right_pad)
   # There is no retained speech before a leading deletion. Cutting from the
   # audition's start prevents the beginning of that filler leaking back in.
   if left is None:start=begin
   if right is None:end=finish
   if left is not None:start=max(start,words[left].get('acousticCenter',words[left]['start'])+.06)
   if right is not None:end=min(end,words[right].get('acousticCenter',words[right]['end'])-.06)
   cuts.append((start,end))
  if any(a>=b for a,b in cuts) or any(a[1]>b[0] for a,b in zip(cuts,cuts[1:])):continue
  if atom_evidence['passed'] and any(not any(a<=t['center']<=b for a,b in cuts) for t in atom_evidence['tokens']):continue
  cursor=begin;pieces=[]
  for start,end in cuts:
   pieces.append(audio[round((cursor-offset)*16000):round((start-offset)*16000)]);cursor=end
  pieces.append(audio[round((cursor-offset)*16000):round((finish-offset)*16000)])
  retained=np.concatenate(pieces)
  heard=''.join(t['text'] for t in recognizer.trace(retained))
  baseline=spoken(''.join(w.get('acousticRecognized',w['word']) for i,w in enumerate(words) if i not in indices))
  ok=heard in (expected,baseline)
  review=cut_reviewer.check(row,words,indices,[{'start':a,'end':b} for a,b in cuts],audio,offset) if ok and cut_reviewer is not None else None
  if review is not None:ok=review['passed']
  attempts.append({'start':cuts[0][0],'end':cuts[-1][1],'cuts':[{'start':a,'end':b} for a,b in cuts],'expected':expected,'baselineExpected':baseline,'recognized':heard,'passed':ok,'candidateProvider':origin,**({'localAudioReview':review} if review is not None else {})})
  if ok:
   return apply_verified(cuts),{'passed':True,'indices':indices,'attempts':attempts,'anchoring':'strong retained flanks and complete restarted phrase' if unstable and flanked_restart else 'two-window token anchors','method':'local retained-audio recognition; not human listening'}
 differential=None
 if attempts and (deadline is None or time.monotonic()<deadline):
  import audio_delta
  original=audio[round((begin-offset)*16000):round((finish-offset)*16000)]
  before=[{**t,'time':t['time']+begin} if isinstance(t.get('time'),(int,float)) else t for t in recognizer.trace(original)]
  differential=audio_delta.prepare(words,indices,before,proposed_fillers,reviewed_excerpts)
  # Keep local failure evidence replayable. No credentials, model prompts or
  # server configuration belong in this acoustic receipt.
  differential['originalTrace']=before
  differential['wordAnchors']=[{k:w[k] for k in ('word','acousticCenter','acousticRecognized','alignmentStable','alignmentProbability','alignmentGroup','alignmentToken') if k in w} for w in words]
  if differential['passed']:
   for attempt in attempts:
    if audio_delta.verify(differential,words,before,attempt['cuts'],attempt['recognized']):
     if cut_reviewer is not None:
      review=cut_reviewer.check(row,words,indices,attempt['cuts'],audio,offset);attempt['localAudioReview']=review
      if not review['passed']:continue
     cuts=[(c['start'],c['end']) for c in attempt['cuts']]
     attempt['passed']=True;attempt['verification']='source-bound exact recognition difference'
     return apply_verified(cuts),{'passed':True,'indices':indices,'attempts':attempts,'differential':differential,'method':'exact original-versus-cut audio trace; not human listening'}
   # A third original view can place a retained neighbour earlier than the
   # two-window estimate. Audition a smaller cut; never waive that neighbour.
   seen={tuple((c['start'],c['end']) for c in a['cuts']) for a in attempts}
   for attempt in list(attempts):
    if deadline is not None and time.monotonic()>=deadline:break
    bounded=audio_delta.constrain_candidate(differential,words,before,attempt['cuts'])
    if not bounded:continue
    key=tuple((c['start'],c['end']) for c in bounded)
    if key in seen:continue
    seen.add(key);cursor=begin;pieces=[]
    for cut in bounded:
     pieces.append(audio[round((cursor-offset)*16000):round((cut['start']-offset)*16000)]);cursor=cut['end']
    pieces.append(audio[round((cursor-offset)*16000):round((finish-offset)*16000)])
    heard=''.join(t['text'] for t in recognizer.trace(np.concatenate(pieces)))
    passed=audio_delta.verify(differential,words,before,bounded,heard)
    review=cut_reviewer.check(row,words,indices,bounded,audio,offset) if passed and cut_reviewer is not None else None
    if review is not None:passed=review['passed']
    attempts.append({'start':bounded[0]['start'],'end':bounded[-1]['end'],'cuts':bounded,'expected':expected,'baselineExpected':baseline,'recognized':heard,'passed':passed,'verification':'three-view bounded union audition',**({'localAudioReview':review} if review is not None else {})})
    if passed:
     return apply_verified([(c['start'],c['end']) for c in bounded]),{'passed':True,'indices':indices,'attempts':attempts,'differential':differential,'method':'three-view source-bound retained-audio audition; not human listening'}
 return None,{'passed':False,'indices':indices,'attempts':attempts,'differential':differential,'reason':'实际删后声音与保留文字不一致'}

def audit_requested_removals(row,words,audio,offset,recognizer,indices,mandatory=(),deadline=None,max_groups=6,proposed_fillers=(),reviewed_excerpts=(),cut_reviewer=None):
 """Isolate unsafe proposals without ever composing independently passed cuts.

 Each trial starts from immutable anchors and includes pre-existing user cuts.
 Only a final exact joint audition can authorize the accepted union. Failed
 proposals retain their timing and cannot inherit another group's pass receipt.
 """
 indices=sorted(set(indices));mandatory=set(mandatory)&set(indices)
 result,full=audit_removal(row,words,audio,offset,recognizer,indices,deadline=deadline,proposed_fillers=proposed_fillers,reviewed_excerpts=reviewed_excerpts,cut_reviewer=cut_reviewer)
 if result is not None:return result,[{**full,'stage':'requested-joint'}]
 receipts=[{**full,'stage':'requested-joint'}];accepted=[]
 groups=removal_runs([i for i in indices if i not in mandatory])
 if len(groups)>1:
  for group in groups[:max_groups]:
   if deadline is not None and time.monotonic()>=deadline:break
   trial=sorted(mandatory|set(group))
   candidate,receipt=audit_removal(row,words,audio,offset,recognizer,trial,deadline=deadline,proposed_fillers=proposed_fillers,reviewed_excerpts=reviewed_excerpts,cut_reviewer=cut_reviewer)
   # Diagnostic single passes never authorize application by themselves.
   receipts.append({**receipt,'passed':False,'individualPassed':candidate is not None,'stage':'isolated-provisional'})
   if candidate is not None:accepted.extend(group)
  if accepted:
   joint=sorted(mandatory|set(accepted))
   result,receipt=audit_removal(row,words,audio,offset,recognizer,joint,deadline=deadline,proposed_fillers=proposed_fillers,reviewed_excerpts=reviewed_excerpts,cut_reviewer=cut_reviewer)
   receipts.append({**receipt,'stage':'accepted-joint'})
 if result is None:result=copy.deepcopy(words);accepted=[]
 authorized=set(accepted)|mandatory if receipts[-1].get('stage')=='accepted-joint' and receipts[-1]['passed'] else set()
 for i in set(indices)-authorized:
  result[i]['alignmentStable']=False;result[i]['alignmentVerified']=False
 return result,receipts
