// Install playwright-core separately, then set PAGELET_PLAYWRIGHT to its module directory.
const assert = require('node:assert/strict')
const { spawn } = require('node:child_process')
const { once } = require('node:events')
const { join } = require('node:path')
const { createInterface } = require('node:readline')
const { test } = require('node:test')
const { chromium } = require(process.env.PAGELET_PLAYWRIGHT || 'playwright-core')

async function localPost(url, path, payload) {
  const html = await (await fetch(url, { signal: AbortSignal.timeout(2000) })).text()
  const [, token] = html.match(/<meta name="local-token" content="([^"]+)"/)
  return fetch(url + path, { method: 'POST', signal: AbortSignal.timeout(2000),
    headers: { 'Content-Type': 'application/json', 'X-Local-Token': token },
    body: JSON.stringify(payload) })
}

test('account actions open the provider in a new tab without submitting the login form', { timeout: 30000 }, async () => {
  const server = spawn(process.env.PYTHON || 'python', [join(__dirname, 'account_links_browser_fixture.py')],
    { stdio: ['ignore', 'pipe', 'inherit'] })
  const lines = createInterface({ input: server.stdout })
  const exited = once(server, 'exit')
  let browser, url
  try {
    url = (await once(lines, 'line', { signal: AbortSignal.timeout(5000) }))[0]
    browser = await chromium.launch({ channel: 'msedge', executablePath: process.env.PAGELET_BROWSER || undefined })
    const context = await browser.newContext()
    const navigations = []
    await context.route('https://**/*', async route => {
      const request = route.request()
      if (request.isNavigationRequest()) navigations.push([request.url(), request.method(),
        request.postData(), request.headers().referer])
      await route.fulfill({ status: 200, contentType: 'text/html', body: '<title>Book provider</title>' })
    })
    const page = await context.newPage()
    page.setDefaultTimeout(4000)
    const localAuthPosts = []
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/auth/')) {
        localAuthPosts.push(request.url())
      }
    })
    await page.goto(url)
    await page.locator('#login-button').click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('heading', { name: '登录Pagelet' }).waitFor()
    await dialog.getByLabel('账号邮箱').fill('test@example.invalid')
    await dialog.getByLabel('密码', { exact: true }).fill('browser-only-test-password')
    const checkLink = async (label, destination) => {
      const link = dialog.getByRole('link', { name: label })
      await link.waitFor()
      assert.equal(await link.getAttribute('href'), destination)
      assert.equal(await link.getAttribute('rel'), 'noopener noreferrer')
      const [tab] = await Promise.all([context.waitForEvent('page'), link.click()])
      await tab.waitForURL(destination)
      assert.equal(await tab.evaluate(() => window.opener), null)
      await tab.close()
      await dialog.getByRole('heading', { name: '登录Pagelet' }).waitFor()
      assert.equal(page.url(), url + '/')
    }
    await checkLink('去注册', 'https://z-lib.sk/registration')
    await checkLink('忘记密码', 'https://zlib.bz/login')
    assert.deepEqual(navigations, [['https://z-lib.sk/registration', 'GET', null, undefined],
      ['https://zlib.bz/login', 'GET', null, undefined]])
    assert.deepEqual(localAuthPosts, [])

    await dialog.getByRole('button', { name: '关闭登录' }).click()
    await dialog.waitFor({ state: 'hidden' })
    const updated = await localPost(url, '/api/settings', { domain: 'https://z-library.ec' })
    assert.equal(updated.ok, true)
    await page.locator('#login-button').click()
    await dialog.getByRole('link', { name: '忘记密码' }).waitFor()
    assert.equal(await dialog.getByRole('link', { name: '去注册' }).getAttribute('href'), 'https://z-library.ec/registration')
    assert.equal(await dialog.getByRole('link', { name: '忘记密码' }).getAttribute('href'), 'https://z-library.ec/login')
  } finally {
    await browser?.close()
    try {
      if (!url || !(await localPost(url, '/api/shutdown', {})).ok) server.kill()
    } catch { server.kill() }
    lines.close()
    await exited
  }
})
