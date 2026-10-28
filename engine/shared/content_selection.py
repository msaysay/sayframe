"""Source-quoted editorial priorities; never infer expertise from a number."""
import copy,json,re
from pathlib import Path
SCHEMA=json.loads((Path(__file__).resolve().parent/'src/content-selection-schema.json').read_text('utf8'))
VERSION=SCHEMA['policyVersion']
BINDING_VERSION=1
class SelectionValidationError(ValueError):
 def __init__(self,message,sentence_id=None):
  self.sentence_id=sentence_id
  super().__init__(message)
PRIORITIES=set(SCHEMA['priorities'])
KINDS=set(SCHEMA['kinds'])
MUSCLE=set(SCHEMA['muscleKinds'])
RULE='''逐句内容认定与选材优先级：先明确这条片子的核心问题和判断，再评价原话的作用。支撑回答“为什么这个判断成立”，可以是原因机制、真实案例、对比、经济账、数据事实、亲身经历；肌肉词回答“为什么相信这个人/产品能解决我的问题”，是本人结果、明确归属的客户结果、可感知的差异优势或与主题有关的经历资历。二者可重叠，label取主要作用，reason说明另一作用。数字、头衔和年限本身不是肌肉词；120平/四五间教室/180平/260平在店型效率主线里是事实参数和机制支撑，不因数字大而判能力证明。“坪效很高”“打磨几套模型”“我们很专业”本身没有具体结果依据，不能当强肌肉词。肌肉词也不必有数字：像造车一样装修、不加一滴水等明确可感知优势可作为候选，不能一律降成无数字废话。帮助客户产生的结果必须保留客户主体、条件、时期，不能改成讲者本人业绩。个人自述不是外部核验，不标为已证实。
保留优先级：必留=让主张成立/避免误导不可缺的判断、必要条件或指代；优先=直接服务主线的具体支撑或能力证据；可选=重复、相关较弱、空泛或待判定的补充；舍弃=本条不选用，仍可恢复。先保语义完整，再比较与主线相关程度、具体程度、信息增量；不能凭数字大小或“肌肉词”标签自动排最前。没有相关肌肉词应如实说缺口，不强凑。条件和限定即使不抢眼也可必留。
每个保留句的labels条目增加selection:{priority:必留/优先/可选,kind:核心判断/论证机制/论证案例/事实参数/本人结果/客户结果/差异优势/经历资历/必要提问/行动承接/泛泛评价/旁支信息,quote:该句内连续原话短依据,claim:它支撑本条哪一个问题或判断,status:内容明确/待确认}。quote必须来自实际保留文字，不能从原片已删字、字幕外推或方向说明拼造。reason简短说清“选它具体证明什么/不是肌肉词的原因”，不要仅写“原话支撑”。肌肉词的kind只可本人结果/客户结果/差异优势/经历资历；尚未说清归属或关联则待确认、可选，不硬贴。每项约一句，理由最多100字。'''
RULE+='''\nstatus“内容明确/待确认”只判断原话、说话人归属和与主线的关联在当前材料中是否清楚，不代表外部事实核验。讲者明确说“我做了/我用了/我完成了”等具体经历，即使它只是本人自述、未经外部核验，也可标为内容明确；reason或claim必须写清“讲者自述”，不能包装为已证实业绩。只有措辞、主体、条件或关联确实模糊时才标待确认；待确认的肌肉词只能可选，不能列为必留或优先。'''
RULE=re.sub(r'kind:[^,\n]+,quote:',lambda m:'kind:'+'/'.join(k for k in SCHEMA['kinds'] if k!='待判定')+',quote:',RULE,count=1)
RULE+='\n必要条件用于避免主张或因果被误解的限制、代价与前提，可列必留；例如“想加活，又不想给我加钱”中回报限制不可因没有数字而删掉。必要条件本身不是肌肉词，也不自动证明人物能力，仍须有本句实际保留原话作为依据。'

def normalized(text):return re.sub(r'\s','',text)

def literal_reference(text,quote):
 """Bind display punctuation only; no changed words/numbers/conditions."""
 if not isinstance(quote,str) or not quote.strip():return None
 if quote in text:return quote
 layout=set(' \t\r\n，。！？；：、,.!?;:')
 def meaningful(s,i):
  # Decimal/grouping separators are data, not subtitle layout punctuation.
  return s[i] not in layout or (s[i] in '.,，' and i>0 and i+1<len(s) and s[i-1].isdigit() and s[i+1].isdigit())
 positions=[i for i,c in enumerate(text) if meaningful(text,i)]
 cleaned=''.join(text[i] for i in positions);needle=''.join(c for i,c in enumerate(quote) if meaningful(quote,i))
 if not needle or cleaned.count(needle)!=1:return None
 at=cleaned.index(needle)
 return text[positions[at]:positions[at+len(needle)-1]+1]

def validate(value):
 if value is None:return None
 if not isinstance(value,dict) or set(value)!={'version','label','priority','kind','quote','claim','reason','status'} or value['version']!=SCHEMA['valueVersion'] or value['label'] not in SCHEMA['labels'] or value['priority'] not in PRIORITIES or value['kind'] not in KINDS or value['status'] not in SCHEMA['statuses']:raise SelectionValidationError('内容保留依据格式无效')
 for key,limit in (('quote',200),('claim',200),('reason',400)):
  if not isinstance(value[key],str) or not value[key].strip() or len(value[key])>limit:raise SelectionValidationError('内容保留依据缺少原话或理由')
 if value['label']=='肌肉词' and value['kind'] not in MUSCLE and not (value['kind']=='待判定' and value['status']=='待确认' and value['priority']=='可选'):raise SelectionValidationError('不能把普通参数标为肌肉词')
 if value['label']=='肌肉词' and value['status']=='待确认' and value['priority'] in ('必留','优先'):raise SelectionValidationError('未认定的肌肉词候选不能排为优先证据')
 if value['kind']=='泛泛评价' and value['priority'] in ('必留','优先'):raise SelectionValidationError('空泛评价不能充当优先证据')
 return copy.deepcopy(value)

def attach(plan,rows):
 result=copy.deepcopy(plan);refs={r['id']:r for r in rows};values=[];warnings=[]
 for label in result.get('labels',[]):
  item=label.get('selection')
  if item is None:continue # Old saved plans stay readable, without invented priorities.
  if not isinstance(item,dict) or set(item)!={'priority','kind','quote','claim','status'}:raise SelectionValidationError('内容认定字段不完整')
  sid=label['id']
  try:value=validate({'version':1,'label':label['label'],'reason':label['reason'],**item})
  except SelectionValidationError as error:
   error.sentence_id=sid;raise
  bound=literal_reference(refs[sid]['text'],value['quote']) if sid in refs else None
  if sid not in refs:raise SelectionValidationError('内容认定引用未知原句')
  if bound is None:
   warnings.append({'id':sid,'reportedQuote':value['quote'],'actualText':refs[sid]['text'],'reason':'引用与原话不符，不能据此优先选材'})
   value.update(quote=refs[sid]['text'][:200],priority='可选',kind='待判定',claim='需要结合主线重新核对',reason='原话引用未匹配，已回到本段原文；认定待复核。',status='待确认')
  else:value['quote']=bound
  if sid not in result.get('drop',[]) and value['priority']=='舍弃':raise SelectionValidationError('保留优先级与剪辑清单不一致')
  values.append({'id':sid,**value})
 result['contentSelection']=values;result['contentSelectionWarnings']=warnings;result['contentSelectionVersion']=VERSION
 return result

def rebind_rows(rows):
 """Invalidate stale editorial metadata against the final kept original words.

 Never infer a shorter claim after a cut, restore words, alter labels, or
 touch audio geometry. Old immutable snapshots remain on disk. A fresh
 semantic planning pass may replace the conservative pending explanation.
 """
 from word_corrections import display_words
 out=copy.deepcopy(rows);entries=[]
 for row in out:
  value=validate(row.get('contentValue'))
  if value is None or row.get('deleted'):continue
  text=''.join(w['word'] for i,w in enumerate(display_words(row)) if i not in row.get('removed',[]))
  bound=literal_reference(text,value['quote']) if value['label']==row.get('label') else None
  if bound is not None:
   if bound!=value['quote']:
    row['contentValue']={**value,'quote':bound}
    entries.append({'id':row['id'],'status':'layout-rebound','previous':value,'current':row['contentValue']})
   continue
  if not text.strip():row.pop('contentValue',None)
  else:
   row['contentValue']=validate({**value,'label':row['label'],'priority':'可选','kind':'待判定','status':'待确认','quote':text[:200],
    'claim':'编辑后需要重新核对本段与主线的关系','reason':'内容已编辑，原保留依据不再完整；请重新分析，暂不作为优先证据。'})
  entries.append({'id':row['id'],'status':'invalidated','previous':value,'current':row.get('contentValue')})
 return out,{'version':BINDING_VERSION,'checked':sum(not r.get('deleted') and r.get('contentValue') is not None for r in rows),'entries':entries,'changedSpeech':False}

def rebind_plan(plan,rows,receipt):
 """Current displayed metadata follows final rows; prior reviews stay history."""
 out=copy.deepcopy(plan);values={r['id']:r['contentValue'] for r in rows if not r.get('deleted') and r.get('contentValue')}
 out['contentSelection']=[{'id':sid,**v} for sid,v in values.items()]
 for label in out.get('labels',[]):
  if label['id'] in values:
   v=values[label['id']];label['reason']=v['reason'];label['selection']={k:v[k] for k in ('priority','kind','quote','claim','status')}
 out['contentSelectionBinding']=copy.deepcopy(receipt)
 return out

def question_report(plan,clips,speed=1):
 labels={l['id']:l['label'] for l in plan.get('labels',[])};question_ids={v['id'] for v in plan.get('contentSelection',[]) if v['kind']=='必要提问' and v['label']!='观点'};groups=[]
 for index,clip in enumerate(clips):
  if labels.get(clip.get('id'))!='提问' and clip.get('id') not in question_ids:continue
  # Group consecutive questions in actual playback, not by raw shooting time.
  if not groups or index!=groups[-1]['last']+1:groups.append({'ids':[],'text':'','seconds':0,'last':index})
  g=groups[-1];g['last']=index
  if clip['id'] not in g['ids']:g['ids'].append(clip['id'])
  g['text']+=clip['text'];g['seconds']+=(clip['end']-clip['start'])/speed
 for g in groups:g.pop('last');g['seconds']=round(g['seconds'],2);g['withinTarget']=g['seconds']<=3
 return {'version':1,'targetSeconds':3,'groups':groups}
