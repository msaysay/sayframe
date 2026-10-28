"""Contract and safety regressions for the real student command implementation."""
import contextlib,copy,importlib.util,io,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
spec=importlib.util.spec_from_file_location('agent',ROOT/'engine/agent.py');agent=importlib.util.module_from_spec(spec);sys.modules['agent']=agent;spec.loader.exec_module(agent)
native_spec=importlib.util.spec_from_file_location('native_audio',ROOT/'engine/native_audio.py');native_audio=importlib.util.module_from_spec(native_spec);native_spec.loader.exec_module(native_audio)

class EditingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.project=self.root/'project';self.project.mkdir();media=self.root/'source.mp4';media.write_bytes(b'fixture-only')
  # Acoustic semantics are tested separately on real recordings; these are contract/render fixtures.
  self.model_stub=patch.object(agent,'model_dir',return_value=self.root/'unused-test-model');self.model_stub.start();self.addCleanup(self.model_stub.stop)
  self.source={'file':str(media),'mediaSha256':agent.digest(media),'duration':4,'width':1080,'height':1920,'segments':[{'id':'s1','start':0,'end':2,'text':'不能删啊','words':[{'word':'不','start':0,'end':.3},{'word':'能删','start':.3,'end':1},{'word':'啊','start':1,'end':2}]},{'id':'s2','start':2,'end':4,'text':'正常内容','words':[{'word':'正常内容','start':2,'end':4}]}]}
  agent.atomic(self.project/'source.json',self.source);self.state={'title':'fixture','order':['s1','s2'],'removed':{},'corrections':{},'settings':{'title':'fixture','name':'','intro':'','framework':'观点破题','voice':1,'musicVolume':.07,'musicFile':None,'speed':1,'font':'NotoSansSC-Regular.ttf','titleFont':'MaShanZheng-Regular.ttf','identityRanges':[]},'summary':'fixture'}
  self.doc={'format':'sayframe-agent','sourceSignature':agent.digest(self.project/'source.json'),'history':[self.state],'cursor':0};agent.atomic(self.project/'sayframe-project.json',self.doc);agent.atomic(self.project/'status.json',{'status':'done'})
 def tearDown(self):self.tmp.cleanup()
 def apply(self,changes,rev=None):
  f=self.root/'changes.json';agent.atomic(f,changes);return agent.apply(self.project,f,rev or agent.revision(agent.read(self.project/'sayframe-project.json')))
 def test_reorder_restore_and_persistent_undo_redo(self):
  self.apply({'summary':'只留后一句','order':['s2']});self.apply({'summary':'前句放后面','order':['s2','s1']})
  self.assertEqual(agent.current(agent.read(self.project/'sayframe-project.json'))['order'],['s2','s1'])
  agent.undo_redo(self.project);self.assertEqual(agent.current(agent.read(self.project/'sayframe-project.json'))['order'],['s2'])
  agent.undo_redo(self.project,True);self.assertEqual(agent.current(agent.read(self.project/'sayframe-project.json'))['order'],['s2','s1'])
 def sealed_fixture(self,name,doc,source=None):
  folder=self.project/'exports'/name;folder.mkdir(parents=True);movie=folder/'final.mp4';movie.write_bytes(b'sealed-test-movie');(folder/'preview.html').write_text('test-preview')
  rev=agent.revision(doc);agent.atomic(folder/'compiled.json',{'revision':rev,'sourceSha256':(source or self.source)['mediaSha256']})
  seal={'revision':rev,'renderVersion':agent.RENDER_VERSION,'movieSha256':agent.digest(movie),'movieBytes':movie.stat().st_size,'duration':4};agent.atomic(folder/'seal.json',seal)
  return folder
 def test_undo_redo_recovers_exact_sealed_movies_without_reencoding(self):
  original=self.sealed_fixture('first',self.doc);self.apply({'summary':'缩短标题','settings':{'title':'短标题'}})
  changed=agent.read(self.project/'sayframe-project.json');second=self.sealed_fixture('second',changed)
  agent.atomic(self.project/'status.json',{'status':'done','stage':'export','movie':str(second/'final.mp4')})
  result=agent.undo_redo(self.project);self.assertTrue(result['movieRestored']);self.assertEqual(agent.read(self.project/'status.json')['movie'],str(original/'final.mp4'))
  result=agent.undo_redo(self.project,True);self.assertTrue(result['movieRestored']);self.assertEqual(agent.read(self.project/'status.json')['movie'],str(second/'final.mp4'))
  with patch.object(agent,'tool',side_effect=AssertionError('must reuse, not encode')):self.assertEqual(agent.export(self.project)['movie'],str(second/'final.mp4'))
 def test_render_recovery_rejects_wrong_source_tampering_and_old_renderer(self):
  folder=self.sealed_fixture('cached',self.doc)
  compiled=agent.read(folder/'compiled.json');compiled['sourceSha256']='another-source';agent.atomic(folder/'compiled.json',compiled)
  self.assertIsNone(agent.cached_render(self.project,self.doc,self.source))
  compiled['sourceSha256']=self.source['mediaSha256'];agent.atomic(folder/'compiled.json',compiled)
  (folder/'final.mp4').write_bytes(b'tampered-test-file');self.assertIsNone(agent.cached_render(self.project,self.doc,self.source))
  seal=agent.read(folder/'seal.json');seal.update(movieSha256=agent.digest(folder/'final.mp4'),movieBytes=(folder/'final.mp4').stat().st_size,renderVersion=agent.RENDER_VERSION-1);agent.atomic(folder/'seal.json',seal)
  self.assertIsNone(agent.cached_render(self.project,self.doc,self.source))
 def test_stale_edits_and_arbitrary_time_rejected_atomically(self):
  old=agent.revision(self.doc);self.apply({'summary':'改音量','settings':{'voice':1.2}});before=(self.project/'sayframe-project.json').read_bytes()
  with self.assertRaises(agent.UserError):self.apply({'summary':'旧回复','order':['s2']},old)
  with self.assertRaises(agent.UserError):self.apply({'summary':'猜时间','start':.4})
  self.assertEqual(before,(self.project/'sayframe-project.json').read_bytes())
 def test_negation_protection_and_subtitle_does_not_delete_audio(self):
  with self.assertRaises(agent.UserError):self.apply({'summary':'删否定','removeWords':[{'id':'s1','indices':[0],'quote':'不'}]})
  self.apply({'summary':'只改字幕','subtitles':[{'id':'s1','index':1,'original':'能删','text':'能说'}]})
  source=agent.read(self.project/'source.json');state=agent.current(agent.read(self.project/'sayframe-project.json'))
  self.assertEqual(source,self.source);self.assertEqual(state['removed'],{});self.assertEqual(agent.compile_clips(source,state)[0]['words'][1]['word'],'能删')
 def test_unmigrated_word_transaction_never_becomes_a_movie(self):
  self.apply({'summary':'语气词候选','removeWords':[{'id':'s1','indices':[2],'quote':'啊'}]})
  with patch.object(agent,'tool',side_effect=AssertionError('must not encode')):
   result=agent.export(self.project)
  self.assertEqual(result['status'],'blocked');self.assertFalse(list(self.project.rglob('final.mp4')))
 def test_source_changed_refuses_all_future_edits(self):
  Path(self.source['file']).write_bytes(b'changed')
  with self.assertRaises(agent.UserError):self.apply({'summary':'改序','order':['s2']})
 def test_proportional_captions_do_not_claim_phoneme_precision(self):
  state=copy.deepcopy(self.state);state['settings']['title']='短标题';out=self.root/'render';out.mkdir()
  agent.draw_ass(out,self.source,state,agent.compile_clips(self.source,state))
  cues=agent.read(out/'captions.json');self.assertTrue(all('proportional' in c['displayTiming'] for c in cues));self.assertTrue(all('，' not in c['text'] for c in cues))
 def test_punctuation_cannot_silently_erase_spoken_caption_words(self):
  before=(self.project/'sayframe-project.json').read_bytes()
  for hidden in ('…','...','——','\u200b'):
   with self.assertRaises(agent.UserError):self.apply({'summary':'听不清就省略','subtitles':[{'id':'s1','index':1,'original':'能删','text':hidden}]})
  self.assertEqual(before,(self.project/'sayframe-project.json').read_bytes())
  # Existing bad drafts cannot bypass the guard by reusing a sealed movie.
  bad=copy.deepcopy(self.doc);bad['history'][0]['corrections']={'s1':{'1':'…'}};agent.atomic(self.project/'sayframe-project.json',bad);self.sealed_fixture('bad-caption',bad)
  self.assertIsNone(agent.cached_render(self.project,bad,self.source))
  with patch.object(agent,'tool',side_effect=AssertionError('must reject before encode')):
   with self.assertRaises(agent.UserError):agent.export(self.project)
 def test_caption_phrase_correction_changes_length_without_changing_audio(self):
  original=(self.project/'source.json').read_bytes();raw=agent.compile_clips(self.source,self.state)
  self.apply({'summary':'整词校正字数不等','subtitleSpans':[{'id':'s1','indices':[0,1],'quote':'不能删','text':'不能删除'}]})
  state=agent.current(agent.read(self.project/'sayframe-project.json'));clips=agent.compile_clips(self.source,state)
  self.assertEqual((self.project/'source.json').read_bytes(),original);self.assertEqual(state['removed'],{})
  self.assertEqual([(c['text'],c['start'],c['end']) for c in raw],[(c['text'],c['start'],c['end']) for c in clips])
  self.assertEqual(''.join(w['captionWord'] for w in clips[0]['words']),'不能删除啊');agent.validate_caption_corrections(self.source,state)
  with self.assertRaises(agent.UserError):self.apply({'summary':'不能拆坏整词','subtitles':[{'id':'s1','index':1,'original':'能删','text':'能说'}]})
  agent.undo_redo(self.project);self.assertEqual(agent.caption_map(self.source['segments'][0],agent.current(agent.read(self.project/'sayframe-project.json'))),{0:'不',1:'能删',2:'啊'})
 def test_caption_phrase_rejects_wrong_quotes_gaps_and_punctuation_atomically(self):
  before=(self.project/'sayframe-project.json').read_bytes()
  for op in [{'id':'s1','indices':[0,2],'quote':'不啊','text':'字幕'},{'id':'s1','indices':[0,1],'quote':'猜的字','text':'字幕'},{'id':'s1','indices':[0,1],'quote':'不能删','text':'…'},{'id':'s1','indices':[0,999999999999],'quote':'不','text':'字幕'}]:
   with self.assertRaises(agent.UserError):self.apply({'summary':'无效校正','subtitleSpans':[op]})
  self.assertEqual(before,(self.project/'sayframe-project.json').read_bytes())
 def test_missing_runtime_is_not_reported_ready(self):
  output=io.StringIO()
  with patch.object(sys,'argv',['sayframe','doctor']),patch.object(agent,'runtime',return_value={}),patch('importlib.util.find_spec',return_value=None),contextlib.redirect_stdout(output):
   with self.assertRaises(SystemExit) as stopped:agent.main()
  self.assertEqual(stopped.exception.code,2);self.assertFalse(json.loads(output.getvalue())['ready'])
 def test_literal_asr_overlap_is_owned_by_source_time_not_text_dedup(self):
  events=[{'text':text,'time':at,'probability':.99} for text,at in [('我',.5),('我',1.2),('好',19.9),('的',20.5)]]
  recognizer=types.SimpleNamespace(trace=lambda audio,offset:events)
  with patch.dict(sys.modules,{'precise_speech':types.SimpleNamespace(CharacterAcoustics=lambda folder:recognizer)}),patch.object(agent,'model_dir',return_value=self.root),patch.object(agent,'tool',return_value='ffmpeg'),patch.object(agent,'run',return_value=b'\0'*16000*4):
   rows=agent.literal_transcription('fixture',22,lambda at:None)
  self.assertEqual(''.join(r['text'] for r in rows),'我我好的')
  self.assertTrue(all(w['timingEstimated'] for r in rows for w in r['words']))
 def native_fixture(self):
  audio=self.root/'audio.m4a';audio.write_bytes(b'audio-fixture');self.manifest=self.root/'prepared.json';self.receipt=self.root/'receipt.json'
  agent.atomic(self.manifest,{'video':self.source['file'],'sourceSha256':self.source['mediaSha256'],'parts':[{'id':'a1','file':str(audio),'sha256':agent.digest(audio),'sourceStart':30,'sourceEnd':34}]})
  agent.atomic(self.receipt,{'tool':'AudioTranscribe','sourceSha256':self.source['mediaSha256'],'parts':[{'id':'a1','audioSha256':agent.digest(audio),'rawResult':'[0:00.100, 0:03.300, 0] 不能删啊正常内容'}]})
 def test_native_receipt_offsets_and_original_text_are_preserved(self):
  self.native_fixture();manifest,result=native_audio.validate(agent,self.manifest,self.receipt)
  self.assertEqual(result['segments'][0]['start'],30.1);self.assertEqual(result['segments'][0]['text'],'不能删啊正常内容');self.assertFalse(result['coverageCertified'])
 def test_native_receipt_refuses_missing_parts_and_invented_out_of_range_times(self):
  self.native_fixture();receipt=agent.read(self.receipt);receipt['parts'][0]['rawResult']='[0:00.100, 0:05.000, 0] 正常内容';agent.atomic(self.receipt,receipt)
  with self.assertRaises(agent.UserError):native_audio.validate(agent,self.manifest,self.receipt)
  receipt['parts']=[];agent.atomic(self.receipt,receipt)
  with self.assertRaises(agent.UserError):native_audio.validate(agent,self.manifest,self.receipt)
 def test_real_output_mix_loads_its_bundled_public_policy(self):
  from music_mix import output_audio_filter
  args=output_audio_filter({'voiceGain':1,'musicId':None,'noiseReduction':'off','peakProtection':True},duration=15)
  self.assertIn('-af',args);self.assertTrue(any('alimiter' in str(item) for item in args))
 def test_phone_rotation_uses_display_dimensions(self):
  raw=json.dumps({'format':{'duration':'10'},'streams':[{'codec_type':'video','width':1920,'height':1080,'side_data_list':[{'rotation':-90}]},{'codec_type':'audio'}]}).encode()
  with patch.object(agent,'tool',return_value='ffprobe'),patch.object(agent,'run',return_value=raw):info=agent.probe('fixture')
  self.assertEqual((info['width'],info['height']),(1080,1920));self.assertEqual(info['codedWidth'],1920)
 def test_title_uses_supplied_punctuation_for_two_clear_lines(self):
  state=copy.deepcopy(self.state);state['settings']['title']='身体没准备好，做试管也未必成功';out=self.root/'title';out.mkdir()
  agent.draw_ass(out,self.source,state,agent.compile_clips(self.source,state))
  self.assertIn(r'身体没准备好\N做试管也未必成功',(out/'captions.ass').read_text('utf8'))
 def test_real_ffmpeg_final_keeps_audio_without_music(self):
  # Synthetic integration fixture: test muxing, NOT speech accuracy. Real
  # calibration acceptance is separately checked in the WorkBuddy project.
  media=Path(self.source['file']);agent.run([agent.tool('ffmpeg'),'-y','-v','error','-f','lavfi','-i','color=c=blue:s=96x160:r=30:d=4','-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-c:a','aac','-shortest',media])
  self.source.update(mediaSha256=agent.digest(media),width=96,height=160);agent.atomic(self.project/'source.json',self.source);self.doc['sourceSignature']=agent.digest(self.project/'source.json');agent.atomic(self.project/'sayframe-project.json',self.doc)
  worker=types.SimpleNamespace(calibrate=lambda request:{'clips':request['clips'],'blocking':[]})
  with patch.dict(sys.modules,{'clip_calibration_worker':worker}):result=agent.export(self.project)
  self.assertEqual(result['status'],'done');self.assertGreater(agent.probe(result['movie'])['duration'],3.9)
 def test_new_workflow_blocks_export_until_direction_and_appearance_are_confirmed(self):
  doc=copy.deepcopy(self.doc);doc['history'][0]['workflow']={'directionConfirmed':False};doc['history'][0]['settings'].update(captionsEnabled=None,titleEnabled=None);agent.atomic(self.project/'sayframe-project.json',doc)
  with patch.object(agent,'tool',side_effect=AssertionError('must not encode before confirmation')):
   self.assertEqual(agent.export(self.project)['stage'],'confirmation')
   doc['history'][0]['workflow']['directionConfirmed']=True;agent.atomic(self.project/'sayframe-project.json',doc);self.assertEqual(agent.export(self.project)['stage'],'appearance-choice')
  self.assertFalse(list(self.project.rglob('final.mp4')))
 def test_direction_requires_explicit_confirmation_and_both_independent_choices(self):
  import planning
  result=planning.propose(agent,self.project,self.proposal_fixture(),agent.revision(self.doc));before=(self.project/'sayframe-project.json').read_bytes()
  for options in (None,{'confirmed':False,'captionsEnabled':True,'titleEnabled':False},{'confirmed':True,'captionsEnabled':True},{'confirmed':True,'captionsEnabled':'off','titleEnabled':False}):
   with self.assertRaises(agent.UserError):planning.choose(agent,self.project,result['plan'],'first',result['revision'],options)
  self.assertEqual(before,(self.project/'sayframe-project.json').read_bytes())
  planning.choose(agent,self.project,result['plan'],'first',result['revision'],{'confirmed':True,'captionsEnabled':False,'titleEnabled':False});state=agent.current(agent.read(self.project/'sayframe-project.json'));self.assertTrue(state['workflow']['directionConfirmed']);self.assertFalse(state['settings']['captionsEnabled']);self.assertFalse(state['settings']['titleEnabled'])
 def test_four_caption_title_combinations_preserve_the_same_timeline(self):
  for captions in (False,True):
   for title in (False,True):
    with self.subTest(captions=captions,title=title):
     state=copy.deepcopy(self.state);state['settings'].update(captionsEnabled=captions,titleEnabled=title);folder=self.root/f'visual-{captions}-{title}';folder.mkdir();duration=agent.draw_ass(folder,self.source,state,agent.compile_clips(self.source,state));ass=(folder/'captions.ass').read_text('utf-8')
     self.assertEqual(duration,4);self.assertEqual(bool(agent.read(folder/'captions.json')),captions);self.assertEqual(bool(__import__('re').search(r'Dialogue: .*?,Title,',ass)),title)
 def test_appearance_flags_are_boolean_and_reversible(self):
  for key in ('captionsEnabled','titleEnabled'):
   with self.assertRaises(agent.UserError):self.apply({'summary':'无效选项','settings':{key:'false'}})
  self.apply({'summary':'不加字幕和标题','settings':{'captionsEnabled':False,'titleEnabled':False}});agent.undo_redo(self.project);self.assertNotIn('captionsEnabled',agent.current(agent.read(self.project/'sayframe-project.json'))['settings']);agent.undo_redo(self.project,True);self.assertFalse(agent.current(agent.read(self.project/'sayframe-project.json'))['settings']['titleEnabled'])
 def test_four_actual_movies_have_distinct_overlays_and_identical_audio(self):
  import hashlib
  media=Path(self.source['file']);agent.run([agent.tool('ffmpeg'),'-y','-v','error','-f','lavfi','-i','color=c=blue:s=180x320:r=30:d=4','-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-c:a','aac','-shortest',media])
  self.source.update(mediaSha256=agent.digest(media),width=180,height=320);agent.atomic(self.project/'source.json',self.source);self.doc['sourceSignature']=agent.digest(self.project/'source.json');agent.atomic(self.project/'sayframe-project.json',self.doc)
  worker=types.SimpleNamespace(calibrate=lambda request:{'clips':request['clips'],'blocking':[]});pcm_hashes=set();frames=set();orders=[]
  for captions in (False,True):
   for title in (False,True):
    self.apply({'summary':'选择文字呈现','settings':{'captionsEnabled':captions,'titleEnabled':title}})
    with patch.dict(sys.modules,{'clip_calibration_worker':worker}):result=agent.export(self.project)
    self.assertEqual(result['status'],'done');self.assertAlmostEqual(agent.probe(result['movie'])['duration'],4,delta=.04)
    movie=Path(result['movie']);compiled=agent.read(movie.parent/'compiled.json');orders.append([(x['start'],x['end']) for x in compiled['clips']])
    pcm=agent.run([agent.tool('ffmpeg'),'-v','error','-i',movie,'-vn','-ac','1','-ar','48000','-f','s16le','pipe:1']);pcm_hashes.add(hashlib.sha256(pcm).hexdigest())
    pixels=agent.run([agent.tool('ffmpeg'),'-v','error','-ss','1','-i',movie,'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1']);frames.add(hashlib.sha256(pixels).hexdigest())
  self.assertEqual(len(pcm_hashes),1);self.assertEqual(len(frames),4);self.assertTrue(all(order==orders[0] for order in orders))
 def cover_fixture(self):
  import covers
  from PIL import Image
  folder=self.project/'covers'/'test-request';folder.mkdir(parents=True);frame=folder/'frame.png';Image.new('RGB',(180,320),'#777788').save(frame)
  reference=agent.SKILL/'assets/covers/style-reference.png'
  request={'version':1,'revision':agent.revision(self.doc),'storyRevision':covers.story_revision(agent,self.doc),'sourceSha256':self.source['mediaSha256'],'title':'保留条件','subtitle':'再讲清楚','textConfirmed':True,'frame':str(frame),'frameSha256':agent.digest(frame),'reference':str(reference),'referenceSha256':agent.digest(reference)}
  agent.atomic(folder/'request.json',request);return folder/'request.json'
 def test_cover_requires_confirmation_and_does_not_choose_for_user(self):
  import covers
  with self.assertRaises(agent.UserError):covers.prepare(agent,self.project,'测试','',False)
  request=self.cover_fixture();result=covers.generate(agent,self.project,request)
  self.assertEqual(len(result['candidates']),3);doc=agent.read(self.project/'sayframe-project.json');self.assertIsNone(agent.current(doc)['cover']['selected'])
  with self.assertRaises(agent.UserError):covers.selected(agent,self.project,agent.current(doc),doc)
  covers.choose(agent,self.project,'ivory',result['revision']);agent.undo_redo(self.project);self.assertIsNone(agent.current(agent.read(self.project/'sayframe-project.json'))['cover']['selected'])
 def test_cover_frame_follows_retained_order_speed_and_leading_frame(self):
  import covers
  folder=self.project/'exports'/'compiled';folder.mkdir(parents=True)
  agent.atomic(folder/'compiled.json',{'sourceSha256':self.source['mediaSha256'],'revision':'right','settings':{'speed':2},'clips':[{'start':30,'end':34},{'start':10,'end':16}]})
  status={'export':str(folder),'seal':{'revision':'right','cover':{'silentLeadSeconds':1/30}}}
  self.assertAlmostEqual(covers.retained_frame_time(agent,status,self.source,2.5+1/30),11)
  status['seal']['revision']='other'
  with self.assertRaises(agent.UserError):covers.retained_frame_time(agent,status,self.source,2.5)
 def test_cover_rejects_stale_text_modified_image_and_changed_story(self):
  import covers
  request=self.cover_fixture();old=agent.read(request);old['revision']='stale';agent.atomic(request,old)
  with self.assertRaises(agent.UserError):covers.generate(agent,self.project,request)
  old['revision']=agent.revision(self.doc);agent.atomic(request,old);result=covers.generate(agent,self.project,request);covers.choose(agent,self.project,'teal',result['revision'])
  self.apply({'summary':'改音量','settings':{'voice':1.2}});doc=agent.read(self.project/'sayframe-project.json')
  with self.assertRaises(agent.UserError):covers.selected(agent,self.project,agent.current(doc),doc)
  agent.undo_redo(self.project);Path(result['candidates'][0]['file']).write_bytes(b'changed');doc=agent.read(self.project/'sayframe-project.json')
  with self.assertRaises(agent.UserError):covers.selected(agent,self.project,agent.current(doc),doc)
 def test_cover_is_actual_first_frame_and_keeps_audio(self):
  import covers
  import numpy as np
  from PIL import Image,ImageOps
  media=Path(self.source['file']);agent.run([agent.tool('ffmpeg'),'-y','-v','error','-f','lavfi','-i','color=c=blue:s=96x160:r=30:d=4','-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-c:a','aac','-shortest',media])
  self.source.update(mediaSha256=agent.digest(media),width=96,height=160);agent.atomic(self.project/'source.json',self.source);self.doc['sourceSignature']=agent.digest(self.project/'source.json');agent.atomic(self.project/'sayframe-project.json',self.doc)
  worker=types.SimpleNamespace(calibrate=lambda request:{'clips':request['clips'],'blocking':[]})
  with patch.dict(sys.modules,{'clip_calibration_worker':worker}):
   agent.export(self.project);prepared=covers.prepare(agent,self.project,'保留条件','再讲清楚',True);options=covers.generate(agent,self.project,prepared['request']);covers.choose(agent,self.project,'ivory',options['revision']);result=agent.export(self.project)
  self.assertEqual(result['seal']['cover']['id'],'ivory');self.assertAlmostEqual(result['seal']['duration'],4+1/30,delta=.035)
  pixels=agent.run([agent.tool('ffmpeg'),'-v','error','-i',result['movie'],'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'])
  actual=np.frombuffer(pixels,dtype=np.uint8).reshape(160,96,3)
  with Image.open(options['candidates'][1]['file']) as image:expected=np.asarray(ImageOps.fit(image.convert('RGB'),(96,160)))
  self.assertLess(float(np.abs(actual.astype(float)-expected.astype(float)).mean()),12)
  pcm=agent.run([agent.tool('ffmpeg'),'-v','error','-i',result['movie'],'-vn','-ac','1','-ar','48000','-f','s16le','pipe:1']);samples=np.frombuffer(pcm,dtype=np.int16)
  self.assertGreater(float(np.abs(samples[2000:4000].astype(float)).mean()),100);self.assertLess(float(np.abs(samples[:800].astype(float)).max()),100)
  # Exercise the other real filter graph too: ducked music plus the cover's
  # single silent leading frame must still map both video and audible audio.
  agent.undo_redo(self.project);agent.undo_redo(self.project)
  self.apply({'summary':'加入本次配乐','settings':{'musicFile':str(media),'musicVolume':.05}})
  with patch.dict(sys.modules,{'clip_calibration_worker':worker}):
   agent.export(self.project);prepared=covers.prepare(agent,self.project,'保留条件','再讲清楚',True);options=covers.generate(agent,self.project,prepared['request']);covers.choose(agent,self.project,'teal',options['revision']);mixed=agent.export(self.project)
  self.assertEqual(mixed['seal']['cover']['id'],'teal');self.assertGreater(agent.probe(mixed['movie'])['duration'],4)

 def proposal_fixture(self):
  directions=[]
  for did,order in [('first',['s2','s1']),('second',['s1','s2'])]:
   directions.append({'id':did,'title':'保留完整条件'+did,'audience':'测试受众','goal':'测试来源绑定','methods':['counter-opening','evidence-four'],'why':'回归夹具，仅验证顺序来源，不证明内容质量','order':order,'beats':[{'role':'opening','ids':[order[0]],'reason':'完整开场'},{'role':'support','ids':[order[1]],'reason':'完整后段'}],'evidence':[{'id':sid,'quote':agent.source_rows(self.source)[sid]['text']} for sid in order],'gaps':['夹具不是实际人物材料'],'review':{'opening':'完整保留','support':'测试绑定而非因果','ability':'无本人能力依据','ending':'无转化事实'}})
  file=self.root/'proposal.json';agent.atomic(file,{'catalogVersion':1,'sourceSha256':self.source['mediaSha256'],'directions':directions});return file
 def test_plan_choose_undo_and_later_edits_cannot_be_overwritten(self):
  import planning
  file=self.proposal_fixture();result=planning.propose(agent,self.project,file,agent.revision(self.doc))
  self.assertEqual(agent.current(agent.read(self.project/'sayframe-project.json'))['order'],['s1','s2'])
  planning.choose(agent,self.project,result['plan'],'first',result['revision'],{'confirmed':True,'captionsEnabled':True,'titleEnabled':True})
  doc=agent.read(self.project/'sayframe-project.json');self.assertEqual(agent.current(doc)['order'],['s2','s1'])
  self.apply({'summary':'用户修改音量','settings':{'voice':1.8}})
  before=(self.project/'sayframe-project.json').read_bytes()
  with self.assertRaises(agent.UserError):planning.choose(agent,self.project,result['plan'],'second',agent.revision(agent.read(self.project/'sayframe-project.json')),{'confirmed':True,'captionsEnabled':True,'titleEnabled':True})
  self.assertEqual(before,(self.project/'sayframe-project.json').read_bytes())
  agent.undo_redo(self.project);agent.undo_redo(self.project);self.assertEqual(agent.current(agent.read(self.project/'sayframe-project.json'))['order'],['s1','s2'])
 def test_plan_rejects_fabricated_quotes_duplicate_audio_and_wrong_source(self):
  import planning
  file=self.proposal_fixture();data=agent.read(file)
  for mutate in [lambda d:d['directions'][0]['evidence'][1].update(quote='能删啊'),lambda d:d['directions'][0]['order'].append('s1'),lambda d:d.update(sourceSha256='other')]:
   wrong=copy.deepcopy(data);mutate(wrong);agent.atomic(file,wrong)
   with self.assertRaises(agent.UserError):planning.propose(agent,self.project,file,agent.revision(self.doc))
  self.assertFalse((self.project/'planning.json').exists())
 def test_plan_tamper_and_stale_generation_rejected(self):
  import planning
  file=self.proposal_fixture();result=planning.propose(agent,self.project,file,agent.revision(self.doc))
  plan_file=self.project/'plans'/(result['plan']+'.json');plan=agent.read(plan_file);plan['directions'][0]['order'].reverse();agent.atomic(plan_file,plan)
  with self.assertRaises(agent.UserError):planning.active(agent,self.project,self.doc)
  self.apply({'summary':'新稿','settings':{'voice':1.2}})
  with self.assertRaises(agent.UserError):planning.propose(agent,self.project,file,result['revision'])
 def test_fork_keeps_source_and_old_project_independent(self):
  import planning
  before=(self.project/'sayframe-project.json').read_bytes();result=planning.fork(agent,self.project,self.root/'independent')
  self.assertEqual(agent.read(Path(result['project'])/'source.json')['file'],self.source['file']);self.assertEqual(before,(self.project/'sayframe-project.json').read_bytes())
  with self.assertRaises(agent.UserError):planning.fork(agent,self.project,result['project'])
 def test_public_method_and_review_modules_load_with_their_registry(self):
  import business_framework,danjie_methodology
  catalog=danjie_methodology.catalog();self.assertEqual(len(catalog['methods']),12)
  self.assertTrue(business_framework.RULES and business_framework.REVIEW)
  self.assertTrue(all(len(m['source']['sha256'])==64 for m in catalog['methods']))

if __name__=='__main__':unittest.main()
