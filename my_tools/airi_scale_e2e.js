/* 复测: 设置页把 livetalking 缩放滑块设为 2.5 → 校验 localStorage → 回舞台页看视频 transform
   用法: node my_tools/airi_scale_e2e.js */
const { chromium } = require('E:/work/airi/node_modules/playwright')

const APP = 'http://localhost:5173'
const CHROME = 'C:/Users/pc/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe'
const SHOT = 'E:/work/LiveTalking/my_tools/image/'

const nuke = page => page.evaluate(() => {
  document.querySelectorAll('[class*="z-9999"]').forEach(el => el.remove())
  document.querySelectorAll('body > div').forEach((el) => {
    if ((el.innerText || '').includes('欢迎来到 AIRI')) el.remove()
  })
  document.documentElement.style.pointerEvents = 'auto'
  document.body.style.pointerEvents = 'auto'
})

const videoState = page => page.evaluate(() => {
  const v = document.querySelector('video')
  if (!v)
    return null
  const r = v.getBoundingClientRect()
  return { transform: getComputedStyle(v).transform, w: Math.round(r.width), h: Math.round(r.height), connected: !!v.srcObject }
})

;(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errs = []
  page.on('pageerror', e => errs.push(String(e)))

  await page.goto(APP, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('settings/livetalking/enabled', 'true')
    localStorage.setItem('settings/livetalking/server-url', 'http://127.0.0.1:8010')
    localStorage.setItem('settings/livetalking/scale', '1')
    localStorage.setItem('settings/livetalking/avatar', 'cafe_clips')
  })

  // 1. 设置页: 把滑块(min2000 max30000)设为 25000 = 2.5
  await page.goto(APP + '/settings/models', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  await nuke(page)
  const ok = await page.evaluate(() => {
    const el = Array.from(document.querySelectorAll('input[type="range"]')).find(x => x.min === '2000' && x.max === '30000')
    if (!el)
      return false
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    setter.call(el, '25000')
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  })
  await page.waitForTimeout(1000)
  const ls = await page.evaluate(() => localStorage.getItem('settings/livetalking/scale'))
  console.log(`[1] 设置页滑块改 2.5: 找到=${ok}, localStorage=${ls} ${ls === '2.5' ? '✅' : '❌'}`)

  // 2. 回舞台页(不手动改 localStorage), 看视频
  await page.goto(APP + '/', { waitUntil: 'networkidle' })
  await page.waitForTimeout(8000)
  await nuke(page)
  console.log('[2] 舞台视频(scale 应为 2.5):', JSON.stringify(await videoState(page)))
  await page.screenshot({ path: `${SHOT}_e2e_scale_after.png` })

  if (errs.length)
    console.log('[!] 报错:', errs.slice(0, 5))
  await browser.close()
})().catch(e => { console.error(e); process.exit(1) })
