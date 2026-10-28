"""Compile explicit quoted deletion requests from creator messages, never media."""
import copy,re
PATTERN=re.compile(r'(?:去掉|删掉|删除|剪掉|去除)(?:前面的|后面的|这几个字|这三个字)?[“「\"]([^”」\"]{1,30})[”」\"]|(?:把)?[“「\"]([^”」\"]{1,30})[”」\"](?:这几个字|这三个字)?(?:去掉|删掉|删除|剪掉|去除)')

def compile(project,plan,messages):
 from content_safety import word_matches
 decisions={}
 for message in messages:
  if message.get('role')!='user':continue
  for match in PATTERN.finditer(message['content']):
   quote=match[1] or match[2];prefix=message['content'][max(0,match.start()-6):match.start()]
   decisions[quote]=not bool(re.search(r'(不要|不能|不许|无需|不用)[^，。；]*$',prefix))
 out=[];kept=set(plan['order'])-set(plan.get('drop',[]));refs={r['id']:r for r in project['segments']};used_quotes=set()
 for sid in plan['order']:
  row=refs[sid]
  if row['id'] not in kept or row['deleted']:continue
  for quote,delete in decisions.items():
   if not delete or quote in used_quotes:continue
   for indices in word_matches(row,quote):
    literal=''.join(row['words'][i]['word'] for i in indices)
    # No punctuation-normalized match may cut a larger multi-character token.
    if literal!=quote or indices!=list(range(indices[0],indices[-1]+1)):continue
    if not any(i not in indices and i not in row['removed'] and any(ch.isalnum() for ch in w['word']) for i,w in enumerate(row['words'])):continue
    if any(set(indices)&set(e['indices']) for e in out if e['id']==row['id']):continue
    # An instantaneous comma after a deleted leading filler is display-only,
    # but leaving it makes the reviewed subtitle falsely look rewritten.
    if indices[0]==0:
     i=indices[-1]+1
     while i<len(row['words']) and not any(ch.isalnum() for ch in row['words'][i]['word']) and row['words'][i].get('end',0)-row['words'][i].get('start',0)<=.02:
      indices.append(i);i+=1
    out.append({'id':row['id'],'indices':indices,'quote':''.join(row['words'][i]['word'] for i in indices),'requestedQuote':quote,'authority':'creator-quoted-deletion'})
    used_quotes.add(quote);break
 return out

def review_rows(rows,project,edits):
 refs={s['id']:s for s in project['segments']};out=copy.deepcopy(rows)
 for row in out:
  ids={i for e in edits if e['id']==row['id'] for i in e['indices']}
  if ids:
   ref=refs[row['id']];row['text']=''.join(ref.get('wordCorrections',{}).get(str(i),w['word']) for i,w in enumerate(ref['words']) if i not in ref['removed'] and i not in ids)
 return out

def describe(value,project,rows):
 """Let validated explicit operations describe themselves, not stale prose."""
 out=copy.deepcopy(value);plan=out.get('plan') or {};edits=plan.get('wordEdits',[])
 if not edits:return out
 out['wordEditDescriptionVersion']=1
 actual={r['id']:r['text'] for r in review_rows(rows,project,edits)}
 chosen=out.get('selected');directions=out.get('directions',[])
 if type(chosen) is int and 0<=chosen<len(directions):
  d=directions[chosen];opening=plan.get('orderStrategy',{}).get('openingIds',[])
  if opening:d['opening']=''.join(actual.get(sid,'') for sid in opening)
  words='、'.join('“'+e.get('requestedQuote',e['quote'])+'”' for e in edits)
  out['reply']='本条以“'+d['name']+'”为主线。按你的明确要求去掉'+words+'；具体保留内容和顺序见下方，生成时核对删后的声音，未通过不会输出。'
  d['tradeoff']=d.get('tradeoff','')+' '+words+'按你的要求精简；删减后的语义和声音仍需核对。'
 return out

def execute(key,record,source,project,plan,api):
 edits=plan.get('wordEdits',[])
 if not edits:return record,source,project,{'applied':False,'edits':[]}
 refs={s['id']:s for s in project['segments']}
 for e in edits:
  if e.get('authority')!='creator-quoted-deletion' or e['id'] not in refs or ''.join(refs[e['id']]['words'][i]['word'] for i in e['indices'])!=e['quote']:raise ValueError('指定删词与原话不匹配，未执行')
 import manual_word_edit
 result=manual_word_edit.run(key,record,{**project,'selectedWords':[{'id':e['id'],'index':i} for e in edits for i in e['indices']]},api)
 if not result['changed']:raise ValueError('指定删词的声音校准未通过，当前稿保留：'+result['reason'])
 updated=api.get_case(result['sourceId'])
 return updated,result['source'],result['project'],{'applied':True,'edits':edits,'calibration':result['calibration']}
