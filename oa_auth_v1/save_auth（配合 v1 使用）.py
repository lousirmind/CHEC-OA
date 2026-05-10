from playwright.sync_api import sync_playwright

def save_login_state():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        page.goto("http://checea.edmcs.cn/cloudoa/login")
        page.get_by_placeholder("请输入用户名").fill("ydtchen")
        page.get_by_placeholder("请输入密码").fill("Lz156970.")
        
        print("请手动查看浏览器，输入验证码并点击登录...")
        input("登录成功后，请按回车键继续...")
        
        # 关键：等待页面跳转到首页，并且“邮件管理”标题可见（证明登录成功）
        try:
            page.wait_for_url("http://checea.edmcs.cn/cloudoa/**", timeout=10000)
            page.get_by_title("邮件管理").wait_for(state="visible", timeout=10000)
            print("✅ 登录确认成功，正在保存状态...")
        except Exception as e:
            print("❌ 等待登录成功标志超时，请检查是否已成功登录")
            browser.close()
            return
        
        # 额外等待2秒确保所有异步存储完成
        page.wait_for_timeout(2000)
        
        # 保存状态
        context.storage_state(path="auth.json")
        print("登录状态已保存到 auth.json 文件！")
        
        browser.close()

if __name__ == "__main__":
    save_login_state()