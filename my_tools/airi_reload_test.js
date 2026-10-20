/**
 * airi + LiveTalking 连续刷新回归测试：
 * 开启 LiveTalking 后连续刷新页面多次，验证每次都能正常启动且视频流建立，
 * 不再出现「Maximum session limit reached」。
 *
 * 用法（项目根执行）:
 *   node my_tools/airi_reload_test.js [rounds]
 */
const { chromium } = require('E:/work/airi/node_modules/playwright')

const APP = 'http://localhost:5173/'
const CHROME = 'C:/Users/pc/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe'
const ROUNDS = Number(process.argv[2] || 3)

async function snapshot(page) {
  return page.evaluate(() => {
    const v = document.querySelector('video')
    const text = document.body.innerText || ''
    return {
      video: !!v,
      videoWidth: v ? v.videoWidth : 0,
      hasStream: !!(v && v.srcObject),
      stuckLoading: text.includes('模型加载中') || text.includes('Loading model'),
      limitError: text.includes('Maximum session limit'),
      sessionId: sessionStorage.getItem('settings/livetalking/session-id'),
    }
  })
}

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME })
  const context = await browser.newContext()
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(`[pageerror] ${e.message}`))
  page.on('console', m => {
    if (m.type() === 'error')
      errors.push(`[console] ${m.text().slice(0, 200)}`)
  })
  page.on('response', async (res) => {
    if (res.url().includes(':8010/offer') && res.status() !== 200)
      errors.push(`[http] /offer ${res.status()}`)
  })

  await page.goto(APP, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('settings/livetalking/enabled', 'true')
    localStorage.setItem('settings/livetalking/server-url', 'http://127.0.0.1:8010')
  })

  let failures = 0
  for (let i = 1; i <= ROUNDS; i++) {
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(12000)
    const s = await snapshot(page)
    const ok = s.video && s.videoWidth > 0 && !s.stuckLoading && !s.limitError
    if (!ok)
      failures++
    console.log(`round ${i}: ${ok ? 'ok' : 'FAIL'} ${JSON.stringify(s)}`)
    await page.screenshot({ path: `E:/work/LiveTalking/my_tools/image/_airi_reload_${i}.png` })
  }

  if (errors.length) {
    console.log('\n浏览器报错:')
    for (const e of errors.slice(0, 10))
      console.log('  ' + e)
  }
  console.log(`\n结果: ${ROUNDS - failures}/${ROUNDS} 通过`)
  await browser.close()
  process.exit(failures === 0 ? 0 : 1)
}

main()
