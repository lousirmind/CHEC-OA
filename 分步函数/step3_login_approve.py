# step3_login_approve.py
import time
from playwright.sync_api import sync_playwright

# ================== 模块1：登录 ==================
def is_logged_in(page):
    try:
        page.get_by_title("邮件管理").wait_for(state="visible", timeout=10000)
        return True
    except:
        return False

def do_login(page, username="ydtchen", password="Lz156970."):
    print("🔐 开始登录...")
    page.goto("http://checea.edmcs.cn/cloudoa/login")
    page.get_by_placeholder("请输入用户名").fill(username)
    page.get_by_placeholder("请输入密码").fill(password)
    captcha_input = page.get_by_role("textbox", name="验证码")
    captcha_input.scroll_into_view_if_needed()
    captcha_input.click()
    print("👀 请查看浏览器窗口，手动输入验证码，然后按回车键继续...")
    input("✅ 输入完成后按回车键 --> ")
    page.get_by_role("button", name="登 录").click()
    page.get_by_title("邮件管理").wait_for(state="visible", timeout=15000)
    print("✅ 登录成功")
    return True

# ================== 模块4：流程审批 ==================
def approve_workflow(page, opinion="同意"):
    print("✍️ 开始流程审批...")
    
    # 回到首页
    page.get_by_title("首页").click()
    home_frame = page.frame_locator("iframe").first
    page.wait_for_timeout(5000)
    
    # 点击待办任务（收文流程）
    try:
        todo_link = page.locator("a:has-text('收文流程')").first
        todo_link.wait_for(state="visible", timeout=15000)
    except:
        try:
            todo_link = home_frame.locator("a:has-text('收文流程')").first
            todo_link.wait_for(state="visible", timeout=15000)
        except:
            print("❌ 未找到待办任务")
            return False
    
    link_text = todo_link.inner_text()
    print(f"找到待办任务: {link_text}")
    todo_link.click()
    print("✅ 已点击待办任务")
    page.wait_for_timeout(3000)
    
    # 查找提交按钮 #executeTask
    submit_btn = None
    try:
        btn = page.locator("#executeTask").first
        if btn.is_visible(timeout=2000):
            submit_btn = btn
            print("在主页面找到提交按钮")
    except:
        pass
    
    if not submit_btn:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                btn = frame.locator("#executeTask").first
                if btn.is_visible(timeout=2000):
                    submit_btn = btn
                    print(f"在 iframe '{frame.name}' 中找到提交按钮")
                    break
            except:
                continue
    
    if not submit_btn:
        page.screenshot(path="debug_no_submit_btn.png")
        print("所有 frames:")
        for f in page.frames:
            print(f"  name={f.name}, url={f.url}")
        raise Exception("未找到提交按钮 #executeTask")
    
    # 点击提交按钮
    try:
        submit_btn.click()
        print("已点击提交按钮")
    except Exception as e:
        print(f"点击提交按钮失败: {e}")
        raise
    
    # 处理二次确认弹窗
    page.wait_for_timeout(2000)
    try:
        confirm_btn = None
        for selector in ["button:has-text('确定')", "button:has-text('确 定')"]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1000):
                    confirm_btn = btn
                    break
            except:
                pass
        if not confirm_btn:
            for frame in page.frames:
                for selector in ["button:has-text('确定')", "button:has-text('确 定')"]:
                    try:
                        btn = frame.locator(selector).first
                        if btn.is_visible(timeout=1000):
                            confirm_btn = btn
                            break
                    except:
                        pass
                if confirm_btn:
                    break
        if confirm_btn:
            confirm_btn.click()
            print("已点击确认按钮")
        else:
            page.once("dialog", lambda dialog: dialog.accept())
            print("尝试处理原生确认框")
    except Exception as e:
        print(f"确认弹窗处理失败: {e}")
    
    page.wait_for_timeout(3000)
    print("✅ 审批完成")
    return True

# ================== 主函数 ==================
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 建议设为 False 便于观察
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()
        page.goto("http://checea.edmcs.cn/cloudoa/")
        
        if not is_logged_in(page):
            print("⚠️ 未检测到登录状态，将执行手动登录...")
            if not do_login(page):
                print("登录失败，退出")
                return
        else:
            print("✅ 已通过 auth.json 自动登录")
        
        # 执行审批
        approve_workflow(page)
        
        context.close()
        browser.close()

if __name__ == "__main__":
    main()