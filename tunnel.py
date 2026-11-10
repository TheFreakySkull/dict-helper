"""Run after putting NGROK_AUTHTOKEN into the environment settings."""
import os, time
from pathlib import Path
from pyngrok import ngrok, conf
root=Path(__file__).parent
if not os.environ.get('NGROK_AUTHTOKEN') and not (root/'.ngrok.yml').exists():
    raise SystemExit('Добавьте NGROK_AUTHTOKEN в секреты окружения и повторите запуск.')
binary = 'ngrok.exe' if os.name == 'nt' else 'ngrok'
config=conf.PyngrokConfig(ngrok_path=str(root/'bin'/binary),config_path=str(root/'.ngrok.yml'),auth_token=os.environ.get('NGROK_AUTHTOKEN'))
tunnel=ngrok.connect(8000,proto='http',url=os.environ.get('NGROK_URL','https://crawfish-earflap-wanted.ngrok-free.dev'),inspect=False,pyngrok_config=config)
print('Откройте на телефоне: '+tunnel.public_url+'/#'+(root/'.access-token').read_text(),flush=True)
try:
    while True:time.sleep(30)
finally:
    ngrok.kill(pyngrok_config=config)
