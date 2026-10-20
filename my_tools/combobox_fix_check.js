/* 展开头像下拉并截图验证选项渲染 */
const { chromium } = require('playwright');

(async () => {
  const APP = 'http://localhost:5173';
  const browser = await chromium.launch({
    executablePath: 'C:/Users/pc/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe',
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));

  await page.goto(APP, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    localStorage.setItem('settings/livetalking/enabled', 'true');
    localStorage.setItem('settings/livetalking/server-url', 'http://127.0.0.1:8010');
    localStorage.removeItem('settings/livetalking/avatar');
  });
  await page.goto(APP + '/settings/models', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  await page.evaluate(() => {
    document.querySelectorAll('[class*="z-9999"]').forEach(el => el.remove());
    document.querySelectorAll('body > div').forEach((el) => {
      if ((el.innerText || '').includes('欢迎来到 AIRI')) el.remove();
    });
    document.documentElement.style.pointerEvents = 'auto';
    document.body.style.pointerEvents = 'auto';
  });
  await page.waitForTimeout(500);

  // 头像下拉可能需要先开 LiveTalking 开关才渲染; 先找 ComboboxSelect 根元素
  const info = await page.evaluate(() => {
    const els = [...document.querySelectorAll('input, button, [role="combobox"]')];
    return els.map(b => ({ tag: b.tagName, role: b.getAttribute('role'), cls: (b.className || '').slice(0, 40), text: (b.value || b.textContent || '').trim().slice(0, 40) })).filter(x => x.text.includes('默认') || x.text.includes('lady') || /avatar/i.test(x.cls));
  });
  console.log('候选触发器:', JSON.stringify(info.slice(0, 8), null, 1));

  // 点开下拉（Combobox 触发器可能是 input 或 button）
  const btn = page.locator('input[value*="默认"], input[value*="lady"], button:has-text("默认"), [role="combobox"]').first();
  const n = await btn.count();
  console.log('触发器数量:', n);
  if (n > 0) {
    await btn.scrollIntoViewIfNeeded();
    await btn.click();
    await page.waitForTimeout(900);
    const items = await page.evaluate(() =>
      [...document.querySelectorAll('[role="option"]')].map(o => o.textContent?.trim()));
    console.log('下拉选项:', JSON.stringify(items));
    // 选 natural
    const nat = page.locator('[role="option"]', { hasText: 'lady_presenter_natural' });
    if (await nat.count() > 0) {
      await nat.click();
      await page.waitForTimeout(600);
      const stored = await page.evaluate(() => localStorage.getItem('settings/livetalking/avatar'));
      console.log('localStorage avatar =', stored);
    }
    await page.screenshot({ path: 'E:/work/LiveTalking/my_tools/image/_combobox_fix.png' });
  }
  await page.screenshot({ path: 'E:/work/LiveTalking/my_tools/image/_settings_page.png', fullPage: false });
  console.log('url =', page.url());
  const cErr = errors.filter(e => e.includes('ComboboxItem') || e.includes('value prop'));
  console.log('ComboboxItem 错误:', cErr.length ? cErr[0].slice(0, 120) : '无 ✅');
  await browser.close();
})();
