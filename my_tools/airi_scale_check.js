/* 诊断: airi 设置里 LiveTalking 模块的「缩放」是否真的作用到视频上
   A. 直接改 localStorage 的 scale 再刷新, 看 <video> 的 computed transform / 尺寸是否变
      若 A 变 → CSS 链路正常, 问题在设置面板写入
      若 A 不变 → 渲染层有问题
   B. 在设置页拖动 scale 滑块, 看 localStorage 是否写入
   用法: node my_tools/airi_scale_check.js */
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

async function videoInfo(page) {
  return page.evaluate(() => {
    const v = document.querySelector('video')
    if (!v)
      return null
    const cs = getComputedStyle(v)
    const r = v.getBoundingClientRect()
    return {
      transform: cs.transform,
      inline: v.getAttribute('style') || '',
      w: Math.round(r.width),
      h: Math.round(r.height),
      vw: v.videoWidth,
      vh: v.videoHeight,
    }
  })
}

async function setScaleAndLoad(page, scale) {
  await page.goto(APP, { waitUntil: 'domcontentloaded' })
  await page.evaluate((s) => {
    localStorage.setItem('settings/livetalking/enabled', 'true')
    localStorage.setItem('settings/livetalking/server-url', 'http://127.0.0.1:8010')
    localStorage.setItem('settings/livetalking/scale', String(s))
  }, scale)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(6000)
  await nuke(page)
  return videoInfo(page)
}

;(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errs = []
  page.on('pageerror', e => errs.push(String(e)))
  page.on('console', m => { if (m.type() === 'error') errs.push(`console: ${m.text()}`) })

  // ---- A. localStorage 直改 ----
  for (const s of [1, 1.8]) {
    const info = await setScaleAndLoad(page, s)
    console.log(`[A] scale=${s} ->`, JSON.stringify(info))
    await page.screenshot({ path: `${SHOT}_scale_${String(s).replace('.', '_')}.png` })
  }

  // ---- B. 设置面板滑块 ----
  await page.goto(APP + '/settings/models', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  await nuke(page)

  const sliders = await page.evaluate(() => Array.from(document.querySelectorAll('input[type="range"]')).map((el, i) => ({
    i,
    min: el.min,
    max: el.max,
    step: el.step,
    value: el.value,
    label: (el.closest('div')?.parentElement?.innerText || '').slice(0, 60).replace(/\n/g, ' | '),
  })))
  console.log('[B] 所有滑块:', JSON.stringify(sliders, null, 1))

  // scale 滑块: min=2000 max=30000 step=100 (Range 内部 *10000)
  const idx = sliders.findIndex(s => Number(s.min) === 2000 && Number(s.max) === 30000)
  if (idx >= 0) {
    const before = await page.evaluate(k => localStorage.getItem('settings/livetalking/scale'), null)
    await page.evaluate((i) => {
      const el = document.querySelectorAll('input[type="range"]')[i]
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
      setter.call(el, '18000')
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }, idx)
    await page.waitForTimeout(800)
    const after = await page.evaluate(() => localStorage.getItem('settings/livetalking/scale'))
    console.log(`[B] scale 滑块写入: ${before} -> ${after} ${after === '1.8' ? '✅' : '❌'}`)
  }
  else { console.log('[B] 没找到 scale 滑块 ❌') }

  await page.screenshot({ path: `${SHOT}_scale_panel.png` })
  if (errs.length)
    console.log('[!] 报错:', errs.slice(0, 5))
  await browser.close()
})().catch(e => { console.error(e); process.exit(1) })
