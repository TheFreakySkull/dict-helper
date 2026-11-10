from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(args=['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--use-file-for-fake-audio-capture='+str(Path('sample.wav').resolve())])
 page=b.new_page(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,permissions=['microphone'])
 page.goto('http://127.0.0.1:8000/#'+Path('.access-token').read_text())
 page.wait_for_function("document.getElementById('health').textContent.includes('готовы')")
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 page.screenshot(path='mobile.png',full_page=True)
 page.locator('#text').fill('Молоко')
 page.locator('#filter').uncheck()
 page.locator('#analyze').click()
 page.wait_for_function("!document.getElementById('analyze').disabled",timeout=120000)
 assert page.locator('#result .word strong').all_text_contents()==['молоко']
 assert page.locator('#result small').inner_text()=='мо · ло · ко'
 print(page.locator('#message').inner_text())
 print(page.locator('#result').inner_text())
 page.screenshot(path='mobile-result.png',full_page=True)
 page.locator('#result .word button').click()
 page.wait_for_function('audio && audioContext.state === \"running\"',timeout=60000)
 page.locator('#stop').click()
 page.locator('#record').click()
 page.wait_for_function("document.getElementById('record').classList.contains('recording')")
 page.wait_for_timeout(4000)
 with page.expect_response('**/api/transcribe',timeout=60000) as transcription:
  page.locator('#record').click()
 assert transcription.value.status==200
 page.wait_for_function("!document.getElementById('analyze').disabled",timeout=120000)
 assert page.locator('#text').input_value(), 'Микрофон не дал распознанной речи'
 assert page.locator('#message').inner_text().startswith('Готово.'),page.locator('#message').inner_text()
 print('MICROPHONE',page.locator('#text').input_value())
 page.set_viewport_size({'width':1280,'height':900})
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 page.screenshot(path='desktop.png',full_page=True)
 print('BROWSER CHECKS PASSED')
 b.close()
