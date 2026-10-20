/**
 * airi LiveTalking 头像切换端到端测试：
 * 改 localStorage 里的 settings/livetalking/avatar（与设置页下拉同一数据源）
 * → 验证客户端自动重连 → 服务端会话的 avatar_id 跟着变化 → 视频流可用。
 *
 * 用法: node my_tools/airi_avatar_switch_test.js
 */
const { chromium } = require('E:/work/airi/node_modules/playwright')

const APP = 'http://localhost:5173/'
const CHROME = 'C:/Users/pc/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe'
const API = 'http://127.0.0.1:8010'

async function serverSessions() {
  const res = await fetch(`${API}/api/admin/sessions`)
  const json = await res.json()
  return json?.data?.sessions ?? []
}

function nukeOnboarding(page) {
  return page.evaluate(() => {
    document.querySelectorAll('[class*="z-9999"]').forEach(el => el.remove())
    document.querySelectorAll('body > div').forEach((el) => {
      if ((el.innerText || '').includes('欢迎来到 AIRI'))
        el.remove()
    })
    document.documentElement.style.pointerEvents = 'auto'
    document.body.style.pointerEvents = 'auto'
  })
}

async function waitForVideo(page, timeoutMs = 15000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const ok = await page.evaluate(() => {
      const v = document.querySelector('video')
      return !!v && !!v.srcObject && v.readyState >= 2 && v.videoWidth > 0
    })
    if (ok)
      return true
    await page.waitForTimeout(300)
  }
  return false
}

async function openHomeWithAvatar(browser, avatarId) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  await page.goto(APP, { waitUntil: 'domcontentloaded' })
  await page.evaluate((id) => {
    localStorage.setItem('settings/livetalking/enabled', 'true')
    localStorage.setItem('settings/livetalking/server-url', 'http://127.0.0.1:8010')
    localStorage.setItem('settings/livetalking/avatar', id)
  }, avatarId)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(600)
  await nukeOnboarding(page)
  return page
}

async function waitForServerAvatar(avatarId, timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const sessions = await serverSessions()
    if (sessions.some(s => s.avatar_id === avatarId))
      return true
    await new Promise(r => setTimeout(r, 500))
  }
  return false
}

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME })
  const fails = []

  // [1] 列表接口（设置页数据源）
  const listRes = await fetch(`${API}/api/avatars`)
  const listJson = await listRes.json()
  const avatars = listJson?.data?.avatars ?? []
  console.log(`[1] GET /api/avatars: ${avatars.length} 个头像 ${avatars.length >= 3 ? '✅' : '❌'}`)
  if (avatars.length < 3)
    fails.push('avatar list incomplete')

  // [2] 默认头像（avatar=''）
  let page = await openHomeWithAvatar(browser, '')
  let ok = await waitForVideo(page)
  console.log(`[2] avatar='' → 默认头像视频流 ${ok ? '✅' : '❌'}`)
  if (!ok)
    fails.push('default video stream')

  // [3] 切到 lady_presenter_anim
  await page.evaluate(() => localStorage.setItem('settings/livetalking/avatar', 'lady_presenter_anim'))
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(600)
  await nukeOnboarding(page)
  ok = await waitForVideo(page)
  const serverOk = await waitForServerAvatar('lady_presenter_anim', 8000)
  console.log(`[3] avatar=lady_presenter_anim → 重连视频流 ${ok ? '✅' : '❌'}, 服务端会话 avatar_id=${serverOk ? 'lady_presenter_anim ✅' : '未切换 ❌'}`)
  if (!ok)
    fails.push('anim video stream')
  if (!serverOk)
    fails.push('server session not on anim')

  // [4] 切回服务端默认
  await page.evaluate(() => localStorage.setItem('settings/livetalking/avatar', ''))
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(600)
  await nukeOnboarding(page)
  ok = await waitForVideo(page)
  const backOk = await waitForServerAvatar('lady_presenter_video', 8000)
  console.log(`[4] avatar='' → 回落默认视频流 ${ok ? '✅' : '❌'}, 服务端会话 avatar_id=${backOk ? 'lady_presenter_video ✅' : '未切换 ❌'}`)
  if (!ok)
    fails.push('fallback video stream')
  if (!backOk)
    fails.push('server session not back to default')

  // [5] 槽位泄漏检查：测试产生的会话不应堆积
  await page.waitForTimeout(2500)
  const sessions = await serverSessions()
  console.log(`[5] 服务端活跃会话: ${sessions.length} 个（≤2 为正常） ${sessions.length <= 2 ? '✅' : '❌'}`)
  if (sessions.length > 2)
    fails.push('session slots leaking')

  console.log(fails.length === 0 ? '\n全部通过 ✅' : `\n失败项: ${fails.join(', ')} ❌`)
  await browser.close()
  process.exit(fails.length === 0 ? 0 : 1)
}

main().catch((e) => { console.error(e); process.exit(1) })
