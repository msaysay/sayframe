"""Original ASR units remain context when split into short subtitle rows.

Exact word membership only; not speaker identification or edit authority.
"""
import copy,hashlib,json,re
VERSION=1

def attach(rows,record):
 units=[];at=0
 for n,original in enumerate(record.get('segments',[])):
  words=original.get('words',[])
  if not words:continue
  want=[w['word'] for w in words];got=[];members=[]
  while len(got)<len(want) and at<len(rows):
   row=rows[at];got.extend(w['word'] for w in row.get('words',[]));members.append(row['id']);at+=1
  if got!=want:return rows
  text=''.join(want);digest=hashlib.sha256(json.dumps(want,ensure_ascii=False).encode()).hexdigest()[:8]
  units.append({'id':f'asr-u{n}-{digest}','members':members,'originalText':text,'terminalQuestion':bool(re.search(r'[？?][”」\s]*$',text)),'identityConfirmed':False,'origin':'original-asr-unit'})
 if at!=len(rows):return rows
 mapping={sid:u for u in units for sid in u['members']}
 return [{**row,**({'sourceUnit':copy.deepcopy(mapping[row['id']])} if row['id'] in mapping else {})} for row in rows]

def rows_for_review(rows):
 return [{'id':r['id'],'text':r['text'],**({'sourceUnit':r['sourceUnit']} if r.get('sourceUnit') else {})} for r in rows]

def packet(payload):
 """Deduplicate context once on the wire without changing actual row text."""
 if not isinstance(payload,dict):return payload
 fields=('transcript','original','originalContext','draftRows','actualRows');units={}
 for field in fields:
  for row in payload.get(field,[]) if isinstance(payload.get(field),list) else []:
   unit=row.get('sourceUnit') if isinstance(row,dict) else None
   if not isinstance(unit,dict):continue
   if unit.get('origin')!='original-asr-unit' or not isinstance(unit.get('id'),str) or not isinstance(unit.get('members'),list) or row.get('id') not in unit['members'] or not isinstance(unit.get('originalText'),str) or unit.get('identityConfirmed') is not False:raise ValueError('来源整句上下文无效')
   if unit['id'] in units and units[unit['id']]!=unit:raise ValueError('来源整句上下文冲突')
   units[unit['id']]=unit
 if not units:return payload
 mapping={}
 for unit in units.values():
  for sid in unit['members']:
   if sid in mapping and mapping[sid]!=unit['id']:raise ValueError('来源整句成员重复')
   mapping[sid]=unit['id']
 out=copy.deepcopy(payload)
 for field in fields:
  if not isinstance(out.get(field),list):continue
  for row in out[field]:
   if not isinstance(row,dict):continue
   row.pop('sourceUnit',None)
   if row.get('id') in mapping:row['sourceUnitId']=mapping[row['id']]
 out.update(sourceUnits=list(copy.deepcopy(units).values()),sourceContextVersion=VERSION)
 return out
