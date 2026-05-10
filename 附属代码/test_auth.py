from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(storage_state="auth.json")
    page = context.new_page()
    page.goto("http://checea.edmcs.cn/cloudoa/")
    page.wait_for_timeout(5000)  # 停留5秒让你观察是否已登录
    browser.close()