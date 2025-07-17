import telebot
from telebot import types
import subprocess
import os
import sqlite3
import time
import psutil
import threading
import sys
import re
import requests

# تثبيت مكتبة Gemini
def install_and_import(package):
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package])
install_and_import('google-generativeai')
import google.generativeai as genai

TOKEN = '8122329927:AAHRKHfIB1JsZLGYKGjczYZwO-P55XYxY3c'
ADMIN_ID = 7577607150
AI_API_KEY = 'AIzaSyA5pzOpKVcMGm6Aek82KoB3Pk94dYg3LX4'
DEV_NAME = "بوخابية أحمد"
SUPPORT_CHANNEL = 'https://t.me/djjhvvsjjccs'
MAX_FILES_PER_USER = 10

genai.configure(api_key=AI_API_KEY)
bot = telebot.TeleBot(TOKEN)
user_states = {}
last_activity = {}

# قاعدة البيانات
conn = sqlite3.connect('pyhost.db', check_same_thread=False)
def db_execute(query, params=(), fetch=False):
    cur = conn.cursor()
    cur.execute(query, params)
    res = cur.fetchall() if fetch else None
    conn.commit()
    cur.close()
    return res

db_execute('''CREATE TABLE IF NOT EXISTS bots
             (user_id INTEGER, bot_name TEXT, bot_file TEXT, is_running INTEGER DEFAULT 0)''')
db_execute('''CREATE TABLE IF NOT EXISTS admins
             (user_id INTEGER PRIMARY KEY)''')
db_execute('''CREATE TABLE IF NOT EXISTS banned
             (user_id INTEGER PRIMARY KEY)''')
db_execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY)''')
db_execute('''CREATE TABLE IF NOT EXISTS disabled_buttons
             (button TEXT PRIMARY KEY, is_disabled INTEGER DEFAULT 0)''')
db_execute(f"INSERT OR IGNORE INTO admins (user_id) VALUES ({ADMIN_ID})")
db_execute(f"INSERT OR IGNORE INTO users (user_id) VALUES ({ADMIN_ID})")

if not os.path.exists('uploaded_bots'):
    os.makedirs('uploaded_bots')

# وظائف مساعدة
def is_admin(user_id): return bool(db_execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,), True))
def is_banned(user_id): return bool(db_execute("SELECT 1 FROM banned WHERE user_id=?", (user_id,), True))
def add_bot(user_id, bot_name, bot_file): db_execute("INSERT INTO bots (user_id, bot_name, bot_file) VALUES (?, ?, ?)", (user_id, bot_name, bot_file))
def delete_bot(user_id, bot_name): db_execute("DELETE FROM bots WHERE user_id=? AND bot_name=?", (user_id, bot_name))
def update_bot_status(bot_name, status): db_execute("UPDATE bots SET is_running=? WHERE bot_name=?", (status, bot_name))
def get_user_bots(user_id): return db_execute("SELECT bot_name, is_running FROM bots WHERE user_id=?", (user_id,), True)
def get_bot_file(bot_name): res = db_execute("SELECT bot_file FROM bots WHERE bot_name=?", (bot_name,), True); return res[0][0] if res else None
def get_bot_owner(bot_name): res = db_execute("SELECT user_id FROM bots WHERE bot_name=?", (bot_name,), True); return res[0][0] if res else None
def stop_bot_process(bot_name):
    stopped = False
    for proc in psutil.process_iter():
        try:
            cmdline = proc.cmdline()
            if len(cmdline) >= 2 and cmdline[0].endswith('python3') and bot_name in cmdline[1]:
                proc.kill()
                stopped = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return stopped

def get_stats():
    total_files = db_execute("SELECT COUNT(*) FROM bots", fetch=True)[0][0]
    total_users = db_execute("SELECT COUNT(*) FROM users", fetch=True)[0][0]
    running_files = db_execute("SELECT COUNT(*) FROM bots WHERE is_running=1", fetch=True)[0][0]
    return total_users, total_files, running_files
def get_all_users():
    return [row[0] for row in db_execute("SELECT user_id FROM users", fetch=True) if row[0] != ADMIN_ID]
def get_all_banned():
    return [row[0] for row in db_execute("SELECT user_id FROM banned", fetch=True)]
def ban_user(user_id): db_execute("INSERT OR IGNORE INTO banned (user_id) VALUES (?)", (user_id,))
def unban_user(user_id): db_execute("DELETE FROM banned WHERE user_id=?", (user_id,))
def reset_user_state(user_id): user_states[user_id] = None
def update_last_activity(user_id): last_activity[user_id] = time.time()
def add_user(user_id): db_execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
def check_inactive_users():
    while True:
        now = time.time()
        for user_id in list(last_activity.keys()):
            if now - last_activity[user_id] > 1200:
                reset_user_state(user_id)
                del last_activity[user_id]
        time.sleep(60)
threading.Thread(target=check_inactive_users, daemon=True).start()

# --- الصيانة ---
def set_maintenance(status=True):
    with open("maintenance.txt", "w") as f:
        f.write("on" if status else "off")

def is_maintenance():
    if not os.path.exists("maintenance.txt"):
        return False
    with open("maintenance.txt") as f:
        return f.read().strip() == "on"

def maintenance_block(message_or_call):
    user_id = message_or_call.from_user.id
    if is_maintenance() and not is_admin(user_id):
        chat_id = message_or_call.chat.id if hasattr(message_or_call, "chat") else message_or_call.message.chat.id
        bot.send_message(chat_id, "🚧 البوت في وضع صيانة عد لاحقاً.")
        return True
    return False

# --- تعطيل وتفعيل الأزرار ---
BUTTONS = [
    ("upload_file", "رفع ملف 🗂️"),
    ("my_files", "ملفاتي المرفوعة 📁"),
    ("stop_all", "إيقاف جميع ملفاتي المرفوعة 🔴"),
    ("install_lib", "تثبيت مكتبة 🛠️"),
    ("speed_test", "سرعة البوت ⚡"),
    ("ai_create", "محادثة مع AI 💬"),
    ("about_dev", "المطور 👨‍💻"),
    ("support_channel", "قناة المطور 🛠️"),
    ("code_to_file", "تشغيل كود بايثون 📄"),
    ("show_users", "عرض المستخدمين 👥"),
    ("show_banned", "عرض المحظورين 👤"),
    ("show_stats", "إحصائيات البوت 📊"),
    ("broadcast", "إرسال رسالة جماعية 📬"),
    ("maintenance_on", "تفعيل وضع الصيانة ⏹️"),
    ("maintenance_off", "إيقاف وضع الصيانة ▶️"),
]
def set_button_status(button, status):
    db_execute("INSERT OR REPLACE INTO disabled_buttons (button, is_disabled) VALUES (?, ?)", (button, int(status)))
def is_button_disabled(button):
    res = db_execute("SELECT is_disabled FROM disabled_buttons WHERE button=?", (button,), True)
    return bool(res and res[0][0])

# --- واجهة الأزرار الرئيسية (مطابقة للصورة) ---
def main_menu(is_admin=False):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("رفع ملف 🗂️", callback_data="upload_file"),
        types.InlineKeyboardButton("ملفاتي المرفوعة 📁", callback_data="my_files"),
    )
    markup.add(
        types.InlineKeyboardButton("إيقاف جميع ملفاتي المرفوعة 🔴", callback_data="stop_all"),
    )
    markup.add(
        types.InlineKeyboardButton("تثبيت مكتبة 🛠️", callback_data="install_lib"),
        types.InlineKeyboardButton("سرعة البوت ⚡", callback_data="speed_test"),
    )
    markup.add(
        types.InlineKeyboardButton("محادثة مع AI 💬", callback_data="ai_create"),
        types.InlineKeyboardButton("تشغيل كود بايثون 📄", callback_data="code_to_file"),
    )
    markup.add(
        types.InlineKeyboardButton("قناة المطور 🛠️", url=SUPPORT_CHANNEL),
        types.InlineKeyboardButton("المطور 👨‍💻", callback_data="about_dev"),
    )
    if is_admin:
        markup.add(
            types.InlineKeyboardButton("عرض المستخدمين 👥", callback_data="show_users"),
            types.InlineKeyboardButton("عرض المحظورين 👤", callback_data="show_banned"),
        )
        markup.add(
            types.InlineKeyboardButton("إحصائيات البوت 📊", callback_data="show_stats"),
            types.InlineKeyboardButton("إرسال رسالة جماعية 📬", callback_data="broadcast"),
        )
        markup.add(
            types.InlineKeyboardButton("تفعيل وضع الصيانة ⏹️", callback_data="maintenance_on"),
            types.InlineKeyboardButton("إيقاف وضع الصيانة ▶️", callback_data="maintenance_off"),
        )
        markup.add(
            types.InlineKeyboardButton("⚙️ إدارة الأزرار", callback_data="manage_buttons"),
        )
    return markup

def stop_button(bot_name, bot_username):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("⏹️ إيقاف هذا البوت", callback_data=f"stop_{bot_name}")
    )
    if bot_username and bot_username.startswith("@"):
        markup.add(
            types.InlineKeyboardButton(f"يوزر البوت: {bot_username}", url=f"https://t.me/{bot_username[1:]}")
        )
    return markup

def my_files_markup(files):
    markup = types.InlineKeyboardMarkup()
    for bot_name, is_running in files:
        status = "🟢" if is_running else "🔴"
        markup.add(
            types.InlineKeyboardButton(f"{bot_name} {status}", callback_data=f"show_file_{bot_name}"),
            types.InlineKeyboardButton("🗑 حذف", callback_data=f"delete_{bot_name}")
        )
    return markup

def extract_token_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r"(?i)token\s*=\s*['\"]([0-9]{8,}:[\w-]+)['\"]", content)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None

def get_bot_username(token):
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if data.get("ok"):
            return "@" + data["result"]["username"]
    except Exception:
        pass
    return "غير معروف"

def get_welcome_text():
    return (
        "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        "𝙒𝙀𝙇𝘾𝙊𝙈𝙀 𝙏𝙊 𝙋𝙔𝘽𝙊𝙏 𝙃𝙊𝙎𝙏 ⚡️\n"
        "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n"
        "مرحباً بك في بوت رفع واستضافة بوتات بايثون.\n"
        "يمكنك رفع ملف أو كتابة كود بايثون وتشغيله مباشرة.\n"
        "البوت يدعم الذكاء الاصطناعي.\n\n"
        "المطور: " + DEV_NAME
    )

def dev_footer():
    return "\n\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n𝙳𝙴𝚅: بوخابية أحمد 👨‍💻"

# --- تابع في الجزء الثاني ---
# --- الأوامر الأساسية ---
@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    if maintenance_block(message): return
    add_user(message.from_user.id)
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 تم حظرك من استخدام البوت.")
        return
    reset_user_state(message.from_user.id)
    update_last_activity(message.from_user.id)
    bot.send_message(
        message.chat.id,
        get_welcome_text() + dev_footer(),
        reply_markup=main_menu(is_admin=is_admin(message.from_user.id)),
        parse_mode="Markdown"
    )

# --- رفع ملف بايثون ---
@bot.callback_query_handler(func=lambda call: call.data == "upload_file")
def ask_for_file(call):
    if maintenance_block(call): return
    add_user(call.from_user.id)
    if is_banned(call.from_user.id):
        bot.send_message(call.message.chat.id, "🚫 تم حظرك من استخدام البوت.")
        return
    reset_user_state(call.from_user.id)
    update_last_activity(call.from_user.id)
    bots = get_user_bots(call.from_user.id)
    if len(bots) >= MAX_FILES_PER_USER:
        bot.send_message(call.message.chat.id, f"❌ لا يمكنك رفع أكثر من {MAX_FILES_PER_USER} ملفات. احذف بعض الملفات أولاً.")
        return
    user_states[call.from_user.id] = "awaiting_file"
    bot.send_message(call.message.chat.id, "📤 أرسل ملف بايثون الخاص بك (بامتداد .py)")

@bot.message_handler(content_types=['document'])
def handle_file_upload(message):
    if maintenance_block(message): return
    add_user(message.from_user.id)
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 تم حظرك من استخدام البوت.")
        return
    if user_states.get(message.from_user.id) != "awaiting_file":
        return
    reset_user_state(message.from_user.id)
    update_last_activity(message.from_user.id)
    bots = get_user_bots(message.from_user.id)
    if len(bots) >= MAX_FILES_PER_USER:
        bot.send_message(message.chat.id, f"❌ لا يمكنك رفع أكثر من {MAX_FILES_PER_USER} ملفات. احذف بعض الملفات أولاً.")
        return
    if not message.document or not message.document.file_name.endswith('.py'):
        bot.send_message(message.chat.id, "❌ الملف يجب أن يكون بامتداد .py فقط.")
        return
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    bot_name = message.document.file_name[:-3]
    file_path = f"uploaded_bots/{message.from_user.id}_{bot_name}.py"
    with open(file_path, 'wb') as f:
        f.write(downloaded_file)
    add_bot(message.from_user.id, bot_name, file_path)
    run_user_file(message, bot_name, file_path, message.from_user.id)

# --- تشغيل ملف المستخدم مع عرض يوزر البوت المشغّل ---
def run_user_file(message, bot_name, file_path, owner_id):
    def run_and_notify():
        try:
            process = subprocess.Popen(
                ['python3', file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            chat_id = message.chat.id
            progress_stages = [
                "[░░░░░░░░░░] 0%",
                "[█░░░░░░░░░] 10%",
                "[██░░░░░░░░] 20%",
                "[███░░░░░░░] 30%",
                "[████░░░░░░] 40%",
                "[█████░░░░░] 50%",
                "[██████░░░░] 60%",
                "[███████░░░] 70%",
                "[████████░░] 80%",
                "[█████████░] 90%",
                "[██████████] 100%"
            ]
            progress_msg = bot.send_message(chat_id, f"⏳ جاري تشغيل الملف... {progress_stages[0]}")
            start_time = time.time()
            timeout = 3
            current_progress_stage_index = 0
            error_lines = []
            while True:
                if process.poll() is not None:
                    break
                from select import select
                rlist, _, _ = select([process.stderr], [], [], 0.1)
                for fd in rlist:
                    line = fd.readline().strip()
                    if line:
                        error_lines.append(line)
                elapsed = time.time() - start_time
                progress_percent = (elapsed / timeout) * 100
                new_progress_stage_index = min(int(progress_percent / 10), len(progress_stages) - 1)
                if new_progress_stage_index > current_progress_stage_index:
                    current_progress_stage_index = new_progress_stage_index
                    try:
                        bot.edit_message_text(f"⏳ جاري تشغيل الملف... {progress_stages[current_progress_stage_index]}", chat_id, progress_msg.message_id)
                    except: pass
                if elapsed >= timeout:
                    break
                time.sleep(0.1)
            if error_lines:
                update_bot_status(bot_name, 0)
                bot.edit_message_text(
                    f"⚠️ <b>فشل تشغيل الملف:</b> <code>{bot_name}</code>\n<pre>{error_lines[0]}</pre>", chat_id, progress_msg.message_id, parse_mode="HTML"
                )
                return
            if process.poll() is None:
                update_bot_status(bot_name, 1)
                bot_token = extract_token_from_file(file_path)
                bot_username = get_bot_username(bot_token) if bot_token else "غير معروف"
                msg = (
                    f"🎉 <b>تم تشغيل بوتك بنجاح!</b> 🎉\n\n"
                    f"📝 <b>اسم الملف:</b> <code>{bot_name}</code>\n"
                    f"👤 <b>معرّف المشغل:</b> <code>{owner_id}</code>\n"
                    f"🤖 <b>يوزر البوت:</b> {bot_username}\n\n"
                    "يمكنك إيقاف البوت من هنا 👇"
                )
                reply_markup = stop_button(bot_name, bot_username)
                bot.edit_message_text(msg, chat_id, progress_msg.message_id, parse_mode="HTML", reply_markup=reply_markup)
            else:
                update_bot_status(bot_name, 0)
                bot.edit_message_text(
                    f"❌ <b>الملف توقف فوراً بعد التشغيل وربما يحتوي على خطأ.</b>",
                    chat_id,
                    progress_msg.message_id,
                    parse_mode="HTML"
                )
        except Exception as e:
            bot.send_message(message.chat.id, f"⚠️ <b>حدث خطأ غير متوقع أثناء معالجة ملفك {bot_name}.py:</b>\n<code>{str(e)}</code>", parse_mode="HTML")
            update_bot_status(bot_name, 0)
    threading.Thread(target=run_and_notify).start()

# --- زر "تشغيل كود بايثون" لأي مستخدم ---
@bot.callback_query_handler(func=lambda call: call.data == "code_to_file")
def ask_code_filename(call):
    if maintenance_block(call): return
    add_user(call.from_user.id)
    if is_banned(call.from_user.id):
        bot.send_message(call.message.chat.id, "🚫 تم حظرك من استخدام البوت.")
        return
    reset_user_state(call.from_user.id)
    update_last_activity(call.from_user.id)
    bots = get_user_bots(call.from_user.id)
    if len(bots) >= MAX_FILES_PER_USER:
        bot.send_message(call.message.chat.id, f"❌ لا يمكنك رفع أكثر من {MAX_FILES_PER_USER} ملفات. احذف بعض الملفات أولاً.")
        return
    user_states[call.from_user.id] = "awaiting_code_filename"
    bot.send_message(call.message.chat.id, "📝 أدخل اسم الملف (بدون .py):")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "awaiting_code_filename")
def ask_code_content(message):
    reset_user_state(message.from_user.id)
    update_last_activity(message.from_user.id)
    user_states[message.from_user.id] = ("awaiting_code_content", message.text.strip())
    bot.send_message(message.chat.id, "✍️ أرسل كود البايثون:")

@bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), tuple) and user_states.get(m.from_user.id)[0] == "awaiting_code_content")
def handle_code_content(message):
    state = user_states.get(message.from_user.id)
    file_base = state[1]
    code = message.text
    reset_user_state(message.from_user.id)
    update_last_activity(message.from_user.id)
    file_path = f"uploaded_bots/{message.from_user.id}_{file_base}.py"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(code)
    add_bot(message.from_user.id, file_base, file_path)
    run_user_file(message, file_base, file_path, message.from_user.id)

# --- بقية الأزرار (مطابقة للكود السابق) ---
@bot.callback_query_handler(func=lambda call: call.data == "my_files")
def show_my_files(call):
    if maintenance_block(call): return
    add_user(call.from_user.id)
    if is_banned(call.from_user.id):
        bot.send_message(call.message.chat.id, "🚫 تم حظرك من استخدام البوت.")
        return
    reset_user_state(call.from_user.id)
    update_last_activity(call.from_user.id)
    bots = get_user_bots(call.from_user.id)
    if not bots:
        bot.send_message(call.message.chat.id, "❌ لا يوجد ملفات مرفوعة لديك.")
        return
    bot.send_message(call.message.chat.id, "📁 <b>ملفاتك المرفوعة:</b>", parse_mode="HTML", reply_markup=my_files_markup(bots))

@bot.callback_query_handler(func=lambda call: call.data.startswith("show_file_"))
def show_file_options(call):
    if maintenance_block(call): return
    bot_name = call.data.split("_", 2)[2]
    file_path = get_bot_file(bot_name)
    bot_token = extract_token_from_file(file_path)
    bot_username = get_bot_username(bot_token) if bot_token else "غير معروف"
    if not file_path:
        bot.send_message(call.message.chat.id, "❌ الملف غير موجود.")
        return
    bot.send_message(call.message.chat.id, f"📝 <b>اسم الملف:</b> <code>{bot_name}</code>\n📂 <b>المسار:</b> <code>{file_path}</code>", parse_mode="HTML", reply_markup=stop_button(bot_name, bot_username))

@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_"))
def delete_user_file(call):
    if maintenance_block(call): return
    bot_name = call.data.split("_", 1)[1]
    file_path = get_bot_file(bot_name)
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
        stop_bot_process(bot_name)
    delete_bot(call.from_user.id, bot_name)
    bot.send_message(call.message.chat.id, f"🗑 <b>تم حذف الملف</b> <code>{bot_name}</code> <b>بنجاح.</b>", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("stop_"))
def stop_file(call):
    bot_name = call.data.split("_", 1)[1]
    stopped = stop_bot_process(bot_name)
    update_bot_status(bot_name, 0)
    if stopped:
        bot.send_message(call.message.chat.id, f"⏹️ <b>تم إيقاف الملف</b> <code>{bot_name}</code>", parse_mode="HTML")
    else:
        bot.send_message(call.message.chat.id, f"⚠️ <b>لم يتم العثور على عملية الملف أو هي متوقفة أصلاً.</b>", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "stop_all")
def stop_all_bots(call):
    if maintenance_block(call): return
    add_user(call.from_user.id)
    if is_banned(call.from_user.id):
        bot.send_message(call.message.chat.id, "🚫 تم حظرك من استخدام البوت.")
        return
    reset_user_state(call.from_user.id)
    update_last_activity(call.from_user.id)
    bots = get_user_bots(call.from_user.id)
    count = 0
    for bot_name, is_running in bots:
        if is_running:
            stop_bot_process(bot_name)
            update_bot_status(bot_name, 0)
            count += 1
    bot.send_message(call.message.chat.id, f"🛑 <b>تم إيقاف {count} ملف/ملفات.</b>", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "install_lib")
def ask_lib_name(call):
    if maintenance_block(call): return
    add_user(call.from_user.id)
    if is_banned(call.from_user.id):
        bot.send_message(call.message.chat.id, "🚫 تم حظرك من استخدام البوت.")
        return
    reset_user_state(call.from_user.id)
    update_last_activity(call.from_user.id)
    user_states[call.from_user.id] = "awaiting_lib"
    bot.send_message(call.message.chat.id, "🛠️ أرسل اسم مكتبة بايثون التي تريد تثبيتها:")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "awaiting_lib")
def install_library(message):
    if maintenance_block(message): return
    reset_user_state(message.from_user.id)
    update_last_activity(message.from_user.id)
    lib = message.text.strip()
    bot.send_message(message.chat.id, "⏳ جاري تثبيت المكتبة...")
    try:
        process = subprocess.run(['pip3', 'install', lib], capture_output=True, text=True, check=True)
        bot.send_message(message.chat.id, f"✅ <b>تم تثبيت المكتبة:</b> <code>{lib}</code>\n<pre>{process.stdout}</pre>", parse_mode="HTML")
    except subprocess.CalledProcessError as e:
        bot.send_message(message.chat.id, f"❌ <b>خطأ أثناء التثبيت:</b> <code>{e.stderr}</code>", parse_mode="HTML")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ <b>خطأ غير متوقع أثناء التثبيت:</b> <code>{e}</code>", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "speed_test")
def speed_test(call):
    if maintenance_block(call): return
    reset_user_state(call.from_user.id)
    update_last_activity(call.from_user.id)
    start = time.time()
    msg = bot.send_message(call.message.chat.id, "⏳ جاري اختبار سرعة البوت...")
    elapsed = round((time.time() - start) * 1000)
    bot.edit_message_text(f"⚡ <b>سرعة الاستجابة:</b> <code>{elapsed}</code> مللي ثانية", call.message.chat.id, msg.message_id, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "ai_create")
def ai_intro(call):
    if maintenance_block(call): return
    reset_user_state(call.from_user.id)
    update_last_activity(call.from_user.id)
    user_states[call.from_user.id] = "awaiting_ai"
    bot.send_message(call.message.chat.id, "🤖 أرسل وصف الملف البرمجي أو سؤالك للذكاء الاصطناعي:")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "awaiting_ai")
def ai_response(message):
    if maintenance_block(message): return
    reset_user_state(message.from_user.id)
    update_last_activity(message.from_user.id)
    user_input = message.text
    try:
        model = genai.GenerativeModel('gemini-1.0-pro')
        response = model.generate_content(user_input)
        ai_reply = response.text
        bot.send_message(message.chat.id, ai_reply)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ حدث خطأ أثناء الاتصال بـ Gemini:\n{e}")

@bot.callback_query_handler(func=lambda call: call.data == "about_dev")
def about_dev(call):
    bot.send_message(call.message.chat.id, f"👨‍💻 <b>المطور:</b> بوخابية أحمد\nطالب ثانوي جزائري، صانع هذا البوت.\nللتواصل: @Ahmed_bou_2008\nقناة الدعم: {SUPPORT_CHANNEL}", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "maintenance_on")
def maintenance_on(call):
    if not is_admin(call.from_user.id): return
    set_maintenance(True)
    bot.send_message(call.message.chat.id, "✅ تم تفعيل وضع الصيانة. لن يتمكن المستخدمون من استخدام البوت.")

@bot.callback_query_handler(func=lambda call: call.data == "maintenance_off")
def maintenance_off(call):
    if not is_admin(call.from_user.id): return
    set_maintenance(False)
    bot.send_message(call.message.chat.id, "✅ تم إيقاف وضع الصيانة. البوت متاح الآن للجميع.")

@bot.callback_query_handler(func=lambda call: call.data == "show_stats")
def show_stats(call):
    if maintenance_block(call): return
    if not is_admin(call.from_user.id): return
    users, files, running = get_stats()
    stats_text = (
        "📊 <b>إحصائيات البوت:</b>\n\n"
        f"- عدد المستخدمين: <code>{users}</code>\n"
        f"- عدد الملفات المرفوعة: <code>{files}</code>\n"
        f"- عدد الملفات المشغلة الآن: <code>{running}</code>\n"
    )
    bot.send_message(call.message.chat.id, stats_text, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "show_users")
def show_users(call):
    if maintenance_block(call): return
    if not is_admin(call.from_user.id): return
    users = get_all_users()
    if not users:
        bot.send_message(call.message.chat.id, "لا يوجد مستخدمين.")
        return
    markup = types.InlineKeyboardMarkup()
    for uid in users:
        try:
            user_info = bot.get_chat(uid)
            name = user_info.username or user_info.first_name or "بدون اسم"
        except:
            name = "غير متاح"
        markup.add(
            types.InlineKeyboardButton(f"👤 {name} | {uid}", callback_data=f"ban_user_{uid}")
        )
    bot.send_message(call.message.chat.id, "اضغط على أي مستخدم لحظره:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ban_user_"))
def ban_user_callback(call):
    if maintenance_block(call): return
    if not is_admin(call.from_user.id): return
    uid = int(call.data.split("_")[2])
    ban_user(uid)
    bot.send_message(call.message.chat.id, f"🚫 تم حظر المستخدم {uid}.")

@bot.callback_query_handler(func=lambda call: call.data == "show_banned")
def show_banned(call):
    if not is_admin(call.from_user.id): return
    banned = get_all_banned()
    if not banned:
        bot.send_message(call.message.chat.id, "لا يوجد مستخدمين محظورين.")
        return
    markup = types.InlineKeyboardMarkup()
    for uid in banned:
        try:
            user_info = bot.get_chat(uid)
            name = user_info.username or user_info.first_name or "بدون اسم"
        except:
            name = "غير متاح"
        markup.add(
            types.InlineKeyboardButton(f"👤 {name} | {uid}", callback_data=f"unban_user_{uid}")
        )
    bot.send_message(call.message.chat.id, "اضغط على أي مستخدم لإلغاء الحظر:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("unban_user_"))
def unban_user_callback(call):
    if not is_admin(call.from_user.id): return
    uid = int(call.data.split("_")[2])
    unban_user(uid)
    bot.send_message(call.message.chat.id, f"✅ تم إلغاء الحظر عن المستخدم {uid}.")

@bot.callback_query_handler(func=lambda call: call.data == "broadcast")
def ask_broadcast(call):
    if maintenance_block(call): return
    if not is_admin(call.from_user.id): return
    user_states[call.from_user.id] = "awaiting_broadcast"
    bot.send_message(call.message.chat.id, "✉️ أرسل الرسالة التي تريد إذاعتها:")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "awaiting_broadcast")
def do_broadcast(message):
    if maintenance_block(message): return
    reset_user_state(message.from_user.id)
    update_last_activity(message.from_user.id)
    users = get_all_users()
    count = 0
    for uid in users:
        try:
            bot.send_message(uid, f"📢 رسالة من المطور:\n\n{message.text}")
            count += 1
        except Exception as e:
            continue
    bot.send_message(message.chat.id, f"✅ تم إرسال الرسالة إلى {count} مستخدم.")

@bot.callback_query_handler(func=lambda call: call.data == "manage_buttons")
def manage_buttons(call):
    if not is_admin(call.from_user.id): return
    markup = types.InlineKeyboardMarkup()
    for btn, label in BUTTONS:
        status = "❌" if is_button_disabled(btn) else "✅"
        markup.add(types.InlineKeyboardButton(f"{label} {status}", callback_data=f"togglebtn_{btn}"))
    bot.send_message(call.message.chat.id, "إدارة الأزرار (اضغط للتفعيل/التعطيل):", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("togglebtn_"))
def toggle_button(call):
    if not is_admin(call.from_user.id): return
    btn = call.data.split("_", 1)[1]
    cur_status = is_button_disabled(btn)
    set_button_status(btn, not cur_status)
    bot.answer_callback_query(call.id, "تم التغيير.")
    manage_buttons(call)

@bot.message_handler(func=lambda m: True)
def fallback(message):
    if maintenance_block(message): return
    add_user(message.from_user.id)
    if is_banned(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 تم حظرك من استخدام البوت.")
        return
    reset_user_state(message.from_user.id)
    update_last_activity(message.from_user.id)
    bot.send_message(message.chat.id, "استخدم الأزرار للتحكم في البوت." + dev_footer(), parse_mode="HTML")

if __name__ == '__main__':
    print("✅ البوت يعمل الآن...")

while True:
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=10)
    except Exception as e:
        print(f"❌ حدث خطأ: {e}")
        time.sleep(5)

    print("✅ ما زلت حيًا...")  # يبقي Render في حالة نشاط
    time.sleep(30)  # انتظر 30 ثانية قبل إعادة التشغيل

