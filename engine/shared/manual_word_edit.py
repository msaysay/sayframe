"""User-selected word deletion with a verified acoustic revision when needed."""
import copy

def selected_words(project,value):
 if not isinstance(value,list) or not value or len(value)>1000:raise ValueError('请先选择要删除的字')
 rows={r['id']:r for r in project['segments']};out={}
 for item in value:
  if not isinstance(item,dict) or set(item)!={'id','index'} or not isinstance(item['id'],str) or item['id'] not in rows or type(item['index']) is not int:raise ValueError('所选原词无效')
  row=rows[item['id']];i=item['index']
  if row['deleted'] or not 0<=i<len(row['words']) or i in row['removed']:raise ValueError('所选文字已变化，请重新选择')
  out.setdefault(item['id'],set()).add(i)
 return out

def run(key,record,payload,api,*,reviewed_excerpts=(),publish_targets_only=False):
 import editor_workflow,speech_alignment
 source,before,_,_=editor_workflow.prepare(record,payload,api);selected=selected_words(before,payload.get('selectedWords'));project=copy.deepcopy(before)
 for row in project['segments']:
  if row['id'] not in selected:continue
  row['removed']=sorted(set(row['removed'])|selected[row['id']]);row.pop('caption',None)
  if 'protectedIndices' in row:row['protectedIndices']=[i for i in row['protectedIndices'] if i not in selected[row['id']]]
  if len(row['removed'])==len(row['words']):row['deleted']=True
 targets=[r['id'] for r in project['segments'] if r['id'] in selected and not r['deleted']]
 options={}
 if reviewed_excerpts:
  options={'base_removed':{r['id']:r['removed'] for r in before['segments']},'reviewed_excerpts':reviewed_excerpts}
 if publish_targets_only:
  if not reviewed_excerpts:raise ValueError('局部声音发布缺少已复核陈述方案')
  options['publish_targets_only']=True
 revised,p,receipt=speech_alignment.revise(record,project,targets,api,key,**options) if targets else (record,project,{'applied':False,'reason':'删除整句不需单字校准'})
 if targets:
  path=api.ROOT/'recognition-cache'/receipt.get('receipt','missing')
  evidence=__import__('json').loads(path.read_text('utf8')) if path.is_file() else {}
  audits={e['id']:e for e in evidence.get('entries',[])} if isinstance(evidence,dict) else {}
  passed={sid for sid,e in audits.items() if e.get('applied') and e.get('audits') and all(a.get('passed') for a in e['audits']) and selected[sid].intersection(i for i,w in enumerate(e['words']) if any(c.isalnum() for c in w['word'])).issubset({i for a in e['audits'] for i in a.get('indices',[])})}
  if not set(targets).issubset(passed):
   # Diagnostics nominate a possible smaller transaction, never authorize it.
   # A caller must re-audition that exact mask from the original source.
   review={'passedIds':sorted(set(targets)&passed),'held':[{'id':sid,'indices':sorted(selected[sid]),'audits':copy.deepcopy(audits.get(sid,{}).get('audits',[]))} for sid in targets if sid not in passed]}
   return {'kind':'word-edit','source':source,'project':before,'changed':False,'reason':'这几个字的声音边界还不够确定，本次保留原话，可扩大选词范围后再删。','calibration':receipt,'acousticReview':review}
 new_source=api.public_case(revised,True)
 return {'kind':'word-edit','source':new_source,'sourceId':new_source['id'],'project':p,'changed':True,'calibration':receipt,'removedWords':sum(len(v) for v in selected.values())}
