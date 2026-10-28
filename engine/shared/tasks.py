"""Persistent task history; cancellable queue and owned child processes."""
import json,pathlib,subprocess,threading,time,uuid,re,math,copy
from process_owner import ProcessOwner
from analysis_usage import usage_summary

class Cancelled(Exception):pass

class TaskStore:
    def __init__(self,folder):
        self.folder=pathlib.Path(folder);self.folder.mkdir(exist_ok=True,parents=True)
        self.lock=threading.RLock();self.local=threading.local();self.slots=threading.Semaphore(1)
        self.owner=ProcessOwner()
        self.jobs={};self.runtime={}
        for p in self.folder.glob('*.json'):
            try:
                r=json.loads(p.read_text(encoding='utf-8'))
                if (isinstance(r,dict) and r.get('id')==p.stem and re.fullmatch('[0-9a-f]{32}',p.stem)
                    and isinstance(r.get('kind'),str) and isinstance(r.get('request'),dict)
                    and r.get('status') in ('queued','running','cancelling','done','error','cancelled','interrupted')
                    and isinstance(r.get('createdAt'),(int,float)) and math.isfinite(r['createdAt'])):self.jobs[p.stem]=r
            except (OSError,ValueError,TypeError):continue
    def write(self,key):
        p=self.folder/(key+'.json');tmp=self.folder/(key+'.'+uuid.uuid4().hex+'.tmp')
        tmp.write_text(json.dumps(self.jobs[key],ensure_ascii=False,indent=2),encoding='utf-8')
        for attempt in range(8):
            try:tmp.replace(p);return
            except PermissionError:
                if attempt==7:raise
                time.sleep(.025*(attempt+1))
    def recover(self):
        # Call only when the real server starts, never as a side effect of test imports.
        with self.lock:
            for key,r in self.jobs.items():
                if r['status'] in ('queued','running','cancelling'):
                    r.update(status='interrupted',message='服务重启，原任务已中断；可按原方案重新运行',endedAt=time.time());self.write(key)
    def check(self,key=None):
        key=key or getattr(self.local,'key',None)
        if key in self.runtime and self.runtime[key]['cancel'].is_set():raise Cancelled('任务已取消')
    def progress(self,key,message,detail=None):
        self.check(key)
        with self.lock:
            if key in self.jobs:
                self.jobs[key]['message']=message
                if detail is not None:self.jobs[key]['progress']=copy.deepcopy(detail)
                self.write(key)
    def analysis_attempt(self,key,record):
        with self.lock:
            if key in self.jobs:
                attempts=self.jobs[key].setdefault('analysisAttempts',[]);attempts.append(record)
                self.jobs[key]['usageSummary']=usage_summary(attempts);self.write(key)
    def planning_checkpoint(self,key,record):
        with self.lock:
            if key in self.jobs:self.jobs[key]['planningCheckpoint']=copy.deepcopy(record);self.write(key)
    def submit(self,kind,title,request,work,parent=None,request_token=None):
        if request_token is not None and (not isinstance(request_token,str) or not re.fullmatch('[a-f0-9]{32}',request_token)):raise ValueError('提交标识无效')
        key=uuid.uuid4().hex
        with self.lock:
            if parent and kind=='editor-auto':
                active=next((r for r in self.jobs.values() if r.get('parentId')==parent and r['kind']==kind and r['status'] in ('queued','running','cancelling')),None)
                if active:return active['id']
            if request_token is not None:
                for previous in self.jobs.values():
                    if previous.get('requestToken')==request_token:
                        if previous['kind']!=kind or previous['request']!=request:raise ValueError('同一提交标识的参数已变化，请恢复原提交或明确新建规划')
                        return previous['id']
            self.jobs[key]={'id':key,'kind':kind,'title':title,'request':copy.deepcopy(request),'status':'queued','message':'等待处理','createdAt':time.time(),'parentId':parent,**({'requestToken':request_token} if request_token is not None else {})}
            self.runtime[key]={'cancel':threading.Event(),'process':None}
            try:self.write(key)
            except Exception:
                self.jobs.pop(key,None);self.runtime.pop(key,None);raise
        def run():
            acquired=False;self.local.key=key
            try:
                while not acquired:self.check(key);acquired=self.slots.acquire(timeout=.1)
                self.check(key)
                with self.lock:self.jobs[key].update(status='running',message='准备处理',startedAt=time.time());self.write(key)
                result=work(key)
                with self.lock:
                    self.check(key);self.jobs[key].update(status='done',message='已完成',result=result,endedAt=time.time());self.write(key)
            except Exception as e:
                with self.lock:
                    cancelled=isinstance(e,Cancelled) or self.runtime[key]['cancel'].is_set()
                    self.jobs[key].update(status='cancelled' if cancelled else 'error',message='已取消；原素材保留' if cancelled else str(e)[-1500:],endedAt=time.time());self.write(key)
            finally:
                if acquired:self.slots.release()
                with self.lock:self.runtime.pop(key,None)
                self.local.key=None
        threading.Thread(target=run,daemon=True).start();return key
    def get(self,key):
        with self.lock:
            if key not in self.jobs:raise ValueError('任务不存在')
            r={k:v for k,v in self.jobs[key].items() if k!='request'}
            if r['kind']=='automatic-edit':
                r['automaticOptions']={k:self.jobs[key]['request'].get(k) for k in ('sourceId','font','framework','music','planJobId')};r['automaticCheckpoint']=(self.folder.parent/'data'/('automatic-semantic-'+key+'.json')).is_file()
            if r['kind']=='audio-roles':r['audioRoles']={k:self.jobs[key]['request'].get(k) for k in ('sourceId','start','end')}
            if r['kind']=='content-plan':r['planning']={k:self.jobs[key]['request'].get(k) for k in ('sourceId','frameworks','targetSeconds','thinking')}
            if r['kind'] in ('candidate-meaning','candidate-meaning-v2'):r['meaningReview']={k:self.jobs[key]['request'].get(k) for k in ('sourceId','candidateId','bindingSha256')}
            if r['kind']=='content-plan' and 'scope' in self.jobs[key]['request']:r['planning']['scope']=copy.deepcopy(self.jobs[key]['request']['scope'])
            if r['kind']=='content-plan' and 'wireVersion' in self.jobs[key]['request']:r['planning']['wireVersion']=self.jobs[key]['request']['wireVersion']
            if r['kind']=='content-plan' and 'resumeJobId' in self.jobs[key]['request']:r['planning']['resumeJobId']=self.jobs[key]['request']['resumeJobId']
            if r['kind']=='content-plan' and 'selectionParentJobId' in self.jobs[key]['request']:r['planning']['selectionParentJobId']=self.jobs[key]['request']['selectionParentJobId']
            if r['kind']=='content-topics':r['contentTopics']={k:copy.deepcopy(self.jobs[key]['request'].get(k)) for k in ('sourceId','audioJobIds')}
            if r['kind']=='topic-plan':r['topicPlanning']={k:self.jobs[key]['request'].get(k) for k in ('topicId','revision','contractVersion','contractRevision')};r['topicPlanning']['contractVersion']=r['topicPlanning']['contractVersion'] or 1;r['topicPlanning']['contractRevision']=r['topicPlanning']['contractRevision'] or 1
            if r['kind']=='topic-source':r['topicSource']={k:self.jobs[key]['request'].get(k) for k in ('topicId','revision','provider')}
            if r['kind']=='topic-keywords':r['keywordExtraction']={'sourceCount':len(self.jobs[key]['request']['topicIds']),'includeComments':self.jobs[key]['request']['includeComments'],'engineVersion':self.jobs[key]['request']['engineVersion']}
            if r['kind']=='topic-keyword-search':
                req=self.jobs[key]['request'];r['keywordSearch']={k:req.get(k) for k in ('keywordId','scope','includeComments','trigger','scheduleId','slotAt')};r['keywordSearch']['word']=req['keyword']['word'];r['keywordSearch']['sourceCount']=len(req['context']['sources'])
            if r['kind']=='source-media':r['sourceMaterial']={k:self.jobs[key]['request'].get(k) for k in ('topicId','language','revision')}
            if r['kind']=='topic-discovery':
                req=self.jobs[key]['request'];r['discovery']={k:req.get(k) for k in ('mode','keyword','pages','order','inputLinkCount')}
            if r['kind']=='render-candidate':
                request=self.jobs[key]['request'];r['composition']={k:request.get(k) for k in ('sourceId','candidateId','canvas','subtitle','packaging','clientFingerprint')};r['composition']['workspaceId']=request.get('workspace',{}).get('id')
            if r['kind']=='composition-frame':
                request=self.jobs[key]['request'];r['framePreview']={k:request.get(k) for k in ('sourceId','candidateId','bindingSha256','clipKey','previewSeconds')};r['framePreview']['workspaceId']=request['workspace']['id']
            if r['kind']=='composition-scan':
                request=self.jobs[key]['request'];r['frameScan']={k:request.get(k) for k in ('sourceId','candidateId','bindingSha256','sampleStep')};r['frameScan']['workspaceId']=request['workspace']['id']
            if r['kind']=='source-text-regions':r['sourceText']={k:self.jobs[key]['request'].get(k) for k in ('scanJobId','ocrScopeSha256')}
            if r['kind']=='cover-preview':r['coverPreview']={k:copy.deepcopy(self.jobs[key]['request'].get(k)) for k in ('outputJobId','bindingSha256','cover')}
            if r['kind']=='composition-plan':r['multiPlanning']={k:self.jobs[key]['request'].get(k) for k in ('sourceId','candidateId','frameworks','targetSeconds','thinking')};r['multiPlanning']['workspaceId']=self.jobs[key]['request'].get('workspace',{}).get('id')
            r['canRetry']=r['kind'] in ('editor-import','editor-auto','automatic-edit','render','render-candidate','cover','cover-ai','transcribe','demo','mimo','mix-preview','content-plan') and (r['status'] in ('cancelled','error','interrupted') or (r['kind']=='editor-auto' and r['status']=='done' and isinstance(r.get('result'),dict) and bool(r['result'].get('video'))))
            p=self.runtime.get(key,{}).get('process');r['activeProcessId']=p.pid if p and p.poll() is None else None
            return r
    def meaning_listing(self,source_id,binding,kind='candidate-meaning'):
        if not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding):raise ValueError('文意复核指纹无效')
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']==kind and r['request'].get('sourceId')==source_id and r['request'].get('bindingSha256')==binding]
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def composition_listing(self,source_id,workspace_id,candidate_id):
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']=='render-candidate' and r['request'].get('sourceId')==source_id and r['request'].get('candidateId')==candidate_id and r['request'].get('workspace',{}).get('id')==workspace_id]
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def frame_listing(self,source_id,workspace_id,candidate_id,binding,kind='composition-frame'):
        if kind not in ('composition-frame','composition-scan'):raise ValueError('帧任务种类无效')
        if not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding):raise ValueError('帧预览指纹无效')
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']==kind and r['request'].get('sourceId')==source_id and r['request'].get('candidateId')==candidate_id and r['request'].get('workspace',{}).get('id')==workspace_id and r['request'].get('bindingSha256')==binding]
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def topic_listing(self,topic_id,kind='topic-plan'):
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']==kind and r['request'].get('topicId')==topic_id]
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def source_text_listing(self,scope):
        if not isinstance(scope,str) or not re.fullmatch('[a-f0-9]{64}',scope):raise ValueError('OCR查询指纹无效')
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']=='source-text-regions' and r['request'].get('ocrScopeSha256')==scope]
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def cover_listing(self,output_id,binding):
        if not isinstance(output_id,str) or not re.fullmatch('[a-f0-9]{32}',output_id) or not isinstance(binding,str) or not re.fullmatch('[a-f0-9]{64}',binding):raise ValueError('封面查询范围无效')
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']=='cover-preview' and r['request'].get('outputJobId')==output_id and r['request'].get('bindingSha256')==binding]
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def listing(self):
        with self.lock:
            rows=[self.get(r['id']) for r in sorted(self.jobs.values(),key=lambda r:r['createdAt'],reverse=True)[:100]]
            for r in rows:
                if r['kind']=='transcribe' and 'result' in r:r['result']={k:r['result'][k] for k in ('id','title','hasVideo')}
            return rows
    def keyword_listing(self):
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']=='topic-keywords']
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def keyword_search_listing(self,keyword_id):
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']=='topic-keyword-search' and r['request'].get('keywordId')==keyword_id]
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def discovery_listing(self):
        with self.lock:
            rows=[r for r in self.jobs.values() if r['kind']=='topic-discovery']
            return [self.get(r['id']) for r in sorted(rows,key=lambda r:r['createdAt'],reverse=True)[:100]]
    def cancel(self,key):
        with self.lock:
            r=self.get(key)
            if r['status'] not in ('queued','running','cancelling'):return r
            message='已请求取消，等待当前识别段结束' if r['kind']=='transcribe' else '正在停止处理'
            self.runtime[key]['cancel'].set();self.jobs[key].update(status='cancelling',message=message);self.write(key)
            p=self.runtime[key]['process']
            if p and p.poll() is None:
                try:p.terminate()
                except OSError:pass
            return self.get(key)
    def process(self,args,cwd=None,timeout=None,check_callback=None):
        self.check();key=getattr(self.local,'key',None)
        p=subprocess.Popen(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:self.owner.attach(p)
        except Exception:
            p.terminate();p.communicate();raise
        with self.lock:
            if key in self.runtime:self.runtime[key]['process']=p
        deadline=time.monotonic()+timeout if timeout is not None else None
        try:
            while True:
                self.check()
                if check_callback:check_callback()
                if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('处理超时，已停止本次子进程；没有自动重试')
                try:out,err=p.communicate(timeout=.2);break
                except subprocess.TimeoutExpired:continue
            self.check()
            if self.owner.closed:raise RuntimeError('处理进程所属服务已关闭')
            if p.returncode:raise RuntimeError(err[-1500:])
            return out
        except Exception:
            if p.poll() is None:
                p.terminate()
                try:p.communicate(timeout=3)
                except subprocess.TimeoutExpired:p.kill();p.communicate()
            raise
        finally:
            with self.lock:
                if key in self.runtime:self.runtime[key]['process']=None
