"""Reuse an exact two-view cut witness at a continuous SOURCE run boundary.

Never fuzzy-match normal words or authorize a new time/mask. A retained literal
interjection missing in ASR may follow two strong normal words. They must still
be heard exactly, keep the original 60ms margin, and abut the SAME audited cut.
All other edge checks, including the opposite normal edge, remain mandatory.
"""
import hashlib,json,math,re
from pathlib import Path
VERSION=1

def media_signature(video):
 path=Path(video).resolve();stat=path.stat()
 return {'path':str(path),'bytes':stat.st_size,'mtimeNs':str(stat.st_mtime_ns)}

def validate_witness(witness,excluded,video,cache):
 from cut_audio_review import VERSION as REVIEW_VERSION,PROMPT,decide
 import mimo
 try:
  if witness.get('version')!=REVIEW_VERSION or witness.get('passed') is not True or witness.get('source')!='actual-local-waveforms' or witness.get('mediaSignature')!=media_signature(video):return False
  cuts=witness['cuts'];views=witness['views'];words=witness['removedWords']
  if not cuts or len(views)!=len(cuts)*2 or not words:return False
  # A different mask cannot inherit an earlier successful joint audition.
  if any(not any(e['word']==w['word'] and abs(e['start']-w['start'])<1e-7 and abs(e['end']-w['end'])<1e-7 for e in excluded) for w in words):return False
  for cut,n in zip(cuts,range(len(cuts))):
   if not all(type(cut.get(k)) in (int,float) and math.isfinite(cut[k]) for k in ('start','end')) or cut['start']>=cut['end']:return False
   hashes=set()
   for view in views[2*n:2*n+2]:
    binding=view['binding']
    if not re.fullmatch('[a-f0-9]{64}',binding) or view['receipt']!='cut-audio-review-v1-'+binding+'.json':return False
    if not view['bounds'][0]<=cut['start']<cut['end']<=view['bounds'][1]:return False
    receipt=json.loads((Path(cache)/view['receipt']).read_text('utf8'))
    if receipt.get('binding')!=binding or receipt.get('audioActuallySubmitted') is not True:return False
    hs,hc=receipt['sourceAudioSha256'],receipt['candidateAudioSha256'];hashes.add((hs,hc))
    expected=hashlib.sha256(json.dumps({'version':REVIEW_VERSION,'prompt':PROMPT,'model':mimo.MODEL,'source':hs,'candidate':hc,'sourceLabel':receipt['sourceLabel'],'left':view['left'],'right':view['right'],'quote':view['removed']},sort_keys=True).encode()).hexdigest()
    if expected!=binding or hs==hc or not decide(receipt['reading'],receipt['sourceLabel'],view['left'],view['right'],view['removed'])['passed']:return False
   if len(hashes)!=2:return False
  return True
 except (KeyError,TypeError,ValueError,OSError):return False

def resolve_end(expected,heard,observations,span,next_span,excluded,video,cache):
 reject=lambda reason:{'version':VERSION,'passed':False,'reason':reason}
 normalize=lambda s:''.join(c for c in s if c.isalnum()).upper()
 want,got=normalize(expected),normalize(heard);tail=re.search('[呃嗯额啊哦哎]+$',want)
 if not tail or next_span is None:return reject('not a retained literal-interjection edge')
 core=want[:tail.start()]
 if len(core)<2 or not got.endswith(core[-2:]):return reject('normal tail words still required exactly')
 normal=observations[:-len(tail.group())][-2:]
 if len(normal)!=2 or ''.join(e.get('expected','') for e in normal)!=core[-2:]:return reject('normal source edge missing')
 for entry in normal:
  a,b=entry.get('first') or {},entry.get('second') or {}
  if any(t.get('actual')!=entry['expected'] or t.get('probability',0)<.8 or not isinstance(t.get('time'),(int,float)) for t in (a,b)) or abs(a['time']-b['time'])>.08:return reject('normal source edge not supported twice')
  if round(span['end']-max(a['time'],b['time']),9)<.06:return reject('normal 60ms tail margin required')
 for item in excluded:
  witness=item.get('cutAudioWitness')
  if not isinstance(witness,dict):continue
  for n,cut in enumerate(witness.get('cuts',[])):
   if abs(cut.get('start',-1)-span['end'])>1e-7 or abs(cut.get('end',-1)-next_span['start'])>1e-7:continue
   views=witness.get('views',[])[2*n:2*n+2]
   if len(views)!=2 or any(not v.get('left','').endswith(core[-2:]) for v in views):continue
   if validate_witness(witness,excluded,video,cache):return {'version':VERSION,'passed':True,'reason':'unchanged continuous source run at the exact twice-audited cut; normal words retained','normalTail':core[-2:],'cut':cut,'viewBindings':[v['binding'] for v in views],'normalMarginSeconds':round(span['end']-max(normal[-1]['first']['time'],normal[-1]['second']['time']),6)}
 return reject('no same-media exact-mask two-view cut witness')
