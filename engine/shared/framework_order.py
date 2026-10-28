"""Source-bound narrative order; semantic choices come from the reviewed plan."""
import copy
VERSION=1
RULE='''成片顺序规划：录制顺序不等于叙述顺序。通读全部当前可编辑原话，比较适合作开场的关键判断；反常识观点可能在中后部，允许连同其必需上下文前置。提问承载判断也可作为开场，但“第一步先别…”等省略场景的回答要连短提问一起移动。不能只按观点/支撑标签排序，更不能只按时间、数字或关键词排序。
北极星围绕一条真实反认知主线，挑选相关理由与强支撑，能力证明自然嵌入，明确人群，最后保留原有有效钩子或行动承接。四喜/业务硬控按各自目的组织，不强套反认知开场。对每个衔接检查“这个/所以/然后/第一步”是否仍有指代和前提，条件/因果/问答不得拆散；必要连续段作为一个内容组移动。数字与经历只是本人自述，不等于核验。开场场景只能引用实际开场原话，不能从后文、方向说明或标题里补出没说的主题。例如“别演、老板做成的不是演的”没有直接说明在做什么，不能在理由中虚构成“老板做IP”；应从可编辑原话补足具体场景或换一个完整判断，不强行保留不相干问题。已在正确开场的观点可以保持，不为了展示调序制造变化；原稿没有适合观点时如实说明。
必须先确定实际保留顺序，再写解释。plan额外返回orderStrategy对象：mode("reordered"或"unchanged"，与实际保留句相对当前稿的顺序一致)、reason(中文总理由)、keyClaim(null或{id,quote,reason}，quote必须为当前该句的连续原话，不能改写)、openingIds(实际开场完整语义组的原句ID；尽量简短，但必要问答和案例不能因分句数量被截断，必须是实际保留序的连续前缀)、blocks([{role:"开场"/"观点与理由"/"具体案例"/"能力证明"/"人群与问题"/"实操步骤"/"结尾承接"/"补充",ids:[本组连续成片句ID],reason:本组为何在这里}])。所有blocks.ids串起来必须精确等于order中去除drop后的全部保留句，各句恰好一次；不是固定凑齐这些角色。keyClaim若非null必须在实际保留稿中。只引用editableIds，不恢复已删除原话。'''
ROLES={'开场','观点与理由','具体案例','能力证明','人群与问题','实操步骤','结尾承接','补充'}

def edit_mode(value):
 if value not in ('full','reorder'):raise ValueError('请选择剪辑规划或只调顺序')
 return value

def normalize_reported_mode(plan,rows):
 """Compute this descriptive flag; never change the edit or its explanation.
 Selecting a late opening while dropping earlier material is not a relative
 reorder of the retained sentences. Keep the provider's claim for diagnosis.
 """
 out=copy.deepcopy(plan);strategy=out.get('orderStrategy')
 if isinstance(strategy,dict) and isinstance(strategy.get('blocks'),list):
  # A provider may list a well-formed, wholly discarded group as "待删".
  # This is explanatory metadata, not an instruction to restore its speech.
  # Keep mixed/unknown/malformed groups untouched for the strict validator.
  source_ids={r['id'] for r in rows};dropped=set(out.get('drop',[]));omitted=[];blocks=[]
  for block in strategy['blocks']:
   if (isinstance(block,dict) and set(block)=={'role','ids','reason'}
       and isinstance(block['role'],str) and block['role'] in ROLES
       and isinstance(block['reason'],str) and block['reason'].strip() and len(block['reason'])<=1200
       and isinstance(block['ids'],list) and block['ids'] and all(isinstance(sid,str) and sid in source_ids and sid in dropped for sid in block['ids'])):
    omitted.append(copy.deepcopy(block))
   else:blocks.append(block)
  if omitted:
   strategy['blocks']=blocks;out['orderOmittedBlockReceipt']={'version':1,'omitted':omitted,'reason':'仅显示实际成片保留组，已舍弃组不恢复原话'}
  aliases=[];raw_labels=out.get('labels');labels={x.get('id'):x for x in raw_labels if isinstance(x,dict) and isinstance(x.get('id'),str)} if isinstance(raw_labels,list) else {}
  for index,block in enumerate(strategy['blocks']):
   if not isinstance(block,dict):continue
   declared=block.get('role');reason=None
   if declared in ('支撑','论证机制'):reason='论证作用的显示名称归一'
   if declared=='能力证明' and isinstance(block.get('ids'),list) and block['ids']:
    members=[labels.get(sid,{}) for sid in block['ids'] if isinstance(sid,str)]
    if len(members)==len(block['ids']) and all(x.get('label')=='支撑' and isinstance(x.get('selection'),dict) and x['selection'].get('kind') in ('论证机制','论证案例','事实参数') and x['selection'].get('status')=='内容明确' for x in members):reason='整组已认定为机制案例或事实参数，不将论证支撑抬成能力证明'
   if reason:
    block['role']='观点与理由';aliases.append({'block':index,'declared':declared,'normalized':'观点与理由','reason':reason})
  if aliases:out['orderRoleReceipt']=[*out.get('orderRoleReceipt',[]),*aliases]
 if isinstance(strategy,dict) and isinstance(strategy.get('keyClaim'),dict):
  claim=strategy['keyClaim'];ref=next((r for r in rows if r['id']==claim.get('id')),None)
  bound=__import__('content_selection').literal_reference(ref['text'],claim.get('quote')) if ref else None
  if bound is not None:claim['quote']=bound
 if not isinstance(strategy,dict) or strategy.get('mode') not in ('reordered','unchanged'):return out
 ids=[sid for sid in out['order'] if sid not in out.get('drop',[])];expected=[r['id'] for r in rows if r['id'] in ids]
 computed='unchanged' if ids==expected else 'reordered'
 if strategy['mode']!=computed:
  out['orderModeReceipt']={'declared':strategy['mode'],'computed':computed,'selectionOnly':ids==expected}
  strategy['mode']=computed
 return out

def validate(plan,rows,required=True):
 value=plan.get('orderStrategy')
 if value is None and not required:return None
 ids=[sid for sid in plan['order'] if sid not in plan.get('drop',[])];by={r['id']:r for r in rows}
 if not isinstance(value,dict) or set(value)!={'mode','reason','keyClaim','openingIds','blocks'}:raise ValueError('请说明实际的成片顺序与调序理由')
 expected=[r['id'] for r in rows if r['id'] in ids];mode='unchanged' if expected==ids else 'reordered'
 if value['mode']!=mode or not isinstance(value['reason'],str) or not value['reason'].strip() or len(value['reason'])>1200:raise ValueError('调序说明与实际顺序不一致')
 opening=value['openingIds']
 if not isinstance(opening,list) or not 1<=len(opening)<=len(ids) or opening!=ids[:len(opening)]:raise ValueError('开场说明没有对应实际前几句')
 claim=value['keyClaim']
 if claim is not None:
  if not isinstance(claim,dict) or set(claim)!={'id','quote','reason'} or not isinstance(claim['id'],str) or claim['id'] not in ids or not isinstance(claim['quote'],str) or not claim['quote'].strip() or claim['quote'] not in by[claim['id']]['text'] or not isinstance(claim['reason'],str) or not claim['reason'].strip():raise ValueError('关键观点必须引用实际保留的原话')
 blocks=value['blocks']
 if not isinstance(blocks,list) or not 1<=len(blocks)<=len(ids):raise ValueError('成片内容组说明无效')
 flat=[]
 for block in blocks:
  if not isinstance(block,dict) or set(block)!={'role','ids','reason'} or not isinstance(block['role'],str) or block['role'] not in ROLES or not isinstance(block['ids'],list) or not block['ids'] or any(not isinstance(sid,str) or sid not in ids for sid in block['ids']) or not isinstance(block['reason'],str) or not block['reason'].strip() or len(block['reason'])>1200:raise ValueError('成片内容组引用或理由无效')
  flat.extend(block['ids'])
 if flat!=ids:raise ValueError('内容组必须按实际播放顺序覆盖全部保留句')
 return copy.deepcopy(value)

def difference(plan,rows):
 ids=[sid for sid in plan['order'] if sid not in plan.get('drop',[])];original=[r['id'] for r in rows if r['id'] in ids];positions={sid:i for i,sid in enumerate(original)}
 return [{'id':sid,'from':positions[sid]+1,'to':i+1} for i,sid in enumerate(ids) if positions[sid]!=i]

def apply(key,record,payload,api):
 import editor_planning,editor_workflow
 receipt=editor_planning.confirmed(record,payload,api);source,project,rows,_=editor_workflow.prepare(record,payload,api);plan=receipt['plan']
 validate(plan,rows)
 if plan.get('drop'):raise ValueError('这份方案包含删减，请选择“只调顺序”，或按完整方案成片')
 edited=editor_workflow.edited_rows(project,{**plan,'labels':[]},[r['id'] for r in rows])
 settings=copy.deepcopy(project['settings']);settings['framework']=plan['selectedFramework']
 result=api.PROJECT_LIBRARY.clean_project({**project,'segments':edited,'settings':settings},source)
 return {'kind':'editor-reorder','sourceId':source['id'],'project':result,'planningId':receipt['id'],'changed':difference(plan,rows),'orderStrategy':plan['orderStrategy']}
