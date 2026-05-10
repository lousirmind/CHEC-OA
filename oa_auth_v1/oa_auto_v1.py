import re
import time
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from collections import defaultdict
from playwright.sync_api import sync_playwright, expect
# 全局超时配置（毫秒）
DEFAULT_TIMEOUT = 30000
SHORT_TIMEOUT = 10000

# ================== 邮件配置（请根据实际情况修改） ==================
SENDER_EMAIL = "your-email@qq.com"          # 发件人QQ邮箱
SMTP_PASSWORD = "your-smtp-auth-code"  # QQ邮箱SMTP授权码（不是登录密码）
RECIPIENT_EMAIL = "recipient@email.com"       # 收件人邮箱

# 发信人编号映射表（）
SENDER_CODE_MAP = {
    "东非商务合约部公邮": "DFSWB",
    "ea. tech@check.bj.cn": "DFKJB",   # 注意原图是 check.bj.cn，实际可能是 chec
    "东非工程部公邮": "DFGCB",
    "notice@qiye.163.com": "WYY",
    "twaha.msita@ports.go.tz": "TPA",
    "abdi. issa@ports.go.tz": "TPA",
    "aggrey.nhnyete@ports.go.tz": "TPA",
    "des@ports.go.tz": "DES",
    "dg@ports.go.tz": "DP",
    "DPWDSM.SecurityAdm@dpworld.com": "DPW",
    "edmund@interconsult-tz.com": "PM",
    "Emmanuel Magori": "PM",
    "四院马林迪项目公邮": "SHY",
    "坦桑尼亚达港马林迪泊位改扩建项目公邮": "SHY",
}

# 来源邮箱 -> 来源编号 映射
SOURCE_CODE_MAP = {
    "source1@company.com": "MLD",
    "source2@company.com": "DMGP5-7",
}

# 来源邮箱 -> 项目名称 映射
SOURCE_PROJECT_MAP = {
    "source1@company.com": "某某工程项目名称",
    "source2@company.com": "另一个项目名称",
}

COUNTER_FILE = "seq_counter.json"

def load_counter():
    """加载序号计数器，格式：{'MLD-DFSWB-CHEC': 5, ...}"""
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return json.load(f)
    return defaultdict(int)

def save_counter(counter):
    """保存序号计数器"""
    with open(COUNTER_FILE, "w") as f:
        json.dump(dict(counter), f, indent=2)

def get_sender_code(sender_name):
    """根据发件人文本获取编号，未匹配返回 'UKN'"""
    # 去除首尾空格，并统一处理可能的特殊字符
    name = sender_name.strip()
    # 直接匹配
    if name in SENDER_CODE_MAP:
        return SENDER_CODE_MAP[name]
    # 尝试忽略大小写和多余空格（简单处理）
    for key, code in SENDER_CODE_MAP.items():
        if key.lower() == name.lower():
            return code
    return "UKN"


# ================== 模块1：登录 ==================
def do_login(page, username="your-username", password="your-password"):
    """登录系统，验证码手动输入"""
    print("🔐 开始登录...")
    page.goto("http://your-oa-server.com/cloudoa/login")
    page.get_by_placeholder("请输入用户名").fill(username)
    page.get_by_placeholder("请输入密码").fill(password)
    
    # 获取验证码输入框并高亮提示（方便你找到）
    captcha_input = page.get_by_role("textbox", name="验证码")
    captcha_input.scroll_into_view_if_needed()
    captcha_input.click()
    
    print("👀 请查看浏览器窗口，手动输入验证码，然后按回车键继续...")
    input("✅ 输入完成后按回车键 --> ")   # 脚本会暂停在这里等你
    
    # 注意：上面 input() 阻塞期间，浏览器不会自动点击，你输完验证码后脚本继续
    page.get_by_role("button", name="登 录").click()
    
    # 等待登录成功标志
    page.get_by_title("邮件管理").wait_for(state="visible", timeout=15000)
    print("✅ 登录成功")
    return True

# ================== 模块2：添加收文 ==================
def has_untransferred_mail(frame):
    """检查当前页是否存在状态为'未转收文'的邮件"""
    rows = frame.locator("tbody tr").all()
    for row in rows:
        status_cell = row.locator("td").filter(has_text=re.compile(r"未转收文"))
        if status_cell.count() > 0:
            return True
    return False

def click_next_page(frame, page):
    """点击下一页按钮，返回是否成功点击并等待刷新"""
    # 定位分页区域中的下一页按钮（常见文本为 '>' 或 '下一页'）
    next_btn = frame.locator("div.layui-table-page").get_by_text(">", exact=True)
    if next_btn.count() == 0:
        next_btn = frame.locator("div.layui-table-page").get_by_text("下一页", exact=True)
    if next_btn.count() == 0:
        next_btn = frame.locator("a.layui-laypage-next")
    if next_btn.count() == 0:
        print("❌ 未找到下一页按钮，可能已到最后一页")
        return False
    
    if next_btn.get_attribute("class") and "disabled" in next_btn.get_attribute("class"):
        print("❌ 下一页按钮被禁用，已到最后一页")
        return False
    
    next_btn.click()
    # 等待表格刷新，最多等待15秒
    try:
        frame.locator("tbody tr").first.wait_for(state="attached", timeout=15000)
    except:
        # 如果超时，尝试等待表格重新出现
        frame.locator("tbody").wait_for(state="visible", timeout=15000)
    page.wait_for_timeout(15000)  # 额外缓冲
    return True

def get_cell_text_by_header(row, frame, header_text):
    """根据表头名称获取当前行对应列的文本内容"""
    # 获取表头所有th的文本
    headers = frame.locator("thead tr th").all_text_contents()
    headers = [h.strip() for h in headers]
    try:
        col_index = headers.index(header_text)
    except ValueError:
        # 尝试模糊匹配
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
    
    
def add_receive_document(page, 
                         receive_type="信函",
                         sender_code="",  # 不再使用固定值，改为动态生成
                         send_unit="当地其他公司",
                         send_method="E-MAIL",
                         project_name=""):  # 不再使用固定值，改为动态选择
    print("📧 开始添加收文（基于来源筛选 + 动态编号生成）...")
    
    # 加载序号计数器
    counter = load_counter()
    
    # 1. 进入公共邮箱
    # 确保邮件管理菜单展开并点击公共邮箱
    mail_manage = page.get_by_title("邮件管理")
    # 先检查公共邮箱是否已经可见（可能菜单已展开）
    public_mail = page.get_by_text("公共邮箱")
    if not public_mail.is_visible():
        # 如果不可见，点击邮件管理展开
        mail_manage.click()
        page.wait_for_timeout(1000)  # 等待动画
    public_mail.click()
    
    # 2. 获取邮件列表 iframe，等待表格加载
    page.wait_for_timeout(10000)  # 等待iframe加载
    mail_frame = page.frame_locator("iframe").first
    # 等待表格至少有一行数据
    mail_frame.locator("tbody tr").first.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    # 设置每页显示90条
    mail_frame.get_by_role("combobox").select_option("90")
    # 等待表格刷新
    mail_frame.locator("tbody tr").first.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    page.wait_for_timeout(10000)
    
    # 翻页查找符合条件的未转收文邮件（来源为指定邮箱）
    max_pages = 10
    current_page = 1
    target_row = None
    matched_source = None   # 记录来源邮箱
    matched_sender = None   # 记录发件人文本
    
    while current_page <= max_pages:
        print(f"🔍 正在检查第 {current_page} 页...")
        rows = mail_frame.locator("tbody tr").all()
        
        for row in rows:
                # 检查是否为“未转收文”
            status_cell = row.locator("td").filter(has_text=re.compile(r"未转收文"))
            if status_cell.count() == 0:
                continue
                
                # 获取发件人和来源
            sender_text = get_cell_text_by_header(row, mail_frame, "发件人")
            source_text = get_cell_text_by_header(row, mail_frame, "来源")
                
                # 排除发件人为 postmaster@qiye.163.com 的邮件
            if sender_text and "postmaster@qiye.163.com" in sender_text:
                print(f"⏭️ 跳过发件人为 postmaster@qiye.163.com 的邮件")
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
            print(f"⚠️ 第 {current_page} 页没有符合条件的未转收文邮件，尝试翻页...")
            if not click_next_page(mail_frame, page):
                print("❌ 无法继续翻页，已到最后一页")
                break
            current_page += 1
            mail_frame = page.frame_locator("iframe").first
            continue
    
    if not target_row:
        print("❌ 所有页均无符合条件的未转收文邮件（来源需为 source1@company.com 或 source2@company.com）")
        return False
    
    # 3. 右键点击主题链接（先清除可能残留的菜单）
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    subject_link = target_row.locator("a").first
    subject_link.click(button="right")
    # 等待右键菜单出现
    try:
        mail_frame.get_by_text("转收文", exact=True).wait_for(state="visible", timeout=10000)
    except:
        print("⚠️ 右键菜单未出现，尝试重新右键")
        subject_link.click(button="right")
        mail_frame.get_by_text("转收文", exact=True).wait_for(state="visible", timeout=10000)
    
    # 4. 点击“转收文”
    mail_frame.get_by_text("转收文", exact=True).click()
    
    # 5. 等待转收文表单加载（直接等待弹窗 iframe 出现）
    print("⏳ 等待转收文表单加载...")
    
    try:
        # 等待至少一个弹窗 iframe 出现（layui-layer-iframe 开头）
        page.wait_for_selector('iframe[name*="layui-layer-iframe"]', state="attached", timeout=15000)
        # 获取所有弹窗 iframe，取最后一个（最新的）
        iframe_elements = page.locator('iframe[name*="layui-layer-iframe"]').all()
        if not iframe_elements:
            raise Exception("未找到弹窗 iframe")
        last_iframe_name = iframe_elements[-1].get_attribute("name")
        trans_frame = page.frame_locator(f"iframe[name='{last_iframe_name}']").first
        print(f"✅ 找到转收文表单 iframe: {last_iframe_name}")
    except Exception as e:
        print(f"❌ 等待转收文 iframe 超时: {e}")
        # 调试：打印所有 iframe 的 URL
        for f in page.frames:
            print(f"  frame: {f.name} - {f.url}")
        return False
    
    # 等待表单中的关键元素可见，增加重试
    try:
        trans_frame.get_by_placeholder("请选择").first.wait_for(state="visible", timeout=15000)
    except Exception as e:
        print(f"⚠️ 等待表单元素超时，尝试额外等待 iframe 内容加载...")
        page.wait_for_timeout(10000)
        # 重新获取 trans_frame 再试一次
        trans_frame = page.frame_locator(f"iframe[name='{last_iframe_name}']").first
        trans_frame.get_by_placeholder("请选择").first.wait_for(state="visible", timeout=10000)
    
    page.wait_for_timeout(10000)    
    # ========== 动态生成发信方编码 ==========
    # 确定来源编号
    source_code = SOURCE_CODE_MAP.get(matched_source, "UNKNOWN")
    # 确定发信人编号
    sender_code_part = get_sender_code(matched_sender)
    # 组合键
    key = f"{source_code}-{sender_code_part}-CHEC"
    # 获取当前序号并递增
    current_seq = counter.get(key, 0) + 1
    # 生成四位序号
    seq_str = f"{current_seq:04d}"
    dynamic_sender_code = f"{source_code}-{sender_code_part}-CHEC-{seq_str}"
    print(f"📝 生成发信方编码: {dynamic_sender_code}")
    # 更新计数器
    counter[key] = current_seq
    save_counter(counter)
    
    # 根据来源选择项目名称
    selected_project = SOURCE_PROJECT_MAP.get(matched_source, "某某工程项目名称")
    print(f"📁 选择项目: {selected_project}")
    
    # ========== 填写表单 ==========
    # 6.1 收文类型
    page.wait_for_timeout(10000)
    type_selector = trans_frame.locator("div").filter(has_text=re.compile(r"^请选择信函$")).get_by_placeholder("请选择")
    type_selector.click()
    trans_frame.locator("dd").filter(has_text=re.compile(r"^信函$")).wait_for(state="visible", timeout=10000)
    trans_frame.locator("dd").filter(has_text=re.compile(r"^信函$")).click()
    page.wait_for_timeout(5000)
    
    # 6.2 发信方编码（使用动态生成的编码）
    sender_code_input = trans_frame.locator("//label[contains(text(),'发信方编码')]/following-sibling::div//input")
    sender_code_input.wait_for(state="visible", timeout=10000)
    sender_code_input.fill(dynamic_sender_code)
    
    # 6.3 发文单位
    unit_selector = trans_frame.get_by_role("textbox", name="请选择", exact=True).nth(1)
    unit_selector.wait_for(state="visible", timeout=10000)
    unit_selector.click()
    unit_option = trans_frame.get_by_text(send_unit).nth(1)
    unit_option.wait_for(state="visible", timeout=10000)
    unit_option.click()
    page.wait_for_timeout(10000)
    
    # 6.4 发送方式
    method_selector = trans_frame.locator("div").filter(has_text=re.compile(r"^请选择E-MAIL纸质信函$")).get_by_placeholder("请选择")
    method_selector.click()
    method_option = trans_frame.locator("dd").filter(has_text=send_method)
    method_option.wait_for(state="visible", timeout=10000)
    method_option.click()
    page.wait_for_timeout(10000)
    
    # 6.5 项目名称
    project_selector = trans_frame.get_by_placeholder("请选择项目名称")
    project_selector.wait_for(state="visible", timeout=10000)
    project_selector.click()
    project_option = trans_frame.locator("dd").filter(has_text=selected_project)
    project_option.wait_for(state="visible", timeout=10000)
    project_option.click()
    page.wait_for_timeout(10000)    # 6.6 文号：填入发信方编码
    trans_frame.locator("#destinationrad").fill(dynamic_sender_code)
    
    # 6.7 点击图标
    trans_frame.locator("i.layui-icon:has-text('')").first.click()
    page.wait_for_timeout(10000)
    
    # 7. 点击保存
    trans_frame.get_by_role("button", name="保 存").click()
    
    # 等待保存成功弹窗关闭
    try:
        page.wait_for_selector('iframe[name*="layui-layer-iframe"]', state="detached", timeout=10000)
        print("✅ 转收文弹窗已关闭")
    except:
        print("⚠️ 弹窗关闭超时，但继续执行")
    
    page.wait_for_timeout(2000)
    print("✅ 收文添加完成")
    return True   
     # ================== 模块3：启动收文流程 ==================
def start_workflow(page, process_name="收文流程", operator="操作人姓名（Your Name）"):
    print("🚀 开始启动收文流程...")
    
    # 1. 进入待发文档
    # 确保文档管理菜单展开并点击待发文档
    doc_manage = page.get_by_title("文档管理")
    pending_doc = page.get_by_text("待发文档", exact=True)
    if not pending_doc.is_visible():
        doc_manage.click()
        page.wait_for_timeout(10000)
    pending_doc.click()
    # 等待 iframe 出现
    page.wait_for_selector("iframe", state="attached", timeout=10000)
    doc_frame = page.frame_locator("iframe").first
    # 等待表格加载
    doc_frame.locator("tbody tr").first.wait_for(state="attached", timeout=20000)
    
    # 2. 勾选第一行复选框（你已验证可用的代码）
    checkbox = doc_frame.locator("td.layui-table-col-special.hide-grid div.layui-form-checkbox").first
    if checkbox.count() == 0:
        first_row = doc_frame.locator("tbody tr").first
        checkbox = first_row.locator("div.layui-form-checkbox")
    if checkbox.count() == 0:
        checkbox = doc_frame.locator("i.layui-icon-o, i.layui-icon-ok").first
    checkbox.click()
    print("✅ 已勾选第一行")
    page.wait_for_timeout(10000)
    
    # 3. 点击“流程”按钮
    doc_frame.get_by_role("button", name="流程").click()
    page.wait_for_timeout(10000)  # 等待下拉框出现
    
    # 4. 选择流程模板（收文流程）
    # 注意：可能有多个“请选择”，但流程模板通常是第一个或通过位置定位
    # 采用更精确的方式：找到包含“流程模板”标签旁边的下拉框
    try:
        # 通过标签定位
        process_select = doc_frame.locator("label:has-text('流程模板')").locator("..").get_by_placeholder("请选择")
        process_select.click()
    except:
        # 降级：使用第一个“请选择”
        doc_frame.get_by_placeholder("请选择").first.click()
    # 选择“收文流程”
    doc_frame.locator("dd").filter(has_text=process_name).click()
    print("✅ 已选择流程模板:", process_name)
    
    # 5. 等待2秒，让单选框出现
    print("⏳ 等待单选框加载...")
    page.wait_for_timeout(2000)
    
    # 6. 点击“dcc”单选按钮（通过文本或radio）
    # 方式1：通过文本点击
    dcc_radio = doc_frame.get_by_text("dcc", exact=True)
    if dcc_radio.count() > 0:
        dcc_radio.click()
    else:
        # 方式2：通过radio的value或class
        doc_frame.locator("input[type='radio'][value='dcc']").click()
    print("✅ 已选择下一步节点: dcc")
    page.wait_for_timeout(2000)
    
    # 7. 点击“下一步操作人”选择框（弹出选人窗口）
    operator_input = doc_frame.get_by_placeholder("请选择dcc节点操作人")
    operator_input.click()
    print("⏳ 等待选人弹窗...")
    page.wait_for_timeout(2000)
    
    # 8. 处理选人弹窗
    print("⏳ 等待选人弹窗...")
    page.wait_for_selector('iframe[name*="layui-layer"]', state="attached", timeout=10000)
    user_frame = page.frame_locator('iframe[name*="layui-layer"]').last

    # 直接等待“操作人姓名”这个文本可见（不等待表格）
    operator_text = user_frame.get_by_text(operator, exact=True)
    operator_text.wait_for(state="visible", timeout=10000)
    print("✅ 选人弹窗已加载，准备点击操作人")

    # 额外等待0.5秒，确保弹窗内交互元素稳定
    page.wait_for_timeout(10000)

    # 点击“操作人姓名”四个字
    operator_text.click()
    print(f"✅ 已选择操作人: {operator}")
    page.wait_for_timeout(1000)
    
    # 9. 点击正确的“确定”按钮（弹窗右下角的确认按钮，而非取消选择的按钮）
    print("⏳ 寻找确认按钮...")
    # 定位父页面中 class 为 layui-layer-btn0 的确定按钮（第二个确定）
    confirm_btn = page.locator("a.layui-layer-btn0:visible")
    confirm_btn.wait_for(state="visible", timeout=10000)
    confirm_btn.click()
    print("✅ 已点击确认按钮（第二个确定）")
    page.wait_for_timeout(10000) 
    # 9. 最后点击“启动流程”按钮
    start_btn = doc_frame.get_by_role("button", name="启动流程")
    if start_btn.count() == 0:
        start_btn = page.get_by_role("button", name="启动流程")
    start_btn.click()
    print("✅ 已点击启动流程")
    
    # 等待启动成功（例如弹窗关闭或页面刷新）
    page.wait_for_timeout(3000)
    print("✅ 流程已启动")
    return True
    
# ================== 模块4：流程审批 ==================
def approve_workflow(page, opinion="同意"):
    """从首页待办进入该收文流程，提交审批"""
    print("✍️ 开始流程审批...")
    # 回到首页
    page.get_by_title("首页").click()
    # 首页待办列表在 iframe 中
    home_frame = page.frame_locator("iframe").first
    page.wait_for_timeout(10000)
    
    # 直接点击第一个包含“收文流程”的链接（优先在主页面查找，若失败则在iframe中查找）
    # 等待待办任务出现，最多等待15秒
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
    
    # 等待弹窗加载（给足够时间）
    page.wait_for_timeout(3000)
    
    # 全局查找提交按钮（遍历所有 frame 和主页面）
    submit_btn = None
    # 先尝试在主页面查找
    try:
        btn = page.locator("#executeTask").first
        if btn.is_visible(timeout=2000):
            submit_btn = btn
            print("在主页面找到提交按钮")
    except:
        pass
    
    # 如果主页没有，遍历所有 iframe
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
        # 调试：截图并打印所有 frame 信息
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
    
    # 处理二次确认弹窗（可能为新 iframe 或原生 dialog）
    page.wait_for_timeout(2000)
    try:
        # 查找确认按钮（常见为“确定”或“确 定”）
        confirm_btn = None
        # 先检查主页面
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
                        if btn.is_visible(timeout=10000):
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
            # 尝试原生 confirm
            page.once("dialog", lambda dialog: dialog.accept())
            print("尝试处理原生确认框")
    except Exception as e:
        print(f"确认弹窗处理失败: {e}")
    
    # 等待审批完成
    page.wait_for_timeout(3000)
    print("✅ 审批完成")
    return True
# ================== 模块 5：邮件发送函数 ==================   
def send_result_email(results):
    """发送循环执行结果邮件（使用固定配置）"""
    subject = "OA自动化脚本执行报告"
    body = f"共执行 {len(results)} 次循环，结果如下：\n\n"
    for idx, success in enumerate(results, 1):
        status = "✅ 成功" if success else "❌ 失败"
        body += f"第 {idx} 次: {status}\n"
    
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = Header(SENDER_EMAIL)
    msg["To"] = Header(RECIPIENT_EMAIL)
    msg["Subject"] = Header(subject)
    
    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(SENDER_EMAIL, SMTP_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECIPIENT_EMAIL], msg.as_string())
        server.quit()
        print("📧 结果邮件发送成功")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}") 
# ================== 主函数（串联所有模块） ==================
def is_logged_in(page):
    """检查当前页面是否已登录（通过判断是否存在登录后才出现的元素）"""
    try:
        # 等待一个只有登录后才出现的元素（如“邮件管理”标题），超时时间短一些
        page.get_by_title("邮件管理").wait_for(state="visible", timeout=10000)
        return True
    except:
        return False

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False) #这里设置可以显示是否显示浏览器窗口，T-不显示
        context = browser.new_context(storage_state="auth.json")
        page = context.new_page()

        page.goto("http://your-oa-server.com/cloudoa/")

        # ---------------------- 登录（不属于模块2-4，但必须保留）---------------------
        if not is_logged_in(page):
            print("⚠️ 未检测到登录状态，将执行手动登录...")
            if not do_login(page):
                print("登录失败，退出")
                return
        else:
            print("✅ 已通过 auth.json 自动登录")

        # ---------------------- 设置循环次数（可保留）-------------------------------
        try:
            repeat_count = 200 #int(input("请输入要重复执行的次数（模块2-4将循环执行）: "))
        except ValueError:
            print("输入无效，默认执行1次")
            repeat_count = 1

        results = []  # 记录每次循环的成功状态

        # ========================== 循环开始 ====================================
        for i in range(repeat_count):
            print(f"\n{'='*50}")
            print(f"第 {i+1} 次循环开始")
            print(f"{'='*50}")

            # 每次循环前回到首页并刷新（建议保留，用于清理状态）
            page.goto("http://your-oa-server.com/cloudoa/")
            page.wait_for_load_state("networkidle", timeout=15000)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
# 
            success = True

            # ================= 模块2：添加收文 =================
            if not add_receive_document(page):
                print(f"第 {i+1} 次循环：添加收文失败")
                success = False
            # ================= 模块3：启动流程 =================
            elif not start_workflow(page):
                print(f"第 {i+1} 次循环：启动流程失败")
                success = False
            # ================= 模块4：流程审批 =================
            elif not approve_workflow(page):
                print(f"第 {i+1} 次循环：审批失败")
                success = False
            else:
                print(f"第 {i+1} 次循环完成")
# 
            results.append(success)

            if not success:
                print("终止后续循环")
                break

        print("\n🎉 所有循环执行完毕！")
        context.close()
        browser.close()

        # 循环结束后自动发送邮件（可选，根据需求决定是否保留）
        send_result_email(results)

if __name__ == "__main__":
    main()