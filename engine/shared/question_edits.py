"""Reviewed contiguous original question excerpts, audited before audio edits."""
import copy
VERSION=2
RULE='''采访提问精简：观众主要关注答案。普通信息请求问题优先3秒以内，只问一件事，尽量一个完整问句、零逗号；先找原话里最短、主体/场景/目的完整的问句。长提问分成多句时只保留必要的一句，删客套、评价、重复换问法，例如“那梵怡诺经营是怎么做的，能让你获得很好的经营效率，这件事你的独特认知是什么”优先保留第一句，不把后三句都叫必要上下文。加盟“如果现在有想加盟的，应该怎么联系”可在不丢加盟场景的条件下缩短，但不能只留失去场景的“怎么联系”。有条件、否定、比较或反认知判断的问句不为3秒硬截，确实需要更长时在summary说明缺少哪项就会误导；不靠加速或改字幕假装剪短。
如果需要在同一原句中精简，可返回questionEdits:[{id,keepQuote:该句内唯一连续、已经说出的完整短问句,reason:为何删前后铺垫仍能准确引出答案}]。只编辑labels为提问或selection.kind为必要提问的保留句（转化问句也可精简），不编辑承载反认知判断的观点句；不能改写、拼词造新问句或添加没说过的字，不能动创作者预留文字。必须对照精简后的实际问答核对场景、否定、条件和指代；声音切口随后严格校准，不安全则保留原话。没有段内精简就返回questionEdits:[]。'''

def compile(project,plan):
 raw=plan.get('questionEdits',[])
 if not isinstance(raw,list) or len(raw)>20:raise ValueError('提问精简清单无效')
 refs={r['id']:r for r in project['segments']};labels={r['id']:r['label'] for r in plan.get('labels',[])};out=[];seen=set()
 for edit in raw:
  if not isinstance(edit,dict) or set(edit)!={'id','keepQuote','reason'} or edit['id'] in seen:raise ValueError('提问精简引用无效')
  sid=edit['id'];seen.add(sid)
  kind=next((r.get('selection',{}).get('kind') for r in plan.get('labels',[]) if r['id']==sid),None)
  if sid not in refs or sid in plan.get('drop',[]) or labels.get(sid)=='观点' or (labels.get(sid)!='提问' and kind!='必要提问'):raise ValueError('只可精简本条保留的普通提问')
  r=refs[sid];quote=edit['keepQuote'];reason=edit['reason']
  if r['deleted'] or r.get('protected') or not isinstance(quote,str) or not quote.strip() or len(quote)>200 or not isinstance(reason,str) or not reason.strip() or len(reason)>500:raise ValueError('预留提问或精简内容无效')
  chars=[];indices=[]
  for i,w in enumerate(r['words']):
   if i in r['removed']:continue
   word=r.get('wordCorrections',{}).get(str(i),w['word']);chars.extend(word);indices.extend([i]*len(word))
  text=''.join(chars)
  if text.count(quote)!=1:raise ValueError('短问句不是唯一连续原话')
  at=text.index(quote);keep=set(indices[at:at+len(quote)])
  if ''.join(r.get('wordCorrections',{}).get(str(i),r['words'][i]['word']) for i in sorted(keep))!=quote:raise ValueError('短問句不能切开同一个原词')
  removed=[i for i in range(len(r['words'])) if i not in keep and i not in r['removed']]
  if set(removed)&set(r.get('protectedIndices',[])):raise ValueError('提问精简不能删预留文字')
  if removed and any(any(c.isalnum() for c in r['words'][i]['word']) for i in removed):out.append({'id':sid,'indices':removed,'keepQuote':quote,'reason':reason})
 return out

def review_rows(rows,cuts):
 out=copy.deepcopy(rows)
 for r in out:
  edit=next((e for e in cuts if e['id']==r['id']),None)
  if edit:r['text']=edit['keepQuote']
 return out

def prepare(key,project,plan,api):
 """Repair only an invalid question reference once; never guess its text.

 The complete resulting plan still goes through the caller's semantic review
 and the normal exact-source and acoustic gates.
 """
 try:return plan,compile(project,plan)
 except ValueError as error:
  from content_recipe import bounded_request
  from analysis_usage import safe_usage
  raw=plan.get('questionEdits',[]);ids={e.get('id') for e in raw if isinstance(e,dict)} if isinstance(raw,list) else set()
  rows=[];kept=[r for r in project['segments'] if not r['deleted'] and r['id'] not in plan.get('drop',[])]
  for n,row in enumerate(kept):
   if row['id'] not in ids and not (n and kept[n-1]['id'] in ids):continue
   rows.append({'id':row['id'],'protected':bool(row.get('protected')),'protectedIndices':row.get('protectedIndices',[]),'text':''.join(row.get('wordCorrections',{}).get(str(i),w['word']) for i,w in enumerate(row['words']) if i not in row['removed'])})
  api.TASKS.progress(key,'正在核对短问句与原话')
  result,usage=bounded_request(RULE+'\n仅修正previousEdits的原话引用，不更换主线、顺序或删句。keepQuote含标点也必须逐字一致且在对应id内只出现一次，不能跨段拼词。无法安全精简则questionEdits=[]保留原问题。只返回JSON {questionEdits:[{id,keepQuote,reason}]}。后续会独立复核实际问答和声音。',{'retainedQuestionsAndFollowingAnswer':rows,'previousEdits':raw,'feedback':str(error),'labels':[{k:v for k,v in label.items() if k in ('id','label','selection')} for label in plan.get('labels',[]) if label['id'] in ids]},api,key=key,max_output_tokens=2048,phase='question-reference-repair')
  api.TASKS.analysis_attempt(key,{'phase':'question-reference-repair','status':'returned','usage':safe_usage(usage)})
  api.save(api.ROOT/'recognition-cache'/('question-reference-repair-'+key+'.json'),{'previousEdits':raw,'feedback':str(error),'result':result})
  if not isinstance(result,dict) or set(result)!={'questionEdits'}:raise ValueError('短问句修正格式无效，原稿保留')
  repaired={**copy.deepcopy(plan),'questionEdits':result['questionEdits']}
  return repaired,compile(project,repaired)

def preview(segments,cuts):
 out=copy.deepcopy(segments)
 for r in out:
  indices={i for e in cuts if e['id']==r['id'] for i in e['indices']}
  if indices:r['removed']=sorted(set(r['removed'])|indices);r.pop('caption',None)
 return out

def execute(key,record,source,project,plan,api):
 cuts=compile(project,plan)
 if not cuts:return record,source,project,{'applied':False,'cuts':[]}
 import manual_word_edit
 result=manual_word_edit.run(key,record,{**project,'selectedWords':[{'id':e['id'],'index':i} for e in cuts for i in e['indices']]},api)
 if not result['changed']:
  # Three seconds is an editorial preference, never authority to guess a cut.
  # The caller must independently review the restored full question before
  # continuing: a condition outside keepQuote can change the answer's meaning.
  return record,source,project,{'applied':False,'held':True,'cuts':cuts,'reason':result['reason'],'calibration':result['calibration']}
 return api.get_case(result['sourceId']),result['source'],result['project'],{'applied':True,'cuts':cuts,'calibration':result['calibration']}

def review_held(key,record,source,project,plan,receipt,api):
 """Re-review actual full questions; never reuse a short-quote pass flag."""
 if not receipt.get('held'):return plan
 import automatic_edit,word_corrections
 api.TASKS.progress(key,'短问句切口不够可靠，正在核对保留完整问题后的衔接')
 ids=set(plan['order'])
 originals=[r for r in api.sentences(record) if r['id'] in ids]
 if {r['id'] for r in originals}!=ids:raise ValueError('完整提问复核的原稿已变化，未继续成片')
 actual=[{'id':r['id'],'text':''.join(w['word'] for i,w in enumerate(word_corrections.display_words(r)) if i not in r['removed'])} for r in project['segments']]
 restored={**copy.deepcopy(plan),'questionEdits':[],'questionCuts':[],'questionEditExecution':copy.deepcopy(receipt)}
 # Evaluate the actual current rows, including prior explicit word edits and
 # their protections. Do not restore an earlier browser draft or removed words.
 restored['drop']=[r['id'] for r in project['segments'] if r['id'] in ids and r['deleted']]
 budget=restored.get('durationBudget')
 seconds=sum(c['end']-c['start'] for c in api.intervals(project['segments'],source['duration'],project['settings'].get('pacing'),source['segments']))/project['settings'].get('speed',1)
 intent={'questionFallback':{'policy':'声音不确定，所有本次短问句精简保持原完整提问；三秒为偏好，不机械截断。按实际问答核对新增的条件、否定、场景与指代，不能沿用短问版通过结论。','heldIds':[e['id'] for e in receipt['cuts']]},'actualRetainedSeconds':round(seconds,3)}
 reviewed,_=automatic_edit.review_edit(key,restored,originals,api,thinking='disabled',compact_labels=True,draft_override=actual,intent=intent)
 folder=api.ROOT/'outputs'/key;folder.mkdir(parents=True,exist_ok=True)
 api.save(folder/'question-fallback-review.json',{'execution':receipt,'review':reviewed.get('review'),'durationBudget':reviewed.get('durationBudget'),'actualQuestions':[r for r in actual if r['id'] in {e['id'] for e in receipt['cuts']}]})
 __import__('semantic_recovery').require_actual_review('question-fallback',reviewed,actual,restored,receipt,project)
 if budget and budget.get('target'):
  checked={**budget,'actualSeconds':round(seconds,3),'passed':seconds<=budget['target']['maxSeconds']+budget['target']['toleranceSeconds']}
  failure=__import__('editorial_policy').duration_failure(checked)
  if failure:raise ValueError(failure['reason'])
  reviewed['durationBudget']=checked
 api.save(folder/'question-fallback-review.json',{'execution':receipt,'review':reviewed.get('review'),'durationBudget':reviewed.get('durationBudget'),'actualQuestions':[r for r in actual if r['id'] in {e['id'] for e in receipt['cuts']}]})
 return reviewed
