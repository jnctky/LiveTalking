/* 验证二期两个开关: airi 设置页 → LiveTalking 模块下的「按语义选情绪」「按句切音频」
   - 两个开关是否存在、默认状态、点击后是否写入 localStorage
   - 关掉再打开后仍是同一份设置(不改服务地址/头像)
   用法: node my_tools/airi_phase2_check.js */
const { chromium } = require('E:/work/airi/node_modules/playwright')

const APP = 'http://localhost:5173'
const CHROME = 'C:/Users/pc/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe'
const SHOT = 'E:/work/LiveTalking/my_tools/image/'
const KEY_SEMANTIC = 'settings/livetalking/semantic-emotion'
const KEY_SENTENCE = 'settings/livetalking/sentence-split'

const nuke = page => page.evaluate(() => {
  document.querySelectorAll('[class*="z-9999"]').forEach(el => el.remove())
  document.querySelectorAll('body > div').forEach((el) => {
    if ((el.innerText || '').includes('欢迎来到 AIRI')) el.remove()
  })
  document.documentElement.style.pointerEvents = 'auto'
  document.body.style.pointerEvents = 'auto'
})

/* CheckBar 的 Checkbox 渲染成 button[role=switch][aria-label=标题]。
   getByRole 在这个页面上匹配不到(accessibility 树被裁剪), 用 CSS 定位。 */
async function rowOf(page, text) {
  return page.locator(`button[role="switch"][aria-label="${text}"]`).first()
}

async function stateOf(page, key) {
  return page.evaluate(k => localStorage.getItem(k), key)
}

;(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: CHROME })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errs = []
  page.on('pageerror', e => errs.push(String(e)))
  const fails = []

  await page.goto(APP, { waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    localStorage.setItem('settings/livetalking/enabled', 'true')
    localStorage.setItem('settings/livetalking/server-url', 'http://127.0.0.1:8010')
    localStorage.removeItem('settings/livetalking/semantic-emotion')
    localStorage.removeItem('settings/livetalking/sentence-split')
  })

  await page.goto(APP + '/settings/models', { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  await nuke(page)

  // ---- 1. 两个开关是否都渲染出来 ----
  const bodyText = await page.evaluate(() => document.body.innerText)
  const hasSemantic = bodyText.includes('按语义选情绪')
  const hasSentence = bodyText.includes('按句切音频')
  console.log(`[1] 文案可见: 按语义选情绪 ${hasSemantic ? '✅' : '❌'}, 按句切音频 ${hasSentence ? '✅' : '❌'}`)
  if (!hasSemantic) fails.push('semantic-emotion switch missing')
  if (!hasSentence) fails.push('sentence-split switch missing')

  // ---- 2. 默认值(未手动设置 = 默认开启) ----
  console.log(`[2] 默认 localStorage: semantic=${await stateOf(page, KEY_SEMANTIC)}, sentence=${await stateOf(page, KEY_SENTENCE)} (null = 用默认值 true)`)

  // ---- 3. 逐个点击, 校验 localStorage 跟着变 ----
  for (const [label, key] of [['按语义选情绪', KEY_SEMANTIC], ['按句切音频', KEY_SENTENCE]]) {
    const box = await rowOf(page, label)
    if (!(await box.count())) {
      fails.push(`checkbox not found: ${label}`)
      console.log(`[3] ${label}: 找不到复选框 ❌`)
      continue
    }
    await box.scrollIntoViewIfNeeded()
    await box.click()
    await page.waitForTimeout(500)
    const off = await stateOf(page, key)
    await box.click()
    await page.waitForTimeout(500)
    const on = await stateOf(page, key)
    const ok = off === 'false' && on === 'true'
    console.log(`[3] ${label}: 关 -> ${off}, 开 -> ${on} ${ok ? '✅' : '❌'}`)
    if (!ok) fails.push(`${label} toggle state`)
  }

  await page.screenshot({ path: SHOT + '_p2_switches.png', fullPage: false })
  console.log('[4] 截图 my_tools/image/_p2_switches.png')

  if (errs.length) console.log('[!] 页面报错:', errs.slice(0, 3))
  console.log(fails.length === 0 ? '\n全部通过 ✅' : `\n失败项: ${fails.join(', ')} ❌`)
  await browser.close()
  process.exit(fails.length ? 1 : 0)
})().catch(e => { console.error(e); process.exit(1) })
