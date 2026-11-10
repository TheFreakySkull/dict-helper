import io, json, os, re, secrets, subprocess, tempfile, threading, wave
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
TOKEN = os.environ.get('APP_TOKEN') or ((ROOT / '.access-token').read_text().strip() if (ROOT / '.access-token').exists() else secrets.token_urlsafe(24))
(ROOT / '.access-token').write_text(TOKEN)
os.chmod(ROOT / '.access-token', 0o600)
lock = threading.Lock()
models = {}
status = {'ready': False, 'error': None}

def load():
    try:
        from vosk import Model, SetLogLevel
        from llama_cpp import Llama
        from piper import PiperVoice
        SetLogLevel(-1)
        models['asr'] = Model(str(ROOT / 'models/vosk-model-small-ru-0.22'))
        models['llm'] = Llama(model_path=str(ROOT / 'models/qwen3-4b.gguf'), n_ctx=4096, n_threads=2, verbose=False, chat_format="chatml")
        models['tts'] = PiperVoice.load(str(ROOT / 'models/voice.onnx'))
        status['ready'] = True
    except Exception as e:
        status['error'] = str(e)

@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=load, daemon=True).start()
    yield

app = FastAPI(lifespan=lifespan)
@app.middleware('http')
async def security(request: Request, call_next):
    if request.url.path.startswith('/api/') and not secrets.compare_digest(request.headers.get('x-access-token', ''), TOKEN):
        return Response('Требуется код доступа', status_code=401)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Permissions-Policy'] = 'microphone=(self)'
    return response

def ready():
    if not status['ready']:
        raise HTTPException(503, status['error'] or 'Модели ещё загружаются')

@app.get('/api/status')
def health():
    return status

@app.post('/api/transcribe')
async def transcribe(file: UploadFile):
    ready()
    data = await file.read(12 * 1024 * 1024 + 1)
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, 'Запись слишком большая: максимум 12 МБ')
    # Each upload is a complete recording; do not concatenate MediaRecorder fragments.
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(recognize, data)

def recognize(data):
    from vosk import KaldiRecognizer
    with lock, tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'input'
        source.write_bytes(data)
        try:
            pcm = subprocess.run(['ffmpeg', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,wav,mp3,ogg,flac,aac', '-i', str(source), '-t', '60', '-ar', '16000', '-ac', '1', '-f', 's16le', '-'], capture_output=True, timeout=30, check=True).stdout
        except (subprocess.SubprocessError, OSError):
            raise HTTPException(422, 'Не удалось прочитать аудио. Запишите фразу заново.')
        rec = KaldiRecognizer(models['asr'], 16000)
        texts = []
        for i in range(0, len(pcm), 8000):
            if rec.AcceptWaveform(pcm[i:i+8000]):
                texts.append(json.loads(rec.Result()).get('text', ''))
        texts.append(json.loads(rec.FinalResult()).get('text', ''))
        return {'text': ' '.join(filter(None, texts))}

class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=1600)
    filter: bool = True


def words(text):
    return re.findall(r'[а-яё]+(?:-[а-яё]+)*', text.lower())

def remove_obvious_remarks(text):
    # ponytail: common classroom commands; the LLM handles other remarks, and the user can disable filtering.
    addresses = 'ребята|дети|класс|маша|мария|петя|пётр|ваня|вася|коля|саша|дима|лена|оля|катя|серёжа|аня'
    commands = [
        r'не\s+(?:шумите|шуми|разговаривай|разговаривайте|отвлекайтесь|мешай|торопитесь)',
        r'(?:сядь|сядьте)\s+(?:ровно|на\s+место)', r'поднимите\s+руки',
        r'откройте\s+тетради', r'запишите\s+дату', r'пишем\s+с\s+красной\s+строки',
        r'(?:поставьте|положите)\s+ручки', r'посмотрите\s+на\s+доску',
        r'слушайте\s+внимательно', r'прекратите\s+разговоры',
    ]
    pattern = r'\b(?:(?:' + addresses + r')\s*[,!:]?\s+)?(?:' + '|'.join(commands) + r')\b[\s,.!:;]*'
    return re.sub(pattern, ' ', text, flags=re.IGNORECASE).strip()

def validate_items(items, source):
    allowed = words(source)
    result = []
    cursor = 0
    for item in items:
        word = str(item.get('word', '')).lower()
        syllables = item.get('syllables', [])
        if word not in allowed[cursor:] or not isinstance(syllables, list) or not syllables:
            raise ValueError('Модель вернула слова, которых нет в записи')
        cursor = allowed.index(word, cursor) + 1
        if any(not isinstance(s, str) or not re.fullmatch('[а-яё-]+', s) for s in syllables) or ''.join(syllables) != word:
            raise ValueError('Модель неточно разделила слово на слоги')
        if any(c in 'аеёиоуыэюя' for c in word) and any(sum(c in 'аеёиоуыэюя' for c in s) != 1 for s in syllables):
            raise ValueError('В каждом слоге должна быть одна гласная')
        result.append({'word': word, 'syllables': syllables})
    return result

def syllable_options(word):
    vowels = [i for i, c in enumerate(word) if c in 'аеёиоуыэюя']
    cuts = []
    # ponytail: school syllable boundaries, not a morphological dictionary; compounds may need manual review.
    for left, right in zip(vowels, vowels[1:]):
        cluster = word[left + 1:right]
        keep = 0
        if len(cluster) > 1:
            if 'ъ' in cluster or 'ь' in cluster:
                keep = max(cluster.rfind('ъ'), cluster.rfind('ь')) + 1
            elif cluster[0] in 'йлмнр' or cluster[0] == cluster[1]:
                keep = 1
        cuts.append(left + 1 + keep)
    return ['·'.join(word[a:b] for a, b in zip((0, *cuts), (*cuts, len(word))))]


def complete(messages, schema):
    output = models['llm'].create_chat_completion(messages=messages, temperature=0, max_tokens=1500,
        response_format={'type': 'json_object', 'schema': schema})
    if output['choices'][0]['finish_reason'] == 'length':
        raise ValueError('Ответ слишком длинный. Запишите более короткую фразу.')
    return json.loads(output['choices'][0]['message']['content'])


@app.post('/api/analyze')
def analyze(body: TextInput):
    ready()
    if not words(body.text):
        raise HTTPException(422, 'Введите или запишите текст на русском языке.')
    cleaned = remove_obvious_remarks(body.text) if body.filter else body.text
    source = words(cleaned)
    if not source:
        return {'items': []}
    spellings = [syllable_options(word)[0] for word in source]
    array = ({'type': 'array', 'items': {'type': 'string', 'enum': list(dict.fromkeys(spellings))}}
        if body.filter else {'type': 'array', 'prefixItems': [{'const': word} for word in spellings],
                             'minItems': len(source), 'maxItems': len(source)})
    schema = {'type': 'object', 'properties': {'items': array}, 'required': ['items'], 'additionalProperties': False}
    instruction = ('Remove classroom management remarks, commands and direct addresses to students. Remove the ENTIRE name plus command phrase, including negations. Keep names in narrated stories. Keep every dictated word in its original order, including prepositions. If the entire speech is classroom management, return an empty items list. '
        if body.filter else 'Keep every word in its original order. ')
    messages = [{'role': 'system', 'content': instruction + 'Output Russian dictated words with syllables separated by ·. Return JSON items: an array of strings. Never invent or replace words. Speech can have no punctuation.'}]
    if body.filter:
        messages += [
            {'role': 'user', 'content': 'Петя сядь ровно. В лесу было тихо.'},
            {'role': 'assistant', 'content': '{"items":["в","ле·су","бы·ло","ти·хо"]}'},
            {'role': 'user', 'content': 'Солнце светило ярко. Не шумите дети.'},
            {'role': 'assistant', 'content': '{"items":["сол·нце","све·ти·ло","яр·ко"]}'},
            {'role': 'user', 'content': 'Откройте тетради и запишите дату.'},
            {'role': 'assistant', 'content': '{"items":[]}'}]
    messages.append({'role': 'user', 'content': cleaned})
    with lock:
        try:
            result = complete(messages, schema)
            items = validate_items([{'word': ''.join(parts.split('·')), 'syllables': parts.split('·')}
                                    for parts in result['items']], body.text)
            if not body.filter and [item['word'] for item in items] != source:
                raise ValueError('Модель пропустила слова')
            return {'items': items}
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f'Не удалось надёжно разобрать текст. Сократите фразу или исправьте её. {e}')

class SpeechInput(BaseModel):
    syllables: list[str] = Field(min_length=1, max_length=20)
    letters: bool = False

@app.post('/api/speak')
def speak(body: SpeechInput):
    ready()
    if any(not re.fullmatch('[а-яё-]{1,35}', x) for x in body.syllables):
        raise HTTPException(422, 'Допустимы только русские слоги')
    from piper import SynthesisConfig
    import numpy as np
    with lock:
        audio = []
        parts = list(''.join(body.syllables)) if body.letters else body.syllables
        names = dict(zip('бвгджзйклмнпрстфхцчшщъыь', ['бэ','вэ','гэ','дэ','жэ','зэ','и краткое','ка','эль','эм','эн','пэ','эр','эс','тэ','эф','ха','цэ','че','ша','ща','твёрдый знак','ы','мягкий знак']))
        rate = 22050
        for part in parts:
            for chunk in models['tts'].synthesize(names.get(part, part) if body.letters else part, SynthesisConfig(length_scale=1.35)):
                rate = chunk.sample_rate
                audio.append(chunk.audio_int16_bytes)
            audio.append(np.zeros(int(rate * .32), dtype=np.int16).tobytes())
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(b''.join(audio))
        return Response(buffer.getvalue(), media_type='audio/wav')

@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
