// 模拟用户浏览器状态：livetalking 已开启，复现"loading 失败"
const { chromium } = require('E:/work/airi/node_modules/playwright')

const url = 'http://localhost:5173/'
const seed = {
  'settings/livetalking/enabled': 'true',
  'settings/livetalking/server-url': '"http://127.0.0.1:8010"',
  'settings/livetalking/scale': '1',
  'settings/livetalking/position': '{"x":0,"y":0}',
}

;(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Users/pc/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe',
  })
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await ctx.newPage()

  const logs = []
  page.on('console', (msg) => {
    if (['error', 'warning'].includes(msg.type()))
      logs.push(`[console.${msg.type()}] ${msg.text().slice(0, 500)}`)
  })
  page.on('pageerror', err => logs.push(`[pageerror] ${err.message}\n${(err.stack || '').split('\n').slice(0, 8).join('\n')}`))

  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 })
  await page.evaluate((seed) => {
    for (const [k, v] of Object.entries(seed))
      localStorage.setItem(k, v)
  }, seed)

  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(15000)

  const bodyText = await page.evaluate(() => document.body?.innerText?.slice(0, 500) || '')
  await page.screenshot({ path: 'E:/work/LiveTalking/my_tools/image/_airi_livetalking.png' })

  console.log('=== BODY ===')
  console.log(bodyText)
  console.log('=== ERRORS (' + logs.length + ') ===')
  console.log(logs.slice(0, 40).join('\n'))
  await browser.close()
})()
