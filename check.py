import io, time, wave
from pathlib import Path
import requests
base='http://127.0.0.1:8000'
s=requests.Session();s.headers['x-access-token']=Path('.access-token').read_text()
for _ in range(30):
    state=s.get(base+'/api/status').json()
    if state['ready'] or state['error']:break
    time.sleep(1)
print('MODELS',state)
assert state['ready'],state
assert requests.get(base+'/api/status').status_code==401
assert s.post(base+'/api/transcribe',files={'file':('bad.wav',b'not audio','audio/wav')}).status_code==422
assert s.post(base+'/api/speak',json={'syllables':['<script>']}).status_code==422
start=time.time()
r=s.post(base+'/api/analyze',json={'text':'Маша не разговаривай. Наступила золотая осень.', 'filter':True},timeout=120)
print('ANALYZE',r.status_code,r.text,'seconds',round(time.time()-start,1));assert r.status_code==200,r.text
assert [i['word'] for i in r.json()['items']]==['наступила','золотая','осень'],r.text
for text, expected in [
 ('ребята не шумите сегодня выпал первый снег', ['сегодня','выпал','первый','снег']),
 ('ребята не шумите', []),
 ('маша пошла в школу', ['маша','пошла','в','школу']),
]:
 r=s.post(base+'/api/analyze',json={'text':text,'filter':True},timeout=120)
 print('FILTER',text,r.status_code,r.text,flush=True)
 assert r.status_code==200,r.text
 assert [i['word'] for i in r.json()['items']]==expected,r.text
r=s.post(base+'/api/speak',json={'syllables':['мо','ло','ко']},timeout=60)
print('TTS',r.status_code,len(r.content));assert r.status_code==200,r.text
with wave.open(io.BytesIO(r.content)) as w: assert w.getnframes()>0
r=s.post(base+'/api/speak',json={'syllables':['молоко']},timeout=60)
assert r.status_code==200
Path('sample.wav').write_bytes(r.content)
r=s.post(base+'/api/transcribe',files={'file':('sample.wav',r.content,'audio/wav')},timeout=60)
print('ASR',r.status_code,r.text);assert r.status_code==200
assert r.json()['text'], 'Распознавание вернуло пустой текст'
assert 'молоко' in r.json()['text'], r.text
print('ALL CHECKS PASSED')
