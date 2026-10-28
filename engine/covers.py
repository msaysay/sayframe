"""Reference-led covers; original subject stays in the student's local frame.

Generated assets are decoration only. Confirmed text is typeset exactly. A
selection is immutable, source-bound, undoable, and compiled into frame zero.
"""
import copy,json,math,re,uuid
from pathlib import Path

STYLES=[('teal','青绿笔触','#073e40','#fff4d5','#71b6a0','MaShanZheng-Regular.ttf'),('ivory','浅底大字','#f4f0e7','#182c2e','#bb412b','NotoSansSC-Regular.ttf'),('ink','黑金重点','#151b20','#fff3db','#d3ae62','NotoSansSC-Regular.ttf')]

def story_revision(agent,doc):
    stripped=copy.deepcopy(doc);stripped['history']=[{k:v for k,v in agent.current(doc).items() if k!='cover'}];stripped['cursor']=0
    return agent.revision(stripped)

def confirmed_text(agent,title,subtitle,confirmed):
    if not confirmed:raise agent.UserError('请先让用户确认封面文字，再生成版本。')
    title=title.strip();subtitle=subtitle.strip()
    if not title or len(title)>24 or len(subtitle)>28 or re.search(r'[\x00-\x1f]',title+subtitle):raise agent.UserError('封面主标题须为1–24字，副标题最多28字，不能含控制字符。')
    return title,subtitle

def current_base(agent,p,doc):
    status=agent.read(p/'status.json');seal=status.get('seal',{});story=story_revision(agent,doc)
    if status.get('status')!='done' or not (seal.get('storyRevision')==story or seal.get('revision')==story or seal.get('revision')==agent.revision(doc)):
        raise agent.UserError('请先生成当前剪辑稿，再制作这条视频的封面。')
    movie=Path(status.get('movie',''))
    if not movie.is_file() or agent.digest(movie)!=seal.get('movieSha256'):raise agent.UserError('当前成片已变化，不能沿用旧封面来源。')
    return status,story

def retained_frame_time(agent,status,source,at):
    compiled_file=Path(status['export'])/'compiled.json'
    if not compiled_file.is_file():raise agent.UserError('当前成片缺少原片映射，请重新生成，不能随意抽其他片段。')
    compiled=agent.read(compiled_file)
    if compiled.get('sourceSha256')!=source['mediaSha256'] or compiled.get('revision')!=status['seal']['revision']:raise agent.UserError('成片原片映射不一致。')
    position=max(0,at-status['seal'].get('cover',{}).get('silentLeadSeconds',0));speed=compiled['settings']['speed']
    clips=compiled['clips']
    for clip in clips:
        duration=(clip['end']-clip['start'])/speed
        if position<duration:return max(clip['start'],min(clip['end']-.005,clip['start']+position*speed))
        position-=duration
    return max(clips[-1]['start'],clips[-1]['end']-.05)

def prepare(agent,project,title,subtitle,confirmed=False):
    title,subtitle=confirmed_text(agent,title,subtitle,confirmed);p,doc,source=agent.load_project(project)
    with agent.lock(p):
        doc=agent.read(p/'sayframe-project.json');status,story=current_base(agent,p,doc)
        folder=p/'covers'/uuid.uuid4().hex;folder.mkdir(parents=True)
        # Map CURRENT finished film back to retained raw source, avoiding the
        # subtitles/title already burned into the finished movie.
        from PIL import Image,ImageFilter,ImageStat
        candidates=[];duration=status['seal']['duration']
        for n,at in enumerate([min(max(.15,duration*.08),duration*.8),min(max(.3,duration*.16),duration*.85),min(max(.45,duration*.24),duration*.9)]):
            source_at=retained_frame_time(agent,status,source,at)
            frame=folder/f'frame-{n+1}.png';agent.run([agent.tool('ffmpeg'),'-v','error','-ss',source_at,'-i',source['file'],'-frames:v','1','-vf','scale=1080:-2',frame])
            with Image.open(frame) as image:
                gray=image.convert('L');mean=ImageStat.Stat(gray).mean[0];score=ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]-abs(mean-130)/50
            candidates.append((score,frame,at,source_at))
        _,frame,at,source_at=max(candidates,key=lambda x:x[0])
        reference=agent.SKILL/'assets/covers/style-reference.png'
        prompts=[]
        for sid,label,bg,fg,accent,font in STYLES:
            prompts.append({'id':sid,'style':label,'prompt':f'为专家口播视频封面制作无文字的装饰底纹。只参考输入示意图中{label}这一栏的色彩和笔触。画布竖版，底色{bg}，克制点缀色{accent}，上方约三分之一留干净的标题区。主题为已确认文字“{title} / {subtitle}”，但图上不要生成任何文字、数字、标志、雕塑、人物或人脸。不复用参考示意人物，不虚构人物资历。后续程序会放入用户真实视频画面并精确排字。保持简洁、清爽、低纹理干扰。','image1':str(reference),'size':'1024x1536','quality':'medium','output_dir':str(folder/'native'/sid)})
        request={'version':1,'id':folder.name,'revision':agent.revision(doc),'storyRevision':story,'sourceSha256':source['mediaSha256'],'title':title,'subtitle':subtitle,'textConfirmed':True,'baseMovieSha256':status['seal']['movieSha256'],'frame':str(frame),'frameSha256':agent.digest(frame),'movieFrameTime':at,'sourceFrameTime':source_at,'frameOrigin':'retained-original-source','reference':str(reference),'referenceSha256':agent.digest(reference),'prompts':prompts,'notice':'可调用当前WorkBuddy原生ImageGen逐次生成3张无人物/无文字背景；遵守工具用量提示。没有生图能力时可直接用内置版式生成，不能称AI生图。'}
        agent.atomic(folder/'request.json',request);return {'request':str(folder/'request.json'),**request}

def font(agent,name,size):
    from PIL import ImageFont
    face=ImageFont.truetype(str(agent.SKILL/'assets/fonts'/name),max(1,size))
    if name.startswith('Noto'):
        try:face.set_variation_by_axes([800])
        except (ValueError,OSError,AttributeError):pass
    return face

def render(agent,frame,request,style,dest,background=None):
    from PIL import Image,ImageDraw,ImageOps
    sid,label,bg,fg,accent,typeface=style
    with Image.open(frame) as raw:base=raw.convert('RGB')
    w,h=base.size;portrait=h>w;header=round(h*(.34 if portrait else .4))
    # Decoration is confined to the title zone. The real subject/photo pixels
    # below it are unchanged; no generative portrait, face swap or beauty pass.
    if background:
        with Image.open(background) as artwork:top=ImageOps.fit(artwork.convert('RGB'),(w,header))
    else:top=Image.new('RGB',(w,header),bg)
    mask=Image.new('L',(w,header));md=ImageDraw.Draw(mask)
    for y in range(header):md.line((0,y,w,y),fill=255 if y<header*.78 else round(255*(header-y)/(header*.22)))
    base.paste(top,(0,0),mask);draw=ImageDraw.Draw(base);margin=round(w*.09)
    title=request['title'];lines=[line for line in re.split('[，,：:；;]',title) if line]
    if len(lines)!=2:
        lines=[title] if len(title)<=9 or not portrait else [title[:math.ceil(len(title)/2)],title[math.ceil(len(title)/2):]]
    size=round(w*(.12 if portrait else .067));face=font(agent,typeface,size)
    max_width=w-2*margin
    while size>round(w*.035) and max(draw.textlength(line,font=face) for line in lines)>max_width:
        size-=1;face=font(agent,typeface,size)
    if max(draw.textlength(line,font=face) for line in lines)>max_width:raise agent.UserError('封面文字过长，请缩短后重新确认。')
    y=round(h*.065);line_h=round(size*1.25)
    for line in lines:
        draw.text((margin,y),line,font=face,fill=fg,stroke_width=max(0,round(w*.001)),stroke_fill=bg);y+=line_h
    draw.rectangle((margin,y+round(h*.01),margin+round(w*.13),y+round(h*.014)),fill=accent)
    if request['subtitle']:
        small_size=round(w*.047);small=font(agent,'NotoSansSC-Regular.ttf',small_size)
        while small_size>round(w*.026) and draw.textlength(request['subtitle'],font=small)>max_width:small_size-=1;small=font(agent,'NotoSansSC-Regular.ttf',small_size)
        if draw.textlength(request['subtitle'],font=small)>max_width:raise agent.UserError('封面副标题过长。')
        draw.text((margin,y+round(h*.025)),request['subtitle'],font=small,fill=fg)
    base.save(dest,quality=95,subsampling=0)
    return {'id':sid,'label':label,'file':str(dest),'sha256':agent.digest(dest),'width':w,'height':h,'provider':'supplied-decoration+exact-local-type' if background else 'built-in-reference-layout','backgroundSha256':agent.digest(background) if background else None,'title':request['title'],'subtitle':request['subtitle']}

def generate(agent,project,request_file,backgrounds_file=None):
    p,doc,source=agent.load_project(project);request_path=Path(request_file).resolve()
    if request_path.parent.parent!=p/'covers' or request_path.name!='request.json':raise agent.UserError('封面请求不属于当前工程。')
    request=agent.read(request_path);folder=request_path.parent
    with agent.lock(p):
        doc=agent.read(p/'sayframe-project.json')
        if request['revision']!=agent.revision(doc) or request['sourceSha256']!=source['mediaSha256'] or request.get('textConfirmed') is not True:raise agent.UserError('封面文字或工程已变化，请重新确认，不覆盖较新的稿。')
        confirmed_text(agent,request['title'],request['subtitle'],True)
        if agent.digest(request['frame'])!=request['frameSha256'] or agent.digest(request['reference'])!=request['referenceSha256']:raise agent.UserError('封面参考或原帧变化，请重新准备。')
        backgrounds=agent.read(backgrounds_file) if backgrounds_file else {}
        if backgrounds and (not isinstance(backgrounds,dict) or set(backgrounds)!={s[0] for s in STYLES}):raise agent.UserError('生图背景需提供teal/ivory/ink三份实际本地图片。')
        variants=folder/('variants-'+uuid.uuid4().hex);variants.mkdir();items=[]
        for style in STYLES:
            background=Path(backgrounds[style[0]]).resolve() if backgrounds else None
            if background and not background.is_file():raise agent.UserError('生图结果未实际落盘。')
            items.append(render(agent,request['frame'],request,style,variants/(style[0]+'.jpg'),background))
        state=copy.deepcopy(agent.current(doc));state['cover']={'version':1,'title':request['title'],'subtitle':request['subtitle'],'textConfirmed':True,'storyRevision':request['storyRevision'],'sourceSha256':source['mediaSha256'],'frameSha256':request['frameSha256'],'request':str(request_path),'candidates':items,'selected':None,'leadFrames':1}
        agent.commit(p,doc,state)
        return {'status':'cover-options-ready','revision':agent.revision(doc),'candidates':items,'notice':'已生成三个版本，等待用户选择；未擅自选择或合成。'}

def choose(agent,project,candidate,expect):
    p,doc,source=agent.load_project(project)
    with agent.lock(p):
        doc=agent.read(p/'sayframe-project.json')
        if agent.revision(doc)!=expect:raise agent.UserError('工程已变化，请重新读取封面候选。')
        state=copy.deepcopy(agent.current(doc));cover=state.get('cover',{})
        item=next((item for item in cover.get('candidates',[]) if item['id']==candidate),None)
        if not item or cover.get('storyRevision')!=story_revision(agent,doc) or agent.digest(item['file'])!=item['sha256']:raise agent.UserError('该封面不属于当前剪辑稿或图片已变化。')
        cover['selected']=candidate;state['cover']=cover;agent.commit(p,doc,state)
        return {'status':'cover-selected','revision':agent.revision(doc),'candidate':candidate,'notice':'选中封面将写入下一次成片首帧；仍可撤销或换版。'}

def selected(agent,project,state,doc):
    cover=state.get('cover')
    if not cover:return None
    if not cover.get('selected'):raise agent.UserError('请先选择一个封面版本，再导出。')
    if cover['storyRevision']!=story_revision(agent,doc):raise agent.UserError('剪辑内容已变化，请重新确认并生成对应封面。')
    item=next((item for item in cover['candidates'] if item['id']==cover['selected']),None)
    if not item or agent.digest(item['file'])!=item['sha256']:raise agent.UserError('封面文件已变化，请重新生成。')
    path=Path(item['file']).resolve()
    if (Path(project)/'covers').resolve() not in path.parents:raise agent.UserError('封面文件不是当前工程生成的候选。')
    return item
