"""One export: video, its first-frame cover, and an optional complete delivery bundle."""
import json,re,shutil,zipfile
from pathlib import Path

def cover_image(folder,record,payload,api):
    from PIL import Image,ImageDraw,ImageFont
    settings=payload['settings'];selected=payload.get('coverImage') or settings.get('coverImage')
    if selected:
        if not isinstance(selected,str) or not re.fullmatch(r'/outputs/[a-f0-9]{32}/cover(?:-[012])?\.png',selected):raise ValueError('封面图片引用无效')
        path=api.ROOT/selected.lstrip('/')
        if not path.is_file():raise ValueError('选定封面已不存在，请重新选择')
        # Check the owning output's source before accepting its image.
        owner_path=path.parent/'project.json'
        if not owner_path.is_file():owner_path=path.parent/'cover-settings.json'
        owner=json.loads(owner_path.read_text('utf-8'))
        if owner['sourceId']!=record['video_id']:raise ValueError('封面与当前视频不匹配')
        if owner.get('renderer')=='minimax-image-01':
            import minimax_cover,hashlib
            review_path=path.parent/'generation-review.json'
            review=json.loads(review_path.read_text('utf8')).get('review',{}) if review_path.is_file() else {}
            if review.get('passed') is not True or review.get('issues')!=[]:raise ValueError('生图封面尚未通过人物与文字检查')
            if owner.get('binding')!=minimax_cover.binding(record['video_id'],settings):raise ValueError('生图封面与当前文字或选帧不匹配，请重新生成')
            if owner.get('imageSha256')!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('生图封面文件已变化，请重新生成')
            shutil.copyfile(path,folder/'cover.png');return folder/'cover.png'
        if not settings.get('presentation',{}).get('enabled',True):
            shutil.copyfile(path,folder/'cover.png');return folder/'cover.png'
    title,subtitle,template,t=api.cover_fields({'title':settings.get('coverTitle') or record['title'].split('#')[0][:14],'subtitle':settings.get('coverSubtitle',''),'template':settings.get('coverTemplate','classic'),'time':settings.get('coverTime',min(1,record['duration_seconds']/2))},record['duration_seconds'])
    frame=folder/'cover-frame.png';api.command(['-ss',str(t),'-i',str(record['video_path']),'-frames:v','1',str(frame)])
    if settings.get('presentation',{}).get('enabled',True):
        from video_finish import cover
        cover(Image.open(frame),settings,api.ROOT/'fonts/NotoSansSC.ttf').save(folder/'cover.png');return folder/'cover.png'
    im=Image.open(frame).convert('RGB');draw=ImageDraw.Draw(im);size=max(16,round(im.width/11));font=ImageFont.truetype(str(api.ROOT/'fonts/NotoSansSC.ttf'),size);font.set_variation_by_axes([700]);small=ImageFont.truetype(str(api.ROOT/'fonts/NotoSansSC.ttf'),max(12,size//2));lines=[];line=''
    for ch in title:
        if line and draw.textlength(line+ch,font=font)>im.width*.86:lines.append(line);line=''
        line+=ch
    if line:lines.append(line)
    height=round(size*(len(lines)*1.3+1.8));y=round(im.height*.05) if template!='minimal' else max(0,im.height-height)
    layer=Image.new('RGBA',im.size);ld=ImageDraw.Draw(layer);ld.rectangle((0,max(0,y-size*.3),im.width,min(im.height,y+height)),fill=(15,18,22,190));im=Image.alpha_composite(im.convert('RGBA'),layer);draw=ImageDraw.Draw(im)
    for line in lines:draw.text(((im.width-draw.textlength(line,font=font))/2,y),line,font=font,fill='white');y+=round(size*1.25)
    if subtitle:
        sublines=[];line=''
        for ch in subtitle:
            if line and draw.textlength(line+ch,font=small)>im.width*.86:sublines.append(line);line=''
            line+=ch
        if line:sublines.append(line)
        for line in sublines:draw.text(((im.width-draw.textlength(line,font=small))/2,y),line,font=small,fill='#f3cf9f');y+=round(small.size*1.3)
    im.convert('RGB').save(folder/'cover.png');return folder/'cover.png'

def bundle(folder,output):
    path=folder/'成片交付.zip'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as z:
        for file,name in [(output,'成片.mp4'),(folder/'cover.png','封面.png'),(folder/'captions.srt','字幕.srt'),(folder/'project.json','编辑工程.json'),(folder/'music-attribution.txt','配乐署名.txt')]:
            if file.is_file():z.write(file,name)
    return path
