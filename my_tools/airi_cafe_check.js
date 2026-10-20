/* 验证 cafe_presenter 已进入 airi 头像下拉, 切换后视频流可用、服务端会话切到该头像 */
const { chromium } = require('E:/work/airi/node_modules/playwright')

const APP = 'http://localhost:5173'
const API = 'http://127.0.0.1:8010'
const CHROME = 'C:/Users/pc/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe'
const TARGET = 'cafe_presenter'
const SHOT = 'E:/work/LiveTalking/my_tools/image/'

const nuke = page => page.evaluate(() => {
  document.querySelectorAll('[class*="z-9999"]').forEach(el => el.remove())
  document.querySelectorAll('body > div').forEach((el) => {
    if ((el.innerText || '').includes('欢迎来到 AIRI')) el.remove()
  })
  document.documentElement.style.pointerEvents = 'auto'
  document.body.style.pointerEvents = 'auto'
})

async function waitVideo(page, ms = 15000) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    const ok = await page.evaluate(() => {
      const v = document.querySelector('video')
      return !!v && !!v.srcObject && v.readyState >= 2 && v.videoWidth > 0
    })
    if (ok) return true
    await page.waitForTimeout(300)
  }
  return false
}

async function sessions() {
  const r = await fetch(`${API}/api/admin/sessions`)
  return (await r.json())?.data?.sessions ?? []
}

async function waitServerAvatar(id, ms = 20000) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    if ((await sessions()).some(s => s.avatar_id === id)) return true
    await new Promise(r => setTimeout(r, 500))
  }
  return false
}

;(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errs = []
  page.on('pageerror', e => errs.push(String(e)))
  const fails = []

  await page.goto(APP, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('settings/livetalking/enabled', 'true')
    localStorage.setItem('settings/livetalking/server-url', 'http://127.0.0.1:8010')
    localStorage.removeItem('settings/livetalking/avatar')
  })

  // ---- 1. 设置页下拉里是否出现 cafe_presenter ----
  await page.goto(APP + '/settings/models', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  await nuke(page)
  const trigger = page.locator('[role="combobox"], input[value*="默认"], input[value*="lady"], input[value*="cafe"]').first()
  let options = []
  if (await trigger.count()) {
    await trigger.scrollIntoViewIfNeeded()
    await trigger.click()
    await page.waitForTimeout(900)
    options = await page.evaluate(() => [...document.querySelectorAll('[role="option"]')].map(o => o.textContent?.trim()))
    await page.screenshot({ path: SHOT + '_cafe_dropdown.png' })
  }
  const inList = options.some(o => (o || '').includes(TARGET))
  console.log(`[1] 下拉选项 ${options.length} 个, 含 ${TARGET}: ${inList ? '✅' : '❌'}`)
  console.log('    ', JSON.stringify(options))
  if (!inList) fails.push('dropdown missing cafe_presenter')

  // ---- 2. 点选 cafe_presenter ----
  if (inList) {
    const opt = page.locator('[role="option"]', { hasText: TARGET }).first()
    await opt.click()
    await page.waitForTimeout(700)
    const stored = await page.evaluate(() => localStorage.getItem('settings/livetalking/avatar'))
    console.log(`[2] 点选后 localStorage avatar = ${stored} ${stored === TARGET ? '✅' : '❌'}`)
    if (stored !== TARGET) fails.push('localStorage not updated')
    await page.screenshot({ path: SHOT + '_cafe_selected.png' })
  }

  // ---- 3. 回主页, 视频流 + 服务端会话 ----
  await page.goto(APP, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)
  await nuke(page)
  const okVideo = await waitVideo(page, 25000)
  const okSess = await waitServerAvatar(TARGET, 20000)
  console.log(`[3] 视频流 ${okVideo ? '✅' : '❌'}, 服务端会话 avatar_id=${TARGET} ${okSess ? '✅' : '❌'}`)
  if (!okVideo) fails.push('video stream')
  if (!okSess) fails.push('server session')

  // ---- 4. 抓一帧真实播放画面 ----
  await page.waitForTimeout(2500)
  const frame = await page.evaluate(() => {
    const v = document.querySelector('video')
    if (!v) return null
    const c = document.createElement('canvas')
    c.width = v.videoWidth || 864
    c.height = v.videoHeight || 1152
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height)
    return c.toDataURL('image/png')
  })
  if (frame) {
    const fs = require('fs')
    fs.writeFileSync(SHOT + '_cafe_live_frame.png', Buffer.from(frame.split(',')[1], 'base64'))
    console.log('[4] 播放帧已存 my_tools/image/_cafe_live_frame.png')
  } else {
    fails.push('no canvas frame')
  }
  await page.screenshot({ path: SHOT + '_cafe_airi_page.png' })

  const ss = await sessions()
  console.log(`[5] 活跃会话 ${ss.length} 个: ${ss.map(s => s.avatar_id).join(', ')}`)
  if (errs.length) console.log('[!] 页面报错:', errs.slice(0, 3))

  console.log(fails.length === 0 ? '\n全部通过 ✅' : `\n失败项: ${fails.join(', ')} ❌`)
  await browser.close()
  process.exit(fails.length ? 1 : 0)
})().catch(e => { console.error(e); process.exit(1) })
