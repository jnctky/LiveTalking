// 打开 airi dev 页面，抓控制台/页面错误并截图，用于定位加载失败原因
// 用法: node my_tools/airi_page_check.js [url]
const { chromium } = require('E:/work/airi/node_modules/playwright')

const url = process.argv[2] || 'http://localhost:5173/'

;(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Users/pc/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe',
  })
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })

  const logs = []
  page.on('console', (msg) => {
    if (['error', 'warning'].includes(msg.type()))
      logs.push(`[console.${msg.type()}] ${msg.text()}`)
  })
  page.on('pageerror', err => logs.push(`[pageerror] ${err.message}\n${(err.stack || '').split('\n').slice(0, 6).join('\n')}`))
  page.on('requestfailed', req => logs.push(`[requestfailed] ${req.url()} :: ${req.failure()?.errorText}`))

  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 })
  }
  catch (e) {
    logs.push(`[goto-failed] ${e.message}`)
  }

  await page.waitForTimeout(12000)

  const bodyText = await page.evaluate(() => document.body?.innerText?.slice(0, 600) || '')
  const shot = 'E:/work/LiveTalking/my_tools/image/_airi_page.png'
  await page.screenshot({ path: shot, fullPage: false })

  console.log('=== URL:', url)
  console.log('=== BODY TEXT ===')
  console.log(bodyText)
  console.log('=== ERRORS (' + logs.length + ') ===')
  console.log(logs.slice(0, 40).join('\n'))
  console.log('=== SCREENSHOT:', shot)
  await browser.close()
})()
