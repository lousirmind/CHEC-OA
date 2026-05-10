# step2_login_start_workflow.py
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

# ================== 模块3：启动流程 ==================
def start_workflow(page, process_name="收文流程", operator="陈乙东庭（Chen Yidongting）"):
    print("🚀 开始启动收文流程...")
    
    # 1. 进入待发文档
    doc_manage = page.get_by_title("文档管理")
    pending_doc = page.get_by_text("待发文档", exact=True)
    if not pending_doc.is_visible():
        doc_manage.click()
        page.wait_for_timeout(10000)
    pending_doc.click()
    
    # 等待 iframe 出现
    page.wait_for_selector("iframe", state="attached", timeout=10000)
    doc_frame = page.frame_locator("iframe").first
    doc_frame.locator("tbody tr").first.wait_for(state="attached", timeout=20000)
    
    # 2. 勾选第一行复选框
    checkbox = doc_frame.locator("td.layui-table-col-special.hide-grid div.layui-form-checkbox").first
    if checkbox.count() == 0:
        first_row = doc_frame.locator("tbody tr").first
        checkbox = first_row.locator("div.layui-form-checkbox")
    if checkbox.count() == 0:
        checkbox = doc_frame.locator("i.layui-icon-o, i.layui-icon-ok").first
    checkbox.click()
    print("✅ 已勾选第一行")
    page.wait_for_timeout(5000)
    
    # 3. 点击“流程”按钮
    doc_frame.get_by_role("button", name="流程").click()
    page.wait_for_timeout(5000)
    
    # 4. 选择流程模板
    try:
        process_select = doc_frame.locator("label:has-text('流程模板')").locator("..").get_by_placeholder("请选择")
        process_select.click()
    except:
        doc_frame.get_by_placeholder("请选择").first.click()
    doc_frame.locator("dd").filter(has_text=process_name).click()
    print("✅ 已选择流程模板:", process_name)
    
    # 5. 等待单选框加载
    page.wait_for_timeout(2000)
    
    # 6. 点击“dcc”单选按钮
    dcc_radio = doc_frame.get_by_text("dcc", exact=True)
    if dcc_radio.count() > 0:
        dcc_radio.click()
    else:
        doc_frame.locator("input[type='radio'][value='dcc']").click()
    print("✅ 已选择下一步节点: dcc")
    page.wait_for_timeout(2000)
    
    # 7. 点击“下一步操作人”选择框
    operator_input = doc_frame.get_by_placeholder("请选择dcc节点操作人")
    operator_input.click()
    print("⏳ 等待选人弹窗...")
    page.wait_for_timeout(2000)
    
    # 8. 处理选人弹窗
    page.wait_for_selector('iframe[name*="layui-layer"]', state="attached", timeout=10000)
    user_frame = page.frame_locator('iframe[name*="layui-layer"]').last
    user_frame.get_by_text(operator, exact=True).wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(5000)
    user_frame.get_by_text(operator, exact=True).click()
    print(f"✅ 已选择操作人: {operator}")
    page.wait_for_timeout(1000)
    
    # 9. 点击确认按钮
    confirm_btn = page.locator("a.layui-layer-btn0:visible")
    confirm_btn.wait_for(state="visible", timeout=10000)
    confirm_btn.click()
    print("✅ 已点击确认按钮")
    page.wait_for_timeout(5000)
    
    # 10. 点击启动流程
    start_btn = doc_frame.get_by_role("button", name="启动流程")
    if start_btn.count() == 0:
        start_btn = page.get_by_role("button", name="启动流程")
    start_btn.click()
    print("✅ 已点击启动流程")
    
    page.wait_for_timeout(3000)
    print("✅ 流程已启动")
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
        
        # 执行启动流程
        start_workflow(page)
        
        context.close()
        browser.close()

if __name__ == "__main__":
    main()