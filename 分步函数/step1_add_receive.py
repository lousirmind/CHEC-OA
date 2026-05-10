# step1_add_receive.py
import re
import time
import json
import os
from collections import defaultdict
from playwright.sync_api import sync_playwright

# ================== 配置（与原来一致） ==================
DEFAULT_TIMEOUT = 30000
SHORT_TIMEOUT = 5000

SENDER_CODE_MAP = {
    "东非商务合约部公邮": "DFSWB",
    "ea.tech@check.bj.cn": "DFKJB",
    "东非工程部公邮": "DFGCB",
    "notice@qiye.163.com": "WYY",
    "twaha.msita@ports.go.tz": "TPA",
    "abdi.issa@ports.go.tz": "TPA",
    "aggrey.nhnyete@ports.go.tz": "TPA",
    "des@ports.go.tz": "DES",
    "dg@ports.go.tz": "DP",
    "DPWDSM.SecurityAdm@dpworld.com": "DPW",
    "edmund@interconsult-tz.com": "PM",
    "Emmanuel Magori": "PM",
    "四院马林迪项目公邮": "SHY",
    "坦桑尼亚达港马林迪泊位改扩建项目公邮": "SHY",
}

SOURCE_CODE_MAP = {
    "source1@company.com": "MLD",
    "source2@company.com": "DMGP5-7",
}

SOURCE_PROJECT_MAP = {
    "source1@company.com": "某某工程项目名称",
    "source2@company.com": "另一个项目名称",
}

COUNTER_FILE = "seq_counter.json"

def load_counter():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return json.load(f)
    return defaultdict(int)

def save_counter(counter):
    with open(COUNTER_FILE, "w") as f:
        json.dump(dict(counter), f, indent=2)

def get_sender_code(sender_name):
    name = sender_name.strip()
    if name in SENDER_CODE_MAP:
        return SENDER_CODE_MAP[name]
    for key, code in SENDER_CODE_MAP.items():
        if key.lower() == name.lower():
            return code
    return "UKN"

def get_cell_text_by_header(row, frame, header_text):
    headers = frame.locator("thead tr th").all_text_contents()
    headers = [h.strip() for h in headers]
    try:
        col_index = headers.index(header_text)
    except ValueError:
        for idx, h in enumerate(headers):
            if header_text in h:
                col_index = idx
                break
        else:
            return ""
    cells = row.locator("td").all()
    if col_index < len(cells):
        return cells[col_index].inner_text().strip()
    return ""

def click_next_page(frame, page):
    next_btn = frame.locator("div.layui-table-page").get_by_text(">", exact=True)
    if next_btn.count() == 0:
        next_btn = frame.locator("div.layui-table-page").get_by_text("下一页", exact=True)
    if next_btn.count() == 0:
        next_btn = frame.locator("a.layui-laypage-next")
    if next_btn.count() == 0:
        return False
    if next_btn.get_attribute("class") and "disabled" in next_btn.get_attribute("class"):
        return False
    next_btn.click()
    try:
        frame.locator("tbody tr").first.wait_for(state="attached", timeout=5000)
    except:
        frame.locator("tbody").wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(5000)
    return True

def is_logged_in(page):
    try:
        page.get_by_title("邮件管理").wait_for(state="visible", timeout=5000)
        return True
    except:
        return False

def do_login(page, username="your-username", password="your-password"):
    print("🔐 开始登录...")
    page.goto("http://your-oa-server.com/cloudoa/login")
    page.get_by_placeholder("请输入用户名").fill(username)
    page.get_by_placeholder("请输入密码").fill(password)
    captcha_input = page.get_by_role("textbox", name="验证码")
    captcha_input.scroll_into_view_if_needed()
    captcha_input.click()
    print("👀 请查看浏览器窗口，手动输入验证码，然后按回车键继续...")
    input("✅ 输入完成后按回车键 --> ")
    page.get_by_role("button", name="登 录").click()
    page.get_by_title("邮件管理").wait_for(state="visible", timeout=5000)
    print("✅ 登录成功")
    return True

def open_public_mailbox(page):
    """一次性打开公共邮箱，返回 mail_frame 对象"""
    print("📂 打开公共邮箱...")
    mail_manage = page.get_by_title("邮件管理")
    public_mail = page.get_by_title("公共邮箱")  # 使用 title 定位，唯一
    if not public_mail.is_visible():
        mail_manage.click()
        page.wait_for_timeout(5000)
        public_mail = page.get_by_title("公共邮箱")
    public_mail.click()
    page.wait_for_timeout(5000)
    mail_frame = page.frame_locator("iframe").first
    mail_frame.locator("tbody tr").first.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    mail_frame.get_by_role("combobox").select_option("90")
    mail_frame.locator("tbody tr").first.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    page.wait_for_timeout(5000)
    print("✅ 公共邮箱已打开，表格已加载")
    return mail_frame

def add_one_receive(page, mail_frame):
    """
    在已打开的公共邮箱中执行一次添加收文操作
    返回 (success, matched_source, matched_sender)
    """
    counter = load_counter()
    max_pages = 10
    current_page = 1
    target_row = None
    matched_source = None
    matched_sender = None

    while current_page <= max_pages:
        print(f"🔍 正在检查第 {current_page} 页...")
        rows = mail_frame.locator("tbody tr").all()
        for row in rows:
            status_cell = row.locator("td").filter(has_text=re.compile(r"未转收文"))
            if status_cell.count() == 0:
                continue
            sender_text = get_cell_text_by_header(row, mail_frame, "发件人")
            source_text = get_cell_text_by_header(row, mail_frame, "来源")
            if sender_text and "postmaster@qiye.163.com" in sender_text:
                continue
            if source_text and ("source1@company.com" in source_text or "source2@company.com" in source_text):
                target_row = row
                matched_source = source_text
                matched_sender = sender_text
                print(f"✅ 在第 {current_page} 页找到符合条件的邮件")
                print(f"   发件人: {matched_sender}")
                print(f"   来源: {matched_source}")
                break
        if target_row:
            break
        else:
            if not click_next_page(mail_frame, page):
                print("❌ 无法继续翻页，已到最后一页")
                break
            current_page += 1
            mail_frame = page.frame_locator("iframe").first

    if not target_row:
        print("❌ 未找到符合条件的未转收文邮件")
        return False, None, None

    # 右键转收文
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    subject_link = target_row.locator("a").first
    subject_link.click(button="right")
    try:
        mail_frame.get_by_text("转收文", exact=True).wait_for(state="visible", timeout=5000)
    except:
        subject_link.click(button="right")
        mail_frame.get_by_text("转收文", exact=True).wait_for(state="visible", timeout=5000)
    mail_frame.get_by_text("转收文", exact=True).click()

    # 等待弹窗
    page.wait_for_selector('iframe[name*="layui-layer-iframe"]', state="attached", timeout=5000)
    iframe_elements = page.locator('iframe[name*="layui-layer-iframe"]').all()
    last_iframe_name = iframe_elements[-1].get_attribute("name")
    trans_frame = page.frame_locator(f"iframe[name='{last_iframe_name}']").first
    trans_frame.get_by_placeholder("请选择").first.wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(5000)

    # 生成编码
    source_code = SOURCE_CODE_MAP.get(matched_source, "UNKNOWN")
    sender_code_part = get_sender_code(matched_sender)
    key = f"{source_code}-{sender_code_part}-CHEC"
    current_seq = counter.get(key, 0) + 1
    seq_str = f"{current_seq:04d}"
    dynamic_sender_code = f"{source_code}-{sender_code_part}-CHEC-{seq_str}"
    print(f"📝 生成发信方编码: {dynamic_sender_code}")
    counter[key] = current_seq
    save_counter(counter)

    selected_project = SOURCE_PROJECT_MAP.get(matched_source, "某某工程项目名称")
    print(f"📁 选择项目: {selected_project}")

    # 填写表单
    # 收文类型
    type_selector = trans_frame.locator("div").filter(has_text=re.compile(r"^请选择信函$")).get_by_placeholder("请选择")
    type_selector.click()
    trans_frame.locator("dd").filter(has_text=re.compile(r"^信函$")).click()
    page.wait_for_timeout(5000)

    # 发信方编码
    sender_code_input = trans_frame.locator("//label[contains(text(),'发信方编码')]/following-sibling::div//input")
    sender_code_input.fill(dynamic_sender_code)

    # 发文单位
    unit_selector = trans_frame.get_by_role("textbox", name="请选择", exact=True).nth(1)
    unit_selector.click()
    trans_frame.get_by_text("当地其他公司").nth(1).click()
    page.wait_for_timeout(5000)

    # 发送方式
    method_selector = trans_frame.locator("div").filter(has_text=re.compile(r"^请选择E-MAIL纸质信函$")).get_by_placeholder("请选择")
    method_selector.click()
    trans_frame.locator("dd").filter(has_text="E-MAIL").click()
    page.wait_for_timeout(5000)

    # 项目名称
    project_selector = trans_frame.get_by_placeholder("请选择项目名称")
    project_selector.click()
    trans_frame.locator("dd").filter(has_text=selected_project).click()
    page.wait_for_timeout(5000)

    # 文号
    trans_frame.locator("#destinationrad").fill(dynamic_sender_code)

    # 点击图标
    trans_frame.locator("i.layui-icon:has-text('')").first.click()
    page.wait_for_timeout(5000)

    # 保存
    trans_frame.get_by_role("button", name="保 存").click()
    try:
        page.wait_for_selector('iframe[name*="layui-layer-iframe"]', state="detached", timeout=5000)
        print("✅ 转收文弹窗已关闭")
    except:
        print("⚠️ 弹窗关闭超时")
    page.wait_for_timeout(2000)
    print("✅ 本次收文添加完成")
    return True, matched_source, matched_sender

def main():
    repeat_count = 100  # 可修改或从输入读取
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # 调试时可设为 False
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()
        page.goto("http://your-oa-server.com/cloudoa/")

        if not is_logged_in(page):
            print("⚠️ 未检测到登录状态，将执行手动登录...")
            if not do_login(page):
                print("登录失败，退出")
                return
        else:
            print("✅ 已通过 auth.json 自动登录")

        # ---------- 只打开一次公共邮箱 ----------
        mail_frame = open_public_mailbox(page)

        success_count = 0
        for i in range(repeat_count):
            print(f"\n{'='*50}")
            print(f"第 {i+1} 次添加收文")
            print(f"{'='*50}")
            ok, _, _ = add_one_receive(page, mail_frame)
            if ok:
                success_count += 1
            else:
                print("❌ 添加收文失败，停止循环")
                break

        print(f"\n🎉 完成！成功添加 {success_count} 次收文")
        context.close()
        browser.close()

if __name__ == "__main__":
    main()