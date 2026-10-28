"""Small local wrapper in the existing SAYFRAME three-panel design.

Bound to one project and a random capability URL. No directory browsing,
arbitrary file API, external connections, model credentials or desktop queue.
"""
import hashlib,json,mimetypes,secrets,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import agent,covers,planning

def serve(project,ready=None,launch_id=None):
    p=agent.project_dir(project);token=secrets.token_urlsafe(32);prefix='/'+token;job_lock=threading.Lock()
    def snapshot():
        # The source hash is checked for writes/exports. Polling the UI does
        # not hash multi-GB source videos repeatedly.
        doc=agent.read(p/'sayframe-project.json');source=agent.read(p/'source.json')
        if agent.digest(p/'source.json')!=doc['sourceSignature']:raise agent.UserError('原始文稿已被外部修改。')
        state=agent.current(doc);rev=agent.revision(doc);status=agent.read(p/'status.json')
        movie=Path(status.get('movie',''))
        available=status.get('status')=='done' and status.get('seal',{}).get('revision')==rev and movie.is_file()
        story=covers.story_revision(agent,doc);seal=status.get('seal',{})
        content_available=status.get('status')=='done' and movie.is_file() and (seal.get('storyRevision')==story or seal.get('revision')==story)
        rows=[{**{k:r[k] for k in ('id','start','end')},'text':''.join(agent.caption_map(r,state).values()),'kept':r['id'] in state['order']} for r in source['segments']]
        return {'engineVersion':agent.VERSION,'revision':rev,'settings':state['settings'],'workflow':state.get('workflow',{'directionConfirmed':True,'legacy':True}),'cover':state.get('cover'),'planning':planning.active(agent,p,doc),'methodology':state.get('methodology'),'summary':state['summary'],'order':state['order'],'segments':rows,'duration':source['duration'],'width':source['width'],'height':source['height'],'status':status,'hasCurrentMovie':available,'hasContentPreview':content_available,'canUndo':doc['cursor']>0,'canRedo':doc['cursor']+1<len(doc['history'])}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send_json(self,value,code=200):
            data=json.dumps(value,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def allowed(self):
            return self.headers.get('Host')==f'127.0.0.1:{server.server_port}' and urlsplit(self.path).path.startswith(prefix+'/')
        def send_file(self,file,download=False):
            file=Path(file);size=file.stat().st_size;start=0;end=size-1;code=200
            if value:=self.headers.get('Range'):
                import re
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
                if not match or int(match[1])>=size:self.send_error(416);return
                start=int(match[1]);end=min(size-1,int(match[2])) if match[2] else size-1;code=206
                if end<start:self.send_error(416);return
            self.send_response(code);self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            if code==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            if download:self.send_header('Content-Disposition','attachment; filename="SAYFRAME-final.mp4"')
            self.end_headers()
            with file.open('rb') as f:
                f.seek(start);left=end-start+1
                while left:
                    chunk=f.read(min(left,1024*256))
                    if not chunk:break
                    self.wfile.write(chunk);left-=len(chunk)
        def do_GET(self):
            if not self.allowed():self.send_error(404);return
            name=urlsplit(self.path).path[len(prefix):]
            try:
                if name=='/':self.send_file(agent.SKILL/'assets/workbench.html')
                elif name=='/mark.svg':self.send_file(agent.SKILL/'assets/mark.svg')
                elif name=='/api/state':self.send_json(snapshot())
                elif name=='/cover/reference':self.send_file(agent.SKILL/'assets/covers/style-reference.png')
                elif name.startswith('/cover/candidate/'):
                    sid=name.rsplit('/',1)[-1];state=snapshot();item=next((i for i in (state.get('cover') or {}).get('candidates',[]) if i['id']==sid),None)
                    if not item:raise agent.UserError('封面候选不存在。')
                    file=Path(item['file']).resolve()
                    if (p/'covers').resolve() not in file.parents or agent.digest(file)!=item['sha256']:raise agent.UserError('封面候选已变化。')
                    self.send_file(file)
                elif name=='/media/source':self.send_file(agent.read(p/'source.json')['file'])
                elif name in ('/media/final','/media/content','/download'):
                    state=snapshot()
                    if not (state['hasContentPreview'] if name=='/media/content' else state['hasCurrentMovie']):raise agent.UserError('当前稿尚无新电影，请先生成；原片不冒充成片。')
                    self.send_file(state['status']['movie'],name=='/download')
                else:self.send_error(404)
            except (agent.UserError,OSError,ValueError,KeyError):self.send_json({'error':'此工程的文件或状态暂不可读。'},409)
        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin')!=origin or self.headers.get('X-Sayframe-Token')!=token or self.headers.get('X-Sayframe-Version')!=agent.VERSION:self.send_error(403);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<1_000_000:raise agent.UserError('请求长度无效。')
                body=json.loads(self.rfile.read(length));name=urlsplit(self.path).path[len(prefix):]
                if name=='/api/apply':
                    file=p/('ui-change-'+secrets.token_hex(12)+'.json');agent.atomic(file,body['changes'])
                    try:value=agent.apply(p,file,body['revision'])
                    finally:file.unlink(missing_ok=True)
                    self.send_json(value)
                elif name in ('/api/undo','/api/redo'):self.send_json(agent.undo_redo(p,name.endswith('redo')))
                elif name=='/api/choose-plan':self.send_json(planning.choose(agent,p,body['plan'],body['direction'],body['revision'],{k:body.get(k) for k in ('confirmed','captionsEnabled','titleEnabled')}))
                elif name=='/api/cover-generate':
                    if not job_lock.acquire(False):raise agent.UserError('工程正在处理，不重复生成。')
                    try:
                        prepared=covers.prepare(agent,p,body['title'],body.get('subtitle',''),body.get('confirmed') is True)
                        self.send_json(covers.generate(agent,p,prepared['request']))
                    finally:job_lock.release()
                elif name=='/api/cover-select':self.send_json(covers.choose(agent,p,body['candidate'],body['revision']))
                elif name=='/api/export':
                    state=snapshot()
                    if state.get('cover') and not state['cover'].get('selected'):raise agent.UserError('请先选择一个封面版本。')
                    if not job_lock.acquire(False):raise agent.UserError('正在生成，不重复提交。')
                    def work():
                        try:agent.export(p)
                        except Exception as error:agent.atomic(p/'status.json',{'status':'error','stage':'export','message':str(error) if isinstance(error,agent.UserError) else '本地导出失败，原稿保留。'})
                        finally:job_lock.release()
                    thread=threading.Thread(target=work,daemon=True);thread.start();self.send_json({'status':'running'})
                else:self.send_error(404)
            except (agent.UserError,OSError,ValueError,KeyError,TypeError) as error:self.send_json({'error':str(error) if isinstance(error,agent.UserError) else '修改请求未通过检查。'},409)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);origin=f'http://127.0.0.1:{server.server_port}';url=origin+prefix+'/'
    if ready:agent.atomic(ready,{'url':url,'pid':__import__('os').getpid(),'project':str(p),'launchId':launch_id,'engineVersion':agent.VERSION})
    try:server.serve_forever()
    finally:server.server_close()

if __name__=='__main__':serve(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None,sys.argv[3] if len(sys.argv)>3 else None)
