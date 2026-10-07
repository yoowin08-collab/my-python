import asyncio
import json
import os
import random
import re
import string
import asyncpg
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Environment Variables
TOKEN = os.getenv("BOT_TOKEN", "8617814117:AAGbTDFaabbt2RUuHSPQDqT9S6WZqiNosvM")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7940553702"))
DATABASE_URL = os.getenv("DATABASE_URL")

TEAMS = [
    {"name": "Arsenal", "stadium": "Emirates Stadium", "emoji": "🔴"},
    {"name": "Aston Villa", "stadium": "Villa Park", "emoji": "🦁"},
    {"name": "Bournemouth", "stadium": "Vitality Stadium", "emoji": "🍒"},
    {"name": "Brentford", "stadium": "Gtech Community Stadium", "emoji": "🐝"},
    {"name": "Brighton", "stadium": "AMEX Stadium", "emoji": "🕊"},
    {"name": "Chelsea", "stadium": "Stamford Bridge", "emoji": "🔵"},
    {"name": "Crystal Palace", "stadium": "Selhurst Park", "emoji": "🦅"},
    {"name": "Everton", "stadium": "Goodison Park", "emoji": "🔵"},
    {"name": "Fulham", "stadium": "Craven Cottage", "emoji": "⚪"},
    {"name": "Liverpool", "stadium": "Anfield", "emoji": "🔴"},
    {"name": "Manchester City", "stadium": "Etihad Stadium", "emoji": "🩵"},
    {"name": "Manchester United", "stadium": "Old Trafford", "emoji": "👹"},
    {"name": "Newcastle United", "stadium": "St. James' Park", "emoji": "⚫⚪"},
    {"name": "Nottingham Forest", "stadium": "The City Ground", "emoji": "🌳"},
    {"name": "Tottenham Hotspur", "stadium": "Tottenham Hotspur Stadium", "emoji": "⚪"},
    {"name": "West Ham United", "stadium": "London Stadium", "emoji": "⚒️"},
    {"name": "Wolves", "stadium": "Molineux Stadium", "emoji": "🐺"},
    {"name": "Real Madrid", "stadium": "Santiago Bernabéu", "emoji": "👑"},
    {"name": "Barcelona", "stadium": "Camp Nou", "emoji": "🔵🔴"},
    {"name": "Bayern Munich", "stadium": "Allianz Arena", "emoji": "🔴"},
    {"name": "PSG", "stadium": "Parc des Princes", "emoji": "🔵🔴"},
    {"name": "Inter Milan", "stadium": "San Siro", "emoji": "🔵⚫"},
]

# Global Memory Stores
group_msg_count = {}
group_threshold = {}
active_games = {}
last_results = {}
active_cboxes = {}  # Store active Coin Boxes
pending_gifts = {}   # Store pending gifts for confirmation
team_creation_state = {} # Setup memory for team creation {user_id: {"step": str, ...}}
pending_joins = {} # Memory for join requests {msg_id: dict}
game_media = None
result_media = None
global_default_threshold = 10
wait_time_seconds = 600  # Default: 10m
permission_checking_groups = set()

# Database Connection Pool
db_pool = None

async def init_db():
    global db_pool, game_media, result_media, global_default_threshold, wait_time_seconds
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                coins BIGINT DEFAULT 0,
                wins BIGINT DEFAULT 0,
                total_games BIGINT DEFAULT 0,
                selected_card_id TEXT
            );
            CREATE TABLE IF NOT EXISTS groups (
                chat_id BIGINT PRIMARY KEY,
                title TEXT,
                added_by_id BIGINT,
                added_by_name TEXT
            );
            CREATE TABLE IF NOT EXISTS group_members (
                chat_id BIGINT,
                user_id BIGINT,
                PRIMARY KEY (chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS cards (
                card_id TEXT PRIMARY KEY,
                name TEXT,
                type TEXT,
                file_id TEXT
            );
            CREATE TABLE IF NOT EXISTS user_cards (
                user_id BIGINT,
                card_id TEXT,
                amount INT DEFAULT 1,
                PRIMARY KEY (user_id, card_id)
            );
            CREATE TABLE IF NOT EXISTS user_teams (
                team_code TEXT PRIMARY KEY,
                team_name TEXT,
                leader_id BIGINT,
                member_limit INT,
                logo_file_id TEXT,
                logo_type TEXT
            );
            CREATE TABLE IF NOT EXISTS team_members (
                team_code TEXT,
                user_id BIGINT,
                PRIMARY KEY (team_code, user_id)
            );
        """)

        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS selected_card_id TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wins BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_games BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_id BIGINT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_name TEXT;")
            await conn.execute("ALTER TABLE user_cards ADD COLUMN IF NOT EXISTS amount INT DEFAULT 1;")
        except Exception:
            pass

        g_media_row = await conn.fetchrow("SELECT value FROM settings WHERE key='game_media'")
        if g_media_row:
            game_media = json.loads(g_media_row['value'])

        r_media_row = await conn.fetchrow("SELECT value FROM settings WHERE key='result_media'")
        if r_media_row:
            result_media = json.loads(r_media_row['value'])

        thresh_row = await conn.fetchrow("SELECT value FROM settings WHERE key='default_threshold'")
        if thresh_row:
            global_default_threshold = int(thresh_row['value'])

        wait_row = await conn.fetchrow("SELECT value FROM settings WHERE key='wait_time'")
        if wait_row:
            wait_time_seconds = int(wait_row['value'])

async def register_user_group(user, chat):
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        if user and not user.is_bot:
            await conn.execute("""
                INSERT INTO users (user_id, name) VALUES ($1, $2)
                ON CONFLICT(user_id) DO UPDATE SET name = EXCLUDED.name
            """, user.id, user.first_name)
        if chat and chat.type in ["group", "supergroup"]:
            added_id = user.id if user else None
            added_name = user.first_name if user else None
            await conn.execute("""
                INSERT INTO groups (chat_id, title, added_by_id, added_by_name) 
                VALUES ($1, $2, $3, $4)
                ON CONFLICT(chat_id) DO UPDATE SET 
                    title = EXCLUDED.title,
                    added_by_id = COALESCE(groups.added_by_id, EXCLUDED.added_by_id),
                    added_by_name = COALESCE(groups.added_by_name, EXCLUDED.added_by_name)
            """, chat.id, chat.title or "Group", added_id, added_name)

            if user and not user.is_bot:
                await conn.execute("""
                    INSERT INTO group_members (chat_id, user_id) VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                """, chat.id, user.id)

async def add_coins(user_id, amount):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET coins = GREATEST(0, coins + $1) WHERE user_id = $2",
            amount, user_id
        )

def get_mention(user_id, name):
    clean_name = (name or "User").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_id}">{clean_name}</a>'

def generate_team_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def check_bot_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status in ["administrator", "creator"]:
            return True
    except Exception:
        pass
    return False

async def handle_permission_wait(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    if chat_id in permission_checking_groups:
        return
    permission_checking_groups.add(chat_id)

    try:
        msg = await context.bot.send_message(
            chat_id,
            "⚠️ **Bot ကို Admin Permission လေးပေးပေးပါဦး။**\n"
            "ဒါမှ Bot သုံးရတာ အဆင်ပြေမှာပါဗျ။ Permission မပေးထားပါက သတ်မှတ် Wait Time ပြည့်လျှင် Auto ထွက်ပါမည်။",
            parse_mode="Markdown"
        )
    except Exception:
        msg = None

    start_time = asyncio.get_event_loop().time()

    while True:
        await asyncio.sleep(15)
        is_admin = await check_bot_admin(context, chat_id)
        if is_admin:
            try:
                await context.bot.send_message(chat_id, "✅ **Admin Permission ရရှိပါပြီ!** ကျေးဇူးတင်ပါတယ်။ Bot ကို စတင်အလုပ်လုပ်ပါပြီ။", parse_mode="Markdown")
            except Exception:
                pass
            break

        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= wait_time_seconds:
            try:
                await context.bot.send_message(chat_id, "❌ သတ်မှတ်ထားသော Wait Time အတွင်း Admin Permission မရရှိသောကြောင့် Bot Group မှ Auto ထွက်ခွာသွားပါသည်။")
                await context.bot.leave_chat(chat_id)
            except Exception:
                pass
            break

    permission_checking_groups.discard(chat_id)

# Coin Box Command
async def cbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg_id = update.message.message_id

    if user.id != ADMIN_ID:
        return

    if chat.type not in ["group", "supergroup"]:
        return await update.message.reply_text("❌ ဒီ Command ကို Group ထဲမှာပဲ အသုံးပြုနိုင်ပါသည်။", reply_to_message_id=msg_id)

    if not context.args:
        return await update.message.reply_text("❌ အသုံးပြုနည်း: `/cbox [amount]` (ဥပမာ- `/cbox 2000`)", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        total_amount = int(context.args[0])
        if total_amount <= 0:
            return await update.message.reply_text("❌ Amount သည် 0 ထက် ကြီးရပါမည်။", reply_to_message_id=msg_id)
    except ValueError:
        return await update.message.reply_text("❌ Amount ကို ကိန်းဂဏန်းသီးသန့် ရိုက်ထည့်ပါ။", reply_to_message_id=msg_id)

    text = f"""🎁 <b>Kachi Coin Box ကျလာပါပြီ!</b> 🩸

💰 <b>Live Remaining Amount:</b> <code>{total_amount}</code> 🩸
👤 <b>Created By:</b> {get_mention(user.id, user.first_name)}

📋 <b>ခိုးယူသွားသူများ Live List:</b>
<i>မည်သူမျှ မခိုးယူရသေးပါ။</i>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🏴‍☠️ ခိုးရန်", callback_data="claim_cbox")
    ]])

    sent_msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

    active_cboxes[sent_msg.message_id] = {
        "total_amount": total_amount,
        "remaining": total_amount,
        "creator": user.first_name,
        "claimed_users": {},
    }

# Admin Command: Wait Time Set
async def set_wait_time_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global wait_time_seconds
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    full_text = update.message.text.strip()
    match = re.search(r"/wait\s+time\s+(\d+)([mh])", full_text, re.IGNORECASE)

    if not match:
        return await update.message.reply_text("❌ အသုံးပြုနည်း: `/wait time 10m` သို့မဟုတ် `/wait time 1h`", parse_mode="Markdown", reply_to_message_id=msg_id)

    num = int(match.group(1))
    unit = match.group(2).lower()

    if unit == "m":
        sec = num * 60
        unit_str = f"{num} မိနစ်"
    else:
        sec = num * 3600
        unit_str = f"{num} နာရီ"

    wait_time_seconds = sec

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ('wait_time', $1)
            ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
        """, str(sec))

    await update.message.reply_text(f"✅ Bot ကို Admin Permission မပေးထားပါက စောင့်ဆိုင်းမည့် Wait Time ကို **{unit_str}** သို့ ပြောင်းလဲလိုက်ပါပြီ။", parse_mode="Markdown", reply_to_message_id=msg_id)

# /start Command
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    bot_info = await context.bot.get_me()
    text = f"""👋 မင်္ဂလာပါ {get_mention(user.id, user.first_name)} !

🌺 𝙂𝘼𝙈𝙀 𝘽𝙊𝙏 မှ ကြိုဆိုပါတယ်။

📌 <b>ဂိမ်းကစားနည်း</b>
- Bot ကို Group တွင် Add ပါ။
- Group အတွင်း စာစကားပြောရင်း သတ်မှတ်စာကြောင်းပြည့်လျှင် Game ကျလာပါမည်။
- မိမိနှစ်သက်ရာ အသင်း သို့မဟုတ် Draw ကို 1 မိနစ်အတွင်း ရွေးချယ်လောင်းကြေးထပ်နိုင်ပါသည်။

ဆုကြေးများ / 𝙋𝙧𝙞𝙘𝙚
- အသင်းနိုင်လျှင်: 10 🩸Kachi Coin
- Draw နိုင်လျှင်: 30 🩸Kachi Coin

📜 <b>အသုံးပြုနိုင်သော Commands များ:</b>
• /kc - မိမိ Coin နှင့် ကဒ်များ စစ်ဆေးရန်
• /kbox - 300 Coin သုံး၍ Card Box ဖောက်ရန်
• /card [card_id] - Card ပုံ/အချက်အလက်နှင့် Top Owners စစ်ဆေးရန်
• /set [card_id] - /kc တွင် ပြသမည့် Card ပုံကို ပြောင်းရန်

🛡️ <b>Team System အသုံးပြုနည်းများ:</b>
• <b>/team</b> - Team တည်ထောင်ရန် (500 Coin)
• <b>/myteam</b> - မိမိဝင်ထားသော Team Status ကို ကြည့်ရန်
• <b>/join [CODE]</b> - အဖွဲ့ Code ကို သုံး၍ Team ထဲသို့ ဝင်ရောက်ရန် လျှောက်ထားရန်
• <b>/out</b> - လက်ရှိ ဝင်ရောက်ထားသော Team မှ ထွက်ရန် (Member သီးသန့်)
• <b>/out [user_id]</b> - Team Member တစ်ဦးအား အဖွဲ့မှ Kick ထုတ်ရန် (Leader သီးသန့်)
• <b>/dele</b> - မိမိတည်ထောင်ထားသော Team ကို ဖျက်သိမ်းရန် (Leader သီးသန့်)

🎁 <b>/kgift လက်ဆောင်ပေးပို့နည်း (Reply ထောက်၍ သုံးပါ):</b>
• <b>Coin ပေးရန်:</b> ပေးပို့ချင်သူ၏ စာကို Reply ထောက်ပြီး <code>/kgift c100</code> (c နောက်တွင် အကြွေစေ့ပမာဏ ရိုက်ပါ)
• <b>Card ပေးရန်:</b> ပေးပို့ချင်သူ၏ စာကို Reply ထောက်ပြီး <code>/kgift 1201</code> (ကဒ် ID ရိုက်ပါ)"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("➕ Add To Group", url=f"https://t.me/{bot_info.username}?startgroup=true")
    ]])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

# /admin Command
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    text = """⚡ <b>Admin Command List</b>

👑 <b>အသုံးပြုနိုင်သော Admin Commands များ:</b>

1. <b>/game</b> - Game ကို အချိန်မရွေး စတင်ခေါ်ယူရန်
2. <b>/c [count]</b> - Group စာကြောင်းရေ သတ်မှတ်ရန် (DM Only)
3. <b>/cbox [amount]</b> - Group အတွင်း Coin Box (Giveaway) ချပေးရန်
4. <b>/wait time [10m/1h]</b> - Permission စောင့်မည့် Wait Time သတ်မှတ်ရန်
5. <b>/k [user_id] [amount]</b> - User ထံ Coin ထည့်/နှုတ်ရန်
6. <b>/add [card_id].[card_name]</b> - Card အသစ်ထည့်ရန် (Photo/Video ကို Reply လုပ်ပါ)
7. <b>/del [card_id]</b> - Card ဖျက်ရန်
8. <b>/cardlist</b> - ရှိသမျှ Card List များ ကြည့်ရန် (Admin Only)
9. <b>/glist</b> - Bot ရှိနေသော Group များ စာရင်းကြည့်ရန်
10. <b>/g</b> (သို့) <b>/r</b> - Game Media သို့မဟုတ် Result Media သတ်မှတ်ရန်
11. <b>/stats</b> - Bot Statistics စာရင်းကြည့်ရန်
12. <b>/broadcast</b> - Group/User များထံ စာ/မီဒီယာများ Forward ပို့ရန်"""

    await update.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)

# /game Command (Admin Only)
async def manual_game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return
    chat_id = update.effective_chat.id
    if chat_id in active_games:
        return await update.message.reply_text("❌ လက်ရှိ Group တွင် Game ကစားနေဆဲဖြစ်ပါသည်။", reply_to_message_id=msg_id)
    
    asyncio.create_task(start_game(context, chat_id))

# Helper to format Team Card display
async def show_user_team(update_or_context, chat_id, team_code, bot=None, reply_to_msg_id=None):
    async with db_pool.acquire() as conn:
        t_info = await conn.fetchrow("SELECT * FROM user_teams WHERE team_code = $1", team_code)
        if not t_info:
            return

        leader = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", t_info['leader_id'])
        leader_name = leader['name'] if leader else "Leader"

        members = await conn.fetch("""
            SELECT u.user_id, u.name 
            FROM team_members tm
            JOIN users u ON tm.user_id = u.user_id
            WHERE tm.team_code = $1
            ORDER BY u.user_id ASC
        """, team_code)

    member_lines = []
    for m in members:
        member_lines.append(f"⇋ {get_mention(m['user_id'], m['name'])}")

    members_str = "\n".join(member_lines)

    text = f"""TEAM - <b>{t_info['team_name']}</b>
Code
<code>{t_info['team_code']}</code>

 ▱ <i>Leader</i> : {get_mention(t_info['leader_id'], leader_name)}

<i>Team Members</i> ⊞ ({len(members)}/{t_info['member_limit']})

{members_str}"""

    target_bot = bot if bot else (update_or_context.bot if hasattr(update_or_context, 'bot') else None)

    try:
        if t_info['logo_type'] == 'photo':
            if hasattr(update_or_context, 'message') and update_or_context.message:
                await update_or_context.message.reply_photo(t_info['logo_file_id'], caption=text, parse_mode="HTML", reply_to_message_id=reply_to_msg_id)
            elif target_bot:
                await target_bot.send_photo(chat_id, t_info['logo_file_id'], caption=text, parse_mode="HTML", reply_to_message_id=reply_to_msg_id)
        else:
            if hasattr(update_or_context, 'message') and update_or_context.message:
                await update_or_context.message.reply_video(t_info['logo_file_id'], caption=text, parse_mode="HTML", reply_to_message_id=reply_to_msg_id)
            elif target_bot:
                await target_bot.send_video(chat_id, t_info['logo_file_id'], caption=text, parse_mode="HTML", reply_to_message_id=reply_to_msg_id)
    except Exception:
        try:
            if hasattr(update_or_context, 'message') and update_or_context.message:
                await update_or_context.message.reply_text(text, parse_mode="HTML", reply_to_message_id=reply_to_msg_id)
            elif target_bot:
                await target_bot.send_message(chat_id, text, parse_mode="HTML", reply_to_message_id=reply_to_msg_id)
        except Exception:
            pass

# /team Command Implementation
async def team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        user_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)

    if user_team:
        await update.message.reply_text("❌ သင် Team သို့ ဝင်ရောက်ထားပြီး ဖြစ်ပါသည်။ အဖွဲ့အချက်အလက်များကို ကြည့်ရန် `/myteam` ဟု ရိုက်ပါ။", parse_mode="Markdown", reply_to_message_id=msg_id)
    else:
        text = "ကဲ အခုပဲ Legendary Team တစ်ခုတည်ထောင်ပြီး Top 1 ယူပြီး 𝗚𝗲𝗺𝗦𝘁𝗼𝗻𝗲🗽 ကိုရယူကြစို့ (ကုန်ကျစရိတ်: 500 Coin)"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Team ထောင်ရန်", callback_data=f"create_team_{user.id}")
        ]])
        await update.message.reply_text(text, reply_markup=keyboard, reply_to_message_id=msg_id)

# /myteam Command Implementation
async def myteam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        user_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)

    if user_team:
        await show_user_team(update, chat.id, user_team['team_code'], reply_to_msg_id=msg_id)
    else:
        await update.message.reply_text("❌ သင် မည်သည့် Team တွင်မျှ ဝင်ရောက်ထားခြင်း မရှိသေးပါ။ (/team ဖြင့် တည်ထောင်ပါ)", reply_to_message_id=msg_id)

# /dele Command (Delete Team - Leader Only)
async def delete_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        team = await conn.fetchrow("SELECT team_code, team_name FROM user_teams WHERE leader_id = $1", user.id)
        if not team:
            return await update.message.reply_text("❌ သင်သည် တည်ထောင်ထားသော Team Leader မဟုတ်ပါ သို့မဟုတ် Team မရှိပါ။", reply_to_message_id=msg_id)

        team_code = team['team_code']
        team_name = team['team_name']

        # Delete team members and team
        await conn.execute("DELETE FROM team_members WHERE team_code = $1", team_code)
        await conn.execute("DELETE FROM user_teams WHERE team_code = $1", team_code)

    await update.message.reply_text(f"✅ သင့်၏ Team <b>{team_name}</b> ကို အောင်မြင်စွာ ဖျက်သိမ်းလိုက်ပါပြီ။ အဖွဲ့ဝင်များလည်း အဖွဲ့မှ ထွက်ရှိသွားပါပြီ။", parse_mode="HTML", reply_to_message_id=msg_id)

# /join [CODE] Command
async def join_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    if not context.args:
        return await update.message.reply_text("❌ အသုံးပြုနည်း: `/join [TEAM_CODE]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_code = context.args[0].strip().upper()

    async with db_pool.acquire() as conn:
        already_in = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)
        if already_in:
            return await update.message.reply_text("❌ သင် အဖွဲ့တစ်ခုတွင် ဝင်ရောက်ပြီးသား ဖြစ်ပါသည်။ အခြား အဖွဲ့သို့ ပြောင်းရန် အရင် Team မှ ထွက်ပါ (/out)။", reply_to_message_id=msg_id)

        team = await conn.fetchrow("SELECT * FROM user_teams WHERE team_code = $1", target_code)
        if not team:
            return await update.message.reply_text("❌ အဖွဲ့ Code မှားယွင်းနေပါသည်။ သေချာစွာ ပြန်လည်စစ်ဆေးပါ။", reply_to_message_id=msg_id)

        current_count = await conn.fetchval("SELECT COUNT(*) FROM team_members WHERE team_code = $1", target_code)
        if current_count >= team['member_limit']:
            return await update.message.reply_text("❌ အဆိုပါ Team တွင် Member Limit အပြည့် ရောက်ရှိနေပါပြီ။", reply_to_message_id=msg_id)

    # Send Join Request to Leader's DM
    leader_id = team['leader_id']
    req_text = f"""📩 <b>Team Join Request!</b>

{get_mention(user.id, user.first_name)} မှ သင့်အဖွဲ့ <b>{team['team_name']}</b> (Code: <code>{target_code}</code>) သို့ ဝင်ရောက်ရန် လျှောက်ထားလာပါသည်။

လက်ခံမည်လား?"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data=f"joinapp_no_{user.id}_{target_code}"),
        InlineKeyboardButton("Confirm ✅", callback_data=f"joinapp_yes_{user.id}_{target_code}")
    ]])

    try:
        sent = await context.bot.send_message(leader_id, req_text, parse_mode="HTML", reply_markup=keyboard)
        pending_joins[sent.message_id] = {
            "applicant_id": user.id,
            "applicant_name": user.first_name,
            "team_code": target_code
        }
        await update.message.reply_text("✅ Team Leader ထံသို့ ဝင်ရောက်ရန် လျှောက်ထားချက် ပို့ဆောင်လိုက်ပါပြီ! Leader အတည်ပြုတာကို စောင့်ဆိုင်းပေးပါ။", reply_to_message_id=msg_id)
    except Exception:
        await update.message.reply_text("❌ Team Leader ၏ DM သို့ သတင်းအချက်အလက် ပို့ရန် မအောင်မြင်ပါ။ Leader မှ Bot ကို /start မလုပ်ထားပါ သို့မဟုတ် Block ထားပါသည်။", reply_to_message_id=msg_id)

# /out Command
async def out_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        in_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)
        if not in_team:
            return await update.message.reply_text("❌ သင် မည်သည့် Team တွင်မျှ မရှိသေးပါ။", reply_to_message_id=msg_id)

        team_code = in_team['team_code']
        team = await conn.fetchrow("SELECT leader_id, team_name FROM user_teams WHERE team_code = $1", team_code)

        # Leader kick out command (/out [user_id])
        if context.args and user.id == team['leader_id']:
            try:
                target_kick_id = int(context.args[0])
                if target_kick_id == user.id:
                    return await update.message.reply_text("❌ မိမိကိုယ်ကို Kick ထုတ်၍ မရပါ။ Team ဖျက်လိုပါက `/dele` ဟု ရိုက်ပါ။", parse_mode="Markdown", reply_to_message_id=msg_id)

                is_member = await conn.fetchrow("SELECT user_id FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, target_kick_id)
                if not is_member:
                    return await update.message.reply_text("❌ အဆိုပါ အသုံးပြုသူသည် သင့် Team ထဲတွင် မရှိပါ။", reply_to_message_id=msg_id)

                await conn.execute("DELETE FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, target_kick_id)
                return await update.message.reply_text(f"✅ User ID <code>{target_kick_id}</code> ကို သင့် Team ထဲမှ Kick ထုတ်လိုက်ပါပြီ။", parse_mode="HTML", reply_to_message_id=msg_id)
            except ValueError:
                return await update.message.reply_text("❌ Kick ထုတ်ရန် User ID ကို ကိန်းဂဏန်းဖြင့် ရိုက်ထည့်ပါ။", reply_to_message_id=msg_id)

        # Normal member leave team (/out)
        if user.id == team['leader_id']:
            return await update.message.reply_text("❌ သင်သည် Team Leader ဖြစ်သောကြောင့် အဖွဲ့မှ ထွက်၍ မရပါ။ (Team ကို အပြီးဖျက်လိုပါက `/dele` ဟု သုံးပါ)", reply_to_message_id=msg_id)

        await conn.execute("DELETE FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, user.id)

    await update.message.reply_text(f"✅ သင်သည် <b>{team['team_name']}</b> Team မှ အောင်မြင်စွာ ထွက်ခွာလိုက်ပါပြီ။", parse_mode="HTML", reply_to_message_id=msg_id)

# /c Command
async def set_count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global global_default_threshold
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return
    if update.effective_chat.type != "private":
        return await update.message.reply_text("❌ ဒီ Command ကို Bot DM မွာပဲ သံုးလို့ရပါမယ္။", reply_to_message_id=msg_id)

    try:
        count = int(context.args[0])
        global_default_threshold = count

        async with db_pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id FROM groups")
            await conn.execute("""
                INSERT INTO settings (key, value) VALUES ('default_threshold', $1)
                ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
            """, str(count))

        for g in groups:
            group_threshold[g['chat_id']] = count

        await update.message.reply_text(
            f"✅ Group များအားလုံးအတွက် စာကြောင်းရေ **{count}** ကြောင်းပြည့်လျှင် Game ကျရန် သတ်မှတ်လိုက်ပါပြီ။",
            parse_mode="Markdown",
            reply_to_message_id=msg_id
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ အသုံးပြုနည်း: `/c 6`", parse_mode="Markdown", reply_to_message_id=msg_id)

# Admin Coin Give/Take
async def admin_coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])

        async with db_pool.acquire() as conn:
            user_exists = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
            if not user_exists:
                await conn.execute("INSERT INTO users (user_id, name, coins) VALUES ($1, $2, 0)", target_id, "User")
            
            await conn.execute("UPDATE users SET coins = GREATEST(0, coins + $1) WHERE user_id = $2", amount, target_id)
            new_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1", target_id)

        status_text = "တိုးပေးလိုက်ပါပြီ" if amount >= 0 else "နှုတ်လိုက်ပါပြီ"
        await update.message.reply_text(
            f"✅ {get_mention(target_id, new_row['name'])} ထံသို့ Kachi Coin <b>{abs(amount)}</b> {status_text}။\n"
            f"💰 လက်ရှိ Coin: <b>{new_row['coins']}</b>",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ အသုံးပြုနည်း: `/k 1928382 200` သို့မဟုတ် `/k 1928382 -200`", parse_mode="Markdown", reply_to_message_id=msg_id)

# /add Command
async def add_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    reply = update.message.reply_to_message
    if not reply or (not reply.photo and not reply.video):
        return await update.message.reply_text("❌ ပုံ သို့မဟုတ် Video ကို Reply ထောက်ပြီး `/add [card_id].[card_name]` ဟု ရိုက်ပါ။", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        full_text = update.message.text
        raw_args = full_text.partition(" ")[2].strip()

        if "." not in raw_args:
            return await update.message.reply_text("❌ အသုံးပြုနည်း: Reply ထောက်ပြီး `/add [card_id].[card_name]` ဟု ရိုက်ပါ", parse_mode="Markdown", reply_to_message_id=msg_id)
        
        card_id, _, card_name = raw_args.partition(".")
        card_id = card_id.strip()
        card_name = card_name.strip()

        if not card_id or not card_name:
            return await update.message.reply_text("❌ Card ID သို့မဟုတ် Card Name မှားယွင်းနေပါသည်။", parse_mode="Markdown", reply_to_message_id=msg_id)

        if reply.photo:
            file_id = reply.photo[-1].file_id
            c_type = "photo"
        else:
            file_id = reply.video.file_id
            c_type = "video"

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO cards (card_id, name, type, file_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (card_id) DO UPDATE SET name = EXCLUDED.name, type = EXCLUDED.type, file_id = EXCLUDED.file_id
            """, card_id, card_name, c_type, file_id)

        await update.message.reply_text(f"✅ Card အသစ်ထည့်သွင်းပြီးပါပြီ!\n\n🆔 Card ID: <code>{card_id}</code>\n🎴 Card Name: {card_name}", parse_mode="HTML", reply_to_message_id=msg_id)
    except Exception as e:
        await update.message.reply_text(f"❌ ထည့်သွင်းရာတွင် အမှားအယွင်းရှိပါသည်: {e}", reply_to_message_id=msg_id)

# /del Command
async def del_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        return await update.message.reply_text("❌ အသုံးပြုနည်း: `/del [card_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_card_id = context.args[0].strip()

    async with db_pool.acquire() as conn:
        card = await conn.fetchrow("SELECT name FROM cards WHERE card_id = $1", target_card_id)
        if not card:
            return await update.message.reply_text(f"❌ Card ID <code>{target_card_id}</code> မရှိပါ သို့မဟုတ် ဖျက်ပြီးသားဖြစ်ပါသည်။", parse_mode="HTML", reply_to_message_id=msg_id)

        await conn.execute("DELETE FROM user_cards WHERE card_id = $1", target_card_id)
        await conn.execute("DELETE FROM cards WHERE card_id = $1", target_card_id)
        await conn.execute("UPDATE users SET selected_card_id = NULL WHERE selected_card_id = $1", target_card_id)

    await update.message.reply_text(f"✅ Card ID <code>{target_card_id}</code> (<b>{card['name']}</b>) ကို စနစ်နှင့် User များဆီမှ အပြီးတိုင် ဖျက်လိုက်ပါပြီ။", parse_mode="HTML", reply_to_message_id=msg_id)

# /set Command
async def set_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    if not context.args:
        return await update.message.reply_text("❌ အသုံးပြုနည်း: `/set [Card_ID]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_card_id = context.args[0]

    async with db_pool.acquire() as conn:
        has_card = await conn.fetchrow("""
            SELECT c.name FROM user_cards uc
            JOIN cards c ON uc.card_id = c.card_id
            WHERE uc.user_id = $1 AND uc.card_id = $2
        """, user.id, target_card_id)

        if not has_card:
            return await update.message.reply_text(f"❌ သင့်ထံတွင် Card ID <code>{target_card_id}</code> မရှိပါ။", parse_mode="HTML", reply_to_message_id=msg_id)

        await conn.execute("UPDATE users SET selected_card_id = $1 WHERE user_id = $2", target_card_id, user.id)

    await update.message.reply_text(f"✅ /kc တွင် ပြသမည့် Card ကို <b>{has_card['name']}</b> သို့ ပြောင်းလဲလိုက်ပါပြီ။", parse_mode="HTML", reply_to_message_id=msg_id)

# /kbox Command
async def kbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
        coins = row['coins'] if row else 0

    if coins < 300:
        return await update.message.reply_text(
            f"❌ မင်္ဂလာပါ {get_mention(user.id, user.first_name)}၊ Box လှည့်ရန် Kachi Coin 300 လိုအပ်ပါသည်။\nသင့်ထံတွင် {coins} Coin သာရှိပါသည်။",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )

    text = f"{get_mention(user.id, user.first_name)} Box ဖောက်နေပါပြီ၊ ဘယ်ဟာလေး ကံကောင်းသွားမလဲ မစောင့်နိုင်တော့ဘူး..."
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎰 စလှည့်ရန်", callback_data=f"spin_{user.id}")
    ]])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=msg_id
    )

# /kgift Command Implementation
async def kgift_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    reply_msg = update.message.reply_to_message

    if not reply_msg or not reply_msg.from_user or reply_msg.from_user.is_bot:
        return await update.message.reply_text("❌ လက်ဆောင်ပေးလိုသည့် အသုံးပြုသူ၏ Message ကို Reply ထောက်၍ သုံးပါ။", reply_to_message_id=msg_id)

    receiver = reply_msg.from_user
    if sender.id == receiver.id:
        return await update.message.reply_text("❌ မိမိကိုယ်ကို လက်ဆောင်ပြန်ပေး၍ မရပါ။", reply_to_message_id=msg_id)

    await register_user_group(sender, chat)
    await register_user_group(receiver, chat)

    if not context.args:
        return await update.message.reply_text("❌ အသုံးပြုနည်း:\n• Card ပေးရန်: Reply ထောက်၍ `/kgift [card_id]`\n• Coin ပေးရန်: Reply ထောက်၍ `/kgift c[amount]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    arg = context.args[0].strip()

    # Case 1: Coin Gift (e.g. /kgift c200)
    if arg.lower().startswith("c") and arg[1:].isdigit():
        amount = int(arg[1:])
        if amount <= 0:
            return await update.message.reply_text("❌ Kachi Coin ပမာဏသည် 0 ထက် ကြီးရပါမည်။", reply_to_message_id=msg_id)

        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", sender.id)
            sender_coins = user_row['coins'] if user_row else 0

        if sender_coins < amount:
            return await update.message.reply_text(f"❌ သင့်ထံတွင် Kachi Coin {amount} မလုံလောက်ပါ။ (လက်ရှိ: {sender_coins} 🩸)", reply_to_message_id=msg_id)

        text = f"""🎁 <b>Kachi Coin Gift Transfer</b>

👤 <b>ပေးပို့သူ:</b> {get_mention(sender.id, sender.first_name)}
👤 <b>လက်ခံမည့်သူ:</b> {get_mention(receiver.id, receiver.first_name)}
💰 <b>လက်ဆောင် Coin ပမာဏ:</b> <b>{amount}</b> 🩸 Kachi Coin

<i>လက်ဆောင်ပေးပို့ခြင်းကို အတည်ပြုရန် အောက်ပါ Gift ခလုတ်ကို နှိပ်ပါ။</i>"""

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data=f"gift_cancel_{sender.id}"),
            InlineKeyboardButton("🎁 Gift", callback_data=f"gift_confirm_{sender.id}")
        ]])

        sent_msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        pending_gifts[sent_msg.message_id] = {
            "type": "coin",
            "sender_id": sender.id,
            "receiver_id": receiver.id,
            "receiver_name": receiver.first_name,
            "amount": amount
        }

    # Case 2: Card Gift (e.g. /kgift 1263)
    else:
        card_id = arg
        async with db_pool.acquire() as conn:
            card = await conn.fetchrow("SELECT card_id, name, type, file_id FROM cards WHERE card_id = $1", card_id)
            if not card:
                return await update.message.reply_text(f"❌ Card ID <code>{card_id}</code> မရှိပါ။", parse_mode="HTML", reply_to_message_id=msg_id)

            user_card = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", sender.id, card_id)
            if not user_card or user_card['amount'] <= 0:
                return await update.message.reply_text(f"❌ သင့်ထံတွင် Card ID <code>{card_id}</code> (<b>{card['name']}</b>) မရှိပါ။", parse_mode="HTML", reply_to_message_id=msg_id)

        text = f"""🎁 <b>Kachi Card Gift Transfer</b>

👤 <b>ပေးပို့သူ:</b> {get_mention(sender.id, sender.first_name)}
👤 <b>လက်ခံမည့်သူ:</b> {get_mention(receiver.id, receiver.first_name)}

🎴 <b>Card အချက်အလက်:</b>
🏷️ <b>Name:</b> {card['name']}
🆔 <b>Card ID:</b> <code>{card['card_id']}</code>

<i>လက်ဆောင်ပေးပို့ခြင်းကို အတည်ပြုရန် အောက်ပါ Gift ခလုတ်ကို နှိပ်ပါ။</i>"""

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data=f"gift_cancel_{sender.id}"),
            InlineKeyboardButton("🎁 Gift", callback_data=f"gift_confirm_{sender.id}")
        ]])

        if card['type'] == 'photo':
            sent_msg = await context.bot.send_photo(chat_id=chat.id, photo=card['file_id'], caption=text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        else:
            sent_msg = await context.bot.send_video(chat_id=chat.id, video=card['file_id'], caption=text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

        pending_gifts[sent_msg.message_id] = {
            "type": "card",
            "sender_id": sender.id,
            "receiver_id": receiver.id,
            "receiver_name": receiver.first_name,
            "card_id": card_id,
            "card_name": card['name']
        }

# Helper to render /kc view
async def render_kc_view(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0, owner_id: int = None):
    user = update_or_query.effective_user if isinstance(update_or_query, Update) else update_or_query.from_user
    target_id = owner_id if owner_id else user.id
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT coins, selected_card_id, name FROM users WHERE user_id = $1", target_id)
        coins = user_row['coins'] if user_row else 0
        selected_card_id = user_row['selected_card_id'] if user_row else None
        display_name = user_row['name'] if user_row else user.first_name

        rank_row = await conn.fetchrow("SELECT COUNT(*) + 1 AS rank FROM users WHERE coins > $1", coins)
        rank = rank_row['rank']

        user_card_rows = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id, uc.amount 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1 AND uc.amount > 0
            ORDER BY c.card_id ASC
        """, target_id)

    text_header = f"""◓𝙉𝘼𝙈𝙀〇 {get_mention(target_id, display_name)}
        ◒ 𝙸𝙳⊝ <code>{target_id}</code>
◓𝙆𝙖𝙘𝙝𝙞 𝘾𝙤𝙞𝙣⊖ {coins} 🩸
         ◓𝙶𝙻𝙾𝙱𝙰𝙻 𝙽𝙾 ▷ #{rank}"""

    if not user_card_rows:
        full_text = f"{text_header}\n\n🎴 <i>ပိုင်ဆိုင်ထားသော ကဒ် မရှိသေးပါ။</i>"
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(full_text, parse_mode="HTML", reply_to_message_id=msg_id)
        else:
            return await update_or_query.edit_message_caption(caption=full_text, parse_mode="HTML")

    active_card = None
    if selected_card_id:
        active_card = next((c for c in user_card_rows if c['card_id'] == selected_card_id), None)
    if not active_card:
        active_card = user_card_rows[-1]

    per_page = 5
    total_cards = len(user_card_rows)
    total_pages = (total_cards + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))

    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_page_cards = user_card_rows[start_idx:end_idx]

    cards_info_list = []
    for c in current_page_cards:
        count_str = f" <b>({c['amount']}x)</b>" if c['amount'] > 1 else ""
        cards_info_list.append(f"• <b>{c['name']}</b> (ID: <code>{c['card_id']}</code>){count_str}")

    cards_info = "\n".join(cards_info_list)
    page_str = f" (Page {page + 1}/{total_pages})" if total_pages > 1 else ""
    full_text = f"{text_header}\n\n🎴 <b>ပိုင်ဆိုင်ထားသော ကဒ်များ{page_str}:</b>\n{cards_info}"

    buttons = []
    if total_pages > 1:
        if page > 0:
            buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"kcpage_{page - 1}_{target_id}"))
        if page < total_pages - 1:
            buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"kcpage_{page + 1}_{target_id}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if isinstance(update_or_query, Update):
        try:
            if active_card['type'] == 'photo':
                await update_or_query.message.reply_photo(photo=active_card['file_id'], caption=full_text, parse_mode="HTML", reply_markup=markup, reply_to_message_id=msg_id)
            else:
                await update_or_query.message.reply_video(video=active_card['file_id'], caption=full_text, parse_mode="HTML", reply_markup=markup, reply_to_message_id=msg_id)
        except Exception:
            await update_or_query.message.reply_text(full_text, parse_mode="HTML", reply_markup=markup, reply_to_message_id=msg_id)
    else:
        query = update_or_query
        try:
            await query.edit_message_caption(caption=full_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            try:
                await query.edit_message_text(text=full_text, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass

# /kc Command Handler
async def check_kc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    await register_user_group(user, chat)
    await render_kc_view(update, context, page=0, owner_id=user.id)

# /cardlist Command - Admin Only
async def cardlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_cardlist_page(update, context, page=0, owner_id=update.effective_user.id)

async def render_cardlist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0, owner_id: int = None):
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None
    async with db_pool.acquire() as conn:
        cards = await conn.fetch("SELECT card_id, name, type FROM cards ORDER BY card_id ASC")

    if not cards:
        text = "🎴 <b>Card List ထဲတွင် ကဒ်များ မရှိသေးပါ။</b>"
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)
        else:
            return await update_or_query.edit_message_text(text, parse_mode="HTML")

    per_page = 10
    total_cards = len(cards)
    total_pages = (total_cards + per_page - 1) // per_page

    page = max(0, min(page, total_pages - 1))
    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_page_cards = cards[start_idx:end_idx]

    card_text_list = []
    for idx, c in enumerate(current_page_cards, start=start_idx + 1):
        type_emoji = "🖼" if c['type'] == 'photo' else "🎥"
        card_text_list.append(f"{idx}. <b>{c['name']}</b> (ID: <code>{c['card_id']}</code>) [{type_emoji} {c['type'].upper()}]")

    cards_str = "\n".join(card_text_list)

    text = f"""📜 <b>Kachi Card List (Page {page + 1}/{total_pages})</b>
📌 <i>ကဒ်၏ အသေးစိတ်နှင့် ပုံကို ကြည့်ရှုလိုပါက <code>/card [card_id]</code> ကို ရိုက်ပါ။</i>

{cards_str}"""

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"clist_{page - 1}_{owner_id}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ▶", callback_data=f"clist_{page + 1}_{owner_id}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(text, parse_mode="HTML", reply_markup=markup, reply_to_message_id=msg_id)
    else:
        query = update_or_query
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass

# /card [card_id] Command
async def card_detail_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    if not context.args:
        return await update.message.reply_text("❌ အသုံးပြုနည်း: `/card [card_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_card_id = context.args[0].strip()

    async with db_pool.acquire() as conn:
        card = await conn.fetchrow("SELECT card_id, name, type, file_id FROM cards WHERE card_id = $1", target_card_id)

        if not card:
            return await update.message.reply_text(f"❌ Card ID <code>{target_card_id}</code> ရှာမတွေ့ပါ။", parse_mode="HTML", reply_to_message_id=msg_id)

        global_drop_count = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE card_id = $1", target_card_id)

        top_owners = await conn.fetch("""
            SELECT u.user_id, u.name, uc.amount 
            FROM user_cards uc
            JOIN users u ON uc.user_id = u.user_id
            WHERE uc.card_id = $1 AND uc.amount > 0
            ORDER BY uc.amount DESC, u.user_id ASC
            LIMIT 10
        """, target_card_id)

    owners_text_list = []
    if top_owners:
        for idx, row in enumerate(top_owners, 1):
            owners_text_list.append(f"{idx}. {get_mention(row['user_id'], row['name'])} — <b>{row['amount']}x</b>")
        owners_str = "\n".join(owners_text_list)
    else:
        owners_str = "<i>မည်သူမျှ ပိုင်ဆိုင်ထားခြင်း မရှိသေးပါ။</i>"

    caption_text = f"""🎴 <b>Card Info Details</b>

🏷️ <b>Name:</b> {card['name']}
🆔 <b>Card ID:</b> <code>{card['card_id']}</code>
📂 <b>Type:</b> {card['type'].upper()}
🌐 <b>Global Drop Count:</b> <b>{global_drop_count}</b> ကဒ်

👑 <b>Top Owners:</b>
{owners_str}"""

    is_video = (card['type'] == 'video') or (str(card['file_id']).startswith("BAA"))

    if is_video:
        try:
            await context.bot.send_video(chat_id=chat.id, video=card['file_id'], caption=caption_text, parse_mode="HTML", reply_to_message_id=msg_id)
        except Exception:
            try:
                await context.bot.send_animation(chat_id=chat.id, animation=card['file_id'], caption=caption_text, parse_mode="HTML", reply_to_message_id=msg_id)
            except Exception:
                await update.message.reply_text(caption_text, parse_mode="HTML", reply_to_message_id=msg_id)
    else:
        try:
            await context.bot.send_photo(chat_id=chat.id, photo=card['file_id'], caption=caption_text, parse_mode="HTML", reply_to_message_id=msg_id)
        except Exception:
            try:
                await context.bot.send_document(chat_id=chat.id, document=card['file_id'], caption=caption_text, parse_mode="HTML", reply_to_message_id=msg_id)
            except Exception:
                await update.message.reply_text(caption_text, parse_mode="HTML", reply_to_message_id=msg_id)

# /glist Command for Admin
async def glist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_glist_page(update, context, page=0)

async def render_glist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None
    async with db_pool.acquire() as conn:
        groups = await conn.fetch("SELECT chat_id, title, added_by_id, added_by_name FROM groups")

    if not groups:
        text = "🏰 **Group List ခွင့်ပြုထားသော Group မရှိသေးပါ။**"
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(text, parse_mode="Markdown", reply_to_message_id=msg_id)
        else:
            return await update_or_query.edit_message_text(text, parse_mode="Markdown")

    total_groups = len(groups)
    g = groups[page]
    chat_id = g['chat_id']

    member_count = "N/A"
    invite_link = "မရရှိနိုင်ပါ (No Permission)"
    try:
        member_count = await context.bot.get_chat_member_count(chat_id)
    except Exception:
        pass

    try:
        chat_obj = await context.bot.get_chat(chat_id)
        if chat_obj.invite_link:
            invite_link = chat_obj.invite_link
        elif chat_obj.username:
            invite_link = f"https://t.me/{chat_obj.username}"
        else:
            invite_link = await context.bot.export_chat_invite_link(chat_id)
    except Exception:
        pass

    adder_text = "—"
    if g['added_by_id']:
        adder_text = get_mention(g['added_by_id'], g['added_by_name'] or "User")

    text = f"""🏰 <b>Group List ({page + 1}/{total_groups})</b>

🔹 <b>Group Name:</b> {g['title']}
🆔 <b>Group ID:</b> <code>{chat_id}</code>
👥 <b>Members:</b> {member_count}
👤 <b>Added By:</b> {adder_text}
🔗 <b>Link:</b> {invite_link}"""

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀ Back", callback_data=f"glist_{page - 1}"))
    if page < total_groups - 1:
        buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"glist_{page + 1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True, reply_to_message_id=msg_id)
    else:
        await update_or_query.edit_message_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)

# Media Commands (/g, /r)
async def media_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    cmd = update.message.text.split()[0].lower()
    sub_cmd = context.args[0].lower() if context.args else ""
    target = "g" if "/g" in cmd else "r"
    key = "game_media" if target == "g" else "result_media"

    global game_media, result_media

    if sub_cmd == "del":
        if target == "g":
            game_media = None
        else:
            result_media = None

        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM settings WHERE key=$1", key)

        return await update.message.reply_text(f"🗑 {'Game' if target == 'g' else 'Result'} Media ကို ဖျက်လိုက်ပါပြီ။", reply_to_message_id=msg_id)

    reply = update.message.reply_to_message
    if not reply:
        return await update.message.reply_text("❌ ပုံ သို့မဟုတ် Video ပို့ထားတဲ့ စာကို Reply ထောက်ပြီး Command ရိုက်ပါ။", reply_to_message_id=msg_id)

    media_obj = None
    if reply.photo:
        media_obj = {"type": "photo", "file_id": reply.photo[-1].file_id}
    elif reply.video:
        media_obj = {"type": "video", "file_id": reply.video.file_id}
    else:
        return await update.message.reply_text("❌ Photo သို့မဟုတ် Video ဖြင့် Reply တွဲပါ။", reply_to_message_id=msg_id)

    if target == "g":
        game_media = media_obj
    else:
        result_media = media_obj

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
        """, key, json.dumps(media_obj))

    await update.message.reply_text(f"✅ {'Game' if target == 'g' else 'Result'} Media သတ်မှတ်ပြီးပါပြီ။", reply_to_message_id=msg_id)

# /stats Command
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:
        u_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        g_count = await conn.fetchval("SELECT COUNT(*) FROM groups")

    await update.message.reply_text(
        f"📊 **Bot Statistics:**\n\n👥 Users: {u_count}\n🏰 Groups: {g_count}",
        parse_mode="Markdown",
        reply_to_message_id=msg_id
    )

# /broadcast Command
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return
    reply = update.message.reply_to_message
    if not reply:
        return await update.message.reply_text("❌ Broadcast ပို့ချင်သော Message ကို Reply ထောက်ပြီး /broadcast ဟု ရိုက်ပါ။", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        users = [r['user_id'] for r in await conn.fetch("SELECT user_id FROM users")]
        groups = [r['chat_id'] for r in await conn.fetch("SELECT chat_id FROM groups")]

    targets = list(set(users + groups))
    await update.message.reply_text(f"🚀 Broadcast (Forward) စတင်နေပါပြီ... (Target: {len(targets)})", reply_to_message_id=msg_id)

    success = 0
    for tid in targets:
        try:
            await context.bot.forward_message(
                chat_id=tid,
                from_chat_id=update.effective_chat.id,
                message_id=reply.message_id
            )
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass

    await update.message.reply_text(f"✅ Broadcast ပို့ဆောင်ပြီးပါပြီ! (အောင်မြင်: {success}/{len(targets)})", reply_to_message_id=msg_id)

# Message Handler
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.message
    if not chat or not msg:
        return

    await register_user_group(user, chat)

    # DM Handling for Team Setup Flow
    if chat.type == "private":
        if user.id in team_creation_state:
            state = team_creation_state[user.id]
            step = state.get("step")

            # Step 1: Receiving Team Name
            if step == "name":
                t_name = msg.text.strip() if msg.text else ""
                if not t_name or len(t_name) > 30:
                    return await msg.reply_text("❌ Team Name သည် စာလုံးရေ 1 မှ 30 အထိ စာဖြင့်သာ ရိုက်ထည့်ပေးပါ။", reply_to_message_id=msg.message_id)

                state["team_name"] = t_name
                state["step"] = "limit"

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("1/7", callback_data=f"tlimit_7_{user.id}"), InlineKeyboardButton("1/9", callback_data=f"tlimit_9_{user.id}")],
                    [InlineKeyboardButton("1/13", callback_data=f"tlimit_13_{user.id}"), InlineKeyboardButton("1/15", callback_data=f"tlimit_15_{user.id}")]
                ])
                await msg.reply_text("✅ Team Name ရရှိပါပြီ!\n\nTeam Member Limit ရွေးပါ:", reply_markup=keyboard, reply_to_message_id=msg.message_id)
                return

            # Step 2: Receiving Team Logo (Photo or Video Only)
            elif step == "logo":
                if not msg.photo and not msg.video:
                    return await msg.reply_text("⚠️ ကျေးဇူးပြု၍ ပုံ (Photo) သို့မဟုတ် ဗီဒီယို (Video) ဖြင့်သာ Team Logo ပေးပို့ပေးပါခင်ဗျာ။", reply_to_message_id=msg.message_id)

                if msg.photo:
                    logo_file_id = msg.photo[-1].file_id
                    logo_type = "photo"
                else:
                    logo_file_id = msg.video.file_id
                    logo_type = "video"

                t_name = state["team_name"]
                t_limit = state["limit"]
                code = generate_team_code()

                async with db_pool.acquire() as conn:
                    # Final check for coins before creation
                    coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)
                    if not coins or coins < 500:
                        del team_creation_state[user.id]
                        return await msg.reply_text("❌ သင့်ထံတွင် Kachi Coin 500 မလုံလောက်တော့ပါသဖြင့် Team တည်ထောင်ခြင်းကို ဖျက်သိမ်းလိုက်ပါသည်။", reply_to_message_id=msg.message_id)

                    # Deduct 500 coins upon successful completion
                    await conn.execute("UPDATE users SET coins = coins - 500 WHERE user_id = $1", user.id)

                    await conn.execute("""
                        INSERT INTO user_teams (team_code, team_name, leader_id, member_limit, logo_file_id, logo_type)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, code, t_name, user.id, t_limit, logo_file_id, logo_type)

                    await conn.execute("""
                        INSERT INTO team_members (team_code, user_id) VALUES ($1, $2)
                    """, code, user.id)

                del team_creation_state[user.id]

                await msg.reply_text("✅ Team တည်ထောင်ခြင်း အောင်မြင်ပါပြီ! (500 Coin နှုတ်ယူပြီးပါပြီ)", reply_to_message_id=msg.message_id)
                await show_user_team(update, chat.id, code, reply_to_msg_id=msg.message_id)
                return

    if chat.type in ["group", "supergroup"]:
        chat_id = chat.id
        is_admin = await check_bot_admin(context, chat_id)
        if not is_admin:
            asyncio.create_task(handle_permission_wait(context, chat_id))

        group_msg_count[chat_id] = group_msg_count.get(chat_id, 0) + 1
        threshold = group_threshold.get(chat_id, global_default_threshold)

        if group_msg_count[chat_id] >= threshold and chat_id not in active_games:
            group_msg_count[chat_id] = 0
            asyncio.create_task(start_game(context, chat_id))

# UI & Buttons
def build_game_ui(game):
    home_list = [game["user_names"][uid] for uid, choice in game["bets"].items() if choice == "home"]
    away_list = [game["user_names"][uid] for uid, choice in game["bets"].items() if choice == "away"]
    draw_list = [game["user_names"][uid] for uid, choice in game["bets"].items() if choice == "draw"]

    home_str = "\n".join(home_list) if home_list else "—"
    away_str = "\n".join(away_list) if away_list else "—"
    draw_str = "\n".join(draw_list) if draw_list else "—"

    return f"""⚽  𝗖𝗵𝗼𝗼𝘀𝗲 𝗙𝗼𝗿 𝗪𝗶𝗻 🍀

🏖️ <b>{game['home']['emoji']} {game['home']['name']}</b> vs <b>{game['away']['emoji']} {game['away']['name']}</b> ⛵

⛲ <i>Stadium</i> - {game['home']['stadium']}
⏲ <i>Time Left</i> - {game['time_left']}s

🧩 𝙇𝙞𝙫𝙚 𝘽𝙚𝙩𝙩𝙞𝙣𝙜 𝙇𝙞𝙨𝙩 

♠ <b>{game['home']['name']}</b>
{home_str}

♥ <b>{game['away']['name']}</b>
{away_str}

♦️ <b>Draw</b>
{draw_str}

GᴏᴏᴅLᴜᴄᴋ G_ʏ ☘️"""

def build_game_buttons(game):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{game['home']['emoji']} {game['home']['name']}", callback_data="bet_home"),
            InlineKeyboardButton(f"{game['away']['emoji']} {game['away']['name']}", callback_data="bet_away"),
        ],
        [InlineKeyboardButton("🤝 Draw", callback_data="bet_draw")],
    ])

def get_leaderboard_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏆 Top In Gp", callback_data="lb_gp"),
            InlineKeyboardButton("🌍 Global Top", callback_data="lb_global"),
        ],
        [
            InlineKeyboardButton("💎 Richest Card Owners", callback_data="lb_cards"),
            InlineKeyboardButton("🌐 GLOBAL TEAM", callback_data="lb_teams_page_0")
        ],
        [
            InlineKeyboardButton("🏰 Top Groups", callback_data="lb_groups")
        ]
    ])

# Helper to render Top Team details with media paging
async def render_top_teams_view(query, page: int = 0):
    async with db_pool.acquire() as conn:
        teams = await conn.fetch("""
            SELECT ut.team_code, ut.team_name, ut.leader_id, ut.member_limit, ut.logo_file_id, ut.logo_type,
                   u.name AS leader_name,
                   COALESCE(SUM(u_all.coins), 0) AS total_coins,
                   COALESCE(SUM(u_all.wins), 0) AS total_wins,
                   COALESCE(SUM(u_all.total_games), 0) AS total_games
            FROM user_teams ut
            JOIN users u ON ut.leader_id = u.user_id
            JOIN team_members tm ON ut.team_code = tm.team_code
            JOIN users u_all ON tm.user_id = u_all.user_id
            GROUP BY ut.team_code, ut.team_name, ut.leader_id, ut.member_limit, ut.logo_file_id, ut.logo_type, u.name
            ORDER BY total_coins DESC, total_wins DESC
            LIMIT 10
        """)

    if not teams:
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="lb_back")]])
        try:
            if query.message.caption:
                await query.edit_message_caption(caption="🌐 <b>GLOBAL TOP TEAMS</b>\n\n<i>အသင်းများ မရှိသေးပါခင်ဗျာ။</i>", parse_mode="HTML", reply_markup=back_markup)
            else:
                await query.edit_message_text(text="🌐 <b>GLOBAL TOP TEAMS</b>\n\n<i>အသင်းများ မရှိသေးပါခင်ဗျာ။</i>", parse_mode="HTML", reply_markup=back_markup)
        except Exception:
            pass
        return

    total_teams = len(teams)
    page = max(0, min(page, total_teams - 1))
    t = teams[page]

    async with db_pool.acquire() as conn:
        members = await conn.fetch("""
            SELECT u.user_id, u.name 
            FROM team_members tm
            JOIN users u ON tm.user_id = u.user_id
            WHERE tm.team_code = $1
            ORDER BY u.user_id ASC
        """, t['team_code'])

    wr = round((t['total_wins'] / t['total_games']) * 100, 1) if t['total_games'] > 0 else 0.0
    member_lines = [f"⇋ {get_mention(m['user_id'], m['name'])}" for m in members]
    members_str = "\n".join(member_lines)

    text = f"""🌐 <b>GLOBAL TOP TEAM (RANK #{page + 1}/{total_teams})</b>

TEAM - <b>{t['team_name']}</b>
Code: <code>{t['team_code']}</code>

 ▱ <i>Leader</i> : {get_mention(t['leader_id'], t['leader_name'])}
 🩸 Coins: <b>{t['total_coins']}</b> | 🎯 Winrate: <b>{wr}%</b>

<i>Team Members</i> ⊞ ({len(members)}/{t['member_limit']})

{members_str}"""

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"lb_teams_page_{page - 1}"))
    if page < total_teams - 1:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"lb_teams_page_{page + 1}"))

    buttons = []
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="lb_back")])

    markup = InlineKeyboardMarkup(buttons)

    # Prepare Media Input
    if t['logo_type'] == 'photo':
        media = InputMediaPhoto(media=t['logo_file_id'], caption=text, parse_mode="HTML")
    else:
        media = InputMediaVideo(media=t['logo_file_id'], caption=text, parse_mode="HTML")

    try:
        await query.edit_message_media(media=media, reply_markup=markup)
    except Exception:
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=markup)
            else:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass

# Game Flow
async def start_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    home_team, away_team = random.sample(TEAMS, 2)
    game_state = {
        "home": home_team,
        "away": away_team,
        "bets": {},
        "user_names": {},
        "time_left": 60,
        "msg_id": None,
    }
    active_games[chat_id] = game_state

    caption = build_game_ui(game_state)
    markup = build_game_buttons(game_state)

    if game_media:
        if game_media["type"] == "photo":
            sent = await context.bot.send_photo(chat_id, game_media["file_id"], caption=caption, parse_mode="HTML", reply_markup=markup)
        else:
            sent = await context.bot.send_video(chat_id, game_media["file_id"], caption=caption, parse_mode="HTML", reply_markup=markup)
    else:
        sent = await context.bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=markup)

    game_state["msg_id"] = sent.message_id

    while game_state["time_left"] > 0:
        await asyncio.sleep(5)
        game_state["time_left"] -= 5
        text = build_game_ui(game_state)
        buttons = build_game_buttons(game_state)
        try:
            if game_media:
                await context.bot.edit_message_caption(chat_id=chat_id, message_id=game_state["msg_id"], caption=text, parse_mode="HTML", reply_markup=buttons)
            else:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=game_state["msg_id"], text=text, parse_mode="HTML", reply_markup=buttons)
        except Exception:
            pass

    try:
        await context.bot.delete_message(chat_id, game_state["msg_id"])
    except Exception:
        pass

    anim = await context.bot.send_message(chat_id, "⚡")
    await asyncio.sleep(3)
    try:
        await context.bot.delete_message(chat_id, anim.message_id)
    except Exception:
        pass

    home_g, away_g = random.randint(0, 3), random.randint(0, 3)
    if home_g > away_g:
        win_choice, win_name = "home", home_team["name"]
    elif away_g > home_g:
        win_choice, win_name = "away", away_team["name"]
    else:
        win_choice, win_name = "draw", "Draw"

    winners, losers = [], []
    async with db_pool.acquire() as conn:
        for uid, choice in game_state["bets"].items():
            uname = game_state["user_names"][uid]
            await conn.execute("UPDATE users SET total_games = total_games + 1 WHERE user_id = $1", uid)

            if choice == win_choice:
                reward = 30 if win_choice == "draw" else 10
                await add_coins(uid, reward)
                await conn.execute("UPDATE users SET wins = wins + 1 WHERE user_id = $1", uid)
                winners.append(f"{uname} (+{reward} 🩸)")
            else:
                losers.append(uname)

    win_str = "\n".join(winners) if winners else "—"
    loss_str = "\n".join(losers) if losers else "—"

    res_text = f"""🎗️  𝗠𝗮𝘁𝗰𝗵 𝗥𝗲𝘀𝘂𝗹𝘁   🧶

🏖️ <b>{home_team['name']}</b> {home_g} - {away_g} <b>{away_team['name']}</b> 🪂

⚡ <b>Win</b> - {win_name}

✨ <b>𝐖𝐢𝐧𝐧𝐞𝐫𝐬</b> -
{win_str}

🐸 <b>𝐋𝐨𝐬𝐬𝐞𝐫𝐬</b> -
{loss_str}"""

    leader_markup = get_leaderboard_buttons()

    if result_media:
        if result_media["type"] == "photo":
            sent_res = await context.bot.send_photo(chat_id, result_media["file_id"], caption=res_text, parse_mode="HTML", reply_markup=leader_markup)
        else:
            sent_res = await context.bot.send_video(chat_id, result_media["file_id"], caption=res_text, parse_mode="HTML", reply_markup=leader_markup)
    else:
        sent_res = await context.bot.send_message(chat_id, res_text, parse_mode="HTML", reply_markup=leader_markup)

    last_results[sent_res.message_id] = res_text
    if chat_id in active_games:
        del active_games[chat_id]

# Callback Query Handler
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    user = query.from_user
    data = query.data

    await register_user_group(user, query.message.chat)

    # Team Creation Initiation
    if data.startswith("create_team_"):
        allowed_user_id = int(data.split("_")[2])
        if user.id != allowed_user_id:
            return await query.answer("❌ သင် ခေါ်ယူထားသော /team မဟုတ်ပါ။", show_alert=True)

        async with db_pool.acquire() as conn:
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)
            if not coins or coins < 500:
                return await query.answer("❌ Team တည်ထောင်ရန် Kachi Coin 500 လိုအပ်ပါသည်!", show_alert=True)

            already_in = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)
            if already_in:
                return await query.answer("❌ သင် အဖွဲ့တစ်ခုတွင် ဝင်ရောက်ပြီးသား ဖြစ်ပါသည်။", show_alert=True)

        # Start state setup (Coin နှုတ်ယူခြင်းကို တည်ထောင်ခြင်း အပြည့်အဝ ပြီးစီးမှသာ လုပ်ဆောင်ပါမည်)
        team_creation_state[user.id] = {"step": "name"}

        try:
            await context.bot.send_message(
                user.id,
                f"👋 မင်္ဂလာပါ {get_mention(user.id, user.first_name)}!\n\n"
                "🏆 <b>Team တည်ထောင်ခြင်း စတင်ပါပြီ!</b>\n"
                "ကျေးဇူးပြု၍ သင်ဖန်တီးလိုသော <b>Team Name</b> ကို ပို့ပေးပါ:",
                parse_mode="HTML"
            )
            await query.answer()
            await query.edit_message_text(f"✅ {get_mention(user.id, user.first_name)}၊ Team တည်ထောင်ရန် Bot DM သို့ သွားရောက်ပါ!", parse_mode="HTML")
        except Exception:
            del team_creation_state[user.id]
            await query.answer("❌ Bot DM သို့ Message ပို့၍ မရပါ၊ Bot ကို /start လုပ်ထားပေးပါခင်ဗျာ။", show_alert=True)

        return

    # Team Member Limit Selection
    if data.startswith("tlimit_"):
        parts = data.split("_")
        limit_val = int(parts[1])
        allowed_id = int(parts[2])

        if user.id != allowed_id:
            return await query.answer("❌ သင် အသုံးပြုခွင့် မရှိပါ။", show_alert=True)

        if user.id in team_creation_state:
            team_creation_state[user.id]["limit"] = limit_val
            team_creation_state[user.id]["step"] = "logo"

            await query.answer()
            await query.edit_message_text(f"✅ Member Limit <b>1/{limit_val}</b> ရွေးချယ်ပြီးပါပြီ!\n\nနောက်တစ်ဆင့်အဖြစ် <b>Team Logo</b> (Photo သို့မဟုတ် Video) ပို့ပေးပါ:", parse_mode="HTML")
        return

    # Join Approval Actions
    if data.startswith("joinapp_"):
        parts = data.split("_")
        action = parts[1]
        applicant_id = int(parts[2])
        team_code = parts[3]

        async with db_pool.acquire() as conn:
            team = await conn.fetchrow("SELECT leader_id, team_name, member_limit FROM user_teams WHERE team_code = $1", team_code)
            if not team or user.id != team['leader_id']:
                return await query.answer("❌ သင်သည် ဒီ Team ၏ Leader မဟုတ်ပါ။", show_alert=True)

            if action == "no":
                if msg_id in pending_joins:
                    del pending_joins[msg_id]
                await query.edit_message_text("❌ <b>Team ဝင်ရောက်ခွင့် လျှောက်ထားချက်ကို ငြင်းပယ်လိုက်ပါပြီ။</b>", parse_mode="HTML")
                try:
                    await context.bot.send_message(applicant_id, f"❌ သင့်ကို <b>{team['team_name']}</b> Team မှ Leader က ဝင်ရောက်ခွင့် ငြင်းပယ်လိုက်ပါသည်။", parse_mode="HTML")
                except Exception:
                    pass
                return await query.answer()

            elif action == "yes":
                curr_cnt = await conn.fetchval("SELECT COUNT(*) FROM team_members WHERE team_code = $1", team_code)
                if curr_cnt >= team['member_limit']:
                    return await query.answer("❌ သင့် Team တွင် Member ပြည့်သွားပါပြီ။", show_alert=True)

                app_in_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", applicant_id)
                if app_in_team:
                    return await query.answer("❌ အဆိုပါ အသုံးပြုသူသည် အခြား Team တစ်ခုသို့ ဝင်ရောက်သွားခဲ့ပြီး ဖြစ်ပါသည်။", show_alert=True)

                await conn.execute("INSERT INTO team_members (team_code, user_id) VALUES ($1, $2)", team_code, applicant_id)
                if msg_id in pending_joins:
                    del pending_joins[msg_id]

                await query.edit_message_text(f"✅ <b>Member အသစ် လက်ခံလိုက်ပါပြီ!</b>", parse_mode="HTML")
                try:
                    await context.bot.send_message(applicant_id, f"🎉 <b>Congratulations!</b> သင့်ကို <b>{team['team_name']}</b> Team ထဲသို့ Leader က လက်ခံလိုက်ပါပြီ။", parse_mode="HTML")
                except Exception:
                    pass
                return await query.answer()

    # Gift Confirmation & Cancel Actions
    if data.startswith("gift_"):
        parts = data.split("_")
        action = parts[1]
        allowed_sender_id = int(parts[2])

        if user.id != allowed_sender_id:
            return await query.answer("❌ သင်သည် ပေးပို့သူ မဟုတ်သည့်အတွက် နှိပ်ပိုင်ခွင့် မရှိပါ။", show_alert=True)

        gift_info = pending_gifts.get(msg_id)
        if not gift_info:
            return await query.answer("❌ ဒီ Gift Transfer သက်တမ်းကုန်သွားပါပြီ။", show_alert=True)

        if action == "cancel":
            del pending_gifts[msg_id]
            cancel_text = "❌ <b>Gift Transfer ကို ပေးပို့သူမှ ပယ်ဖျက်လိုက်ပါပြီ။</b>"
            try:
                if query.message.caption:
                    await query.edit_message_caption(caption=cancel_text, parse_mode="HTML")
                else:
                    await query.edit_message_text(text=cancel_text, parse_mode="HTML")
            except Exception:
                pass
            return await query.answer("ပယ်ဖျက်လိုက်ပါပြီ။")

        elif action == "confirm":
            sender_id = gift_info["sender_id"]
            receiver_id = gift_info["receiver_id"]
            receiver_name = gift_info["receiver_name"]

            async with db_pool.acquire() as conn:
                if gift_info["type"] == "coin":
                    amount = gift_info["amount"]
                    s_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", sender_id)
                    if not s_row or s_row['coins'] < amount:
                        return await query.answer("❌ သင့်ထံတွင် Kachi Coin မလုံလောက်တော့ပါ။", show_alert=True)

                    await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", amount, sender_id)
                    await conn.execute("""
                        INSERT INTO users (user_id, name, coins) VALUES ($1, $2, $3)
                        ON CONFLICT(user_id) DO UPDATE SET coins = users.coins + EXCLUDED.coins
                    """, receiver_id, receiver_name, amount)

                    success_text = f"✅ {get_mention(sender_id, user.first_name)} မှ {get_mention(receiver_id, receiver_name)} ထံသို့ Kachi Coin <b>{amount}</b> 🩸 လက်ဆောင်ပေးပို့ခြင်း အောင်မြင်ပါပြီ!"

                elif gift_info["type"] == "card":
                    card_id = gift_info["card_id"]
                    card_name = gift_info["card_name"]

                    s_card = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", sender_id, card_id)
                    if not s_card or s_card['amount'] <= 0:
                        return await query.answer(f"❌ သင့်ထံတွင် Card ID {card_id} မရှိတော့ပါ။", show_alert=True)

                    if s_card['amount'] == 1:
                        await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = $2", sender_id, card_id)
                    else:
                        await conn.execute("UPDATE user_cards SET amount = amount - 1 WHERE user_id = $1 AND card_id = $2", sender_id, card_id)

                    await conn.execute("""
                        INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                        ON CONFLICT(user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
                    """, receiver_id, card_id)

                    success_text = f"✅ {get_mention(sender_id, user.first_name)} မှ {get_mention(receiver_id, receiver_name)} ထံသို့ <b>{card_name}</b> (ID: <code>{card_id}</code>) Card လက်ဆောင်ပေးပို့ခြင်း အောင်မြင်ပါပြီ!"

            del pending_gifts[msg_id]
            try:
                if query.message.caption:
                    await query.edit_message_caption(caption=success_text, parse_mode="HTML")
                else:
                    await query.edit_message_text(text=success_text, parse_mode="HTML")
            except Exception:
                pass
            return await query.answer("လက်ဆောင်ပေးပြီးပါပြီ!")

    # KC Pagination Action
    if data.startswith("kcpage_"):
        parts = data.split("_")
        page = int(parts[1])
        target_id = int(parts[2])

        if user.id != target_id:
            return await query.answer("❌ သင် ခေါ်ယူထားသော /kc မဟုတ်ပါ!", show_alert=True)

        await render_kc_view(query, context, page=page, owner_id=target_id)
        await query.answer()
        return

    # Coin Box Claim Action
    if data == "claim_cbox":
        box = active_cboxes.get(msg_id)
        if not box:
            return await query.answer("❌ ဒီ Coin Box သက်တမ်းကုန်သွားပါပြီ သို့မဟုတ် မရှိတော့ပါ။", show_alert=True)

        if user.id in box["claimed_users"]:
            return await query.answer("❌ သင် ဒီ Box မှ Coin ခိုးယူပြီးပါပြီ!", show_alert=True)

        if box["remaining"] <= 0:
            return await query.answer("❌ Coin Box ထဲတွင် Coin များ ကုန်သွားပါပြီ!", show_alert=True)

        max_steal = max(1, min(box["remaining"], int(box["total_amount"] * 0.4)))
        stolen_amount = random.randint(1, max_steal) if box["remaining"] > 1 else box["remaining"]

        box["remaining"] -= stolen_amount
        box["claimed_users"][user.id] = {
            "name": user.first_name,
            "got": stolen_amount
        }

        await add_coins(user.id, stolen_amount)
        await query.answer(f"🎉 သင့်ထံသို့ {stolen_amount} 🩸 Kachi Coin ရရှိသွားပါပြီ!", show_alert=True)

        claimed_list = []
        for uid, udata in box["claimed_users"].items():
            claimed_list.append(f"• {get_mention(uid, udata['name'])} — <b>{udata['got']}</b> 🩸")
        
        list_str = "\n".join(claimed_list)

        if box["remaining"] > 0:
            status_str = f"💰 <b>Live Remaining Amount:</b> <code>{box['remaining']}</code> 🩸"
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏴‍☠ ခိုးရန်", callback_data="claim_cbox")]])
        else:
            status_str = "🎁 <b>Coin Box ကုန်သွားပါပြီ!</b>"
            markup = None

        text = f"""🎁 <b>Kachi Coin Box!</b> 🩸

{status_str}
👤 <b>Created By:</b> {box['creator']}

📋 <b>ခိုးယူသွားသူများ Live List:</b>
{list_str}"""

        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        return

    # Spin Kachi Box Action
    if data.startswith("spin_"):
        owner_id = int(data.split("_")[1])
        if user.id != owner_id:
            return await query.answer("❌ သင် ခေါ်ယူထားသော Box မဟုတ်ပါ။ မိမိကိုယ်တိုင် /kbox ခေါ်ယူပါ။", show_alert=True)

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
            coins = row['coins'] if row else 0

            if coins < 300:
                return await query.answer("❌ Kachi Coin 300 မလုံလောက်ပါ။", show_alert=True)

            cards = await conn.fetch("SELECT card_id, name, type, file_id FROM cards")
            if not cards:
                return await query.answer("❌ Box အတွင်း Card များ မရှိသေးပါ၊ ခဏစောင့်ပါ။", show_alert=True)

            await conn.execute("UPDATE users SET coins = coins - 300 WHERE user_id = $1", user.id)

        await query.answer("🎰 Box စတင်လှည့်နေပါပြီ...")

        frames = ["🔄 [▰▱▱▱▱▱▱▱▱▱] Loading 10%...", "🔄 [▰▰▰▰▱▱▱▱▱▱] Loading 40%...", "🔄 [▰▰▰▰▰▰▰▱▱▱] Loading 70%...", "🔄 [▰▰▰▰▰▰▰▰▰▰] Complete!"]
        for frame in frames:
            try:
                await query.edit_message_text(f"🎁 {get_mention(user.id, user.first_name)} မင်္ဂလာပါ!\n\n{frame}", parse_mode="HTML")
            except Exception:
                pass
            await asyncio.sleep(1)

        won_card = random.choice(cards)

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, user.id, won_card['card_id'])

            rem_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)
            new_amount = await conn.fetchval("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", user.id, won_card['card_id'])

        try:
            await query.message.delete()
        except Exception:
            pass

        amount_notice = f"\n📦 <b>စုစုပေါင်း ပိုင်ဆိုင်မှု:</b> {new_amount}x" if new_amount > 1 else ""

        win_text = f"""🎉 <b>Congratulations {get_mention(user.id, user.first_name)}!</b>

🆔 <b>User ID:</b> <code>{user.id}</code>
💰 <b>Kachi Coin လက်ကျန်:</b> {rem_coins} 🩸

🎴 <b>ရရှိသွားသော Card အချက်အလက်:</b>
🏷 <b>Name:</b> {won_card['name']}
🔢 <b>Card ID:</b> <code>{won_card['card_id']}</code>{amount_notice}"""

        if won_card['type'] == 'photo':
            await context.bot.send_photo(chat_id=chat_id, photo=won_card['file_id'], caption=win_text, parse_mode="HTML")
        else:
            await context.bot.send_video(chat_id=chat_id, video=won_card['file_id'], caption=win_text, parse_mode="HTML")
        return

    # glist Pagination Handling
    if data.startswith("glist_"):
        if user.id != ADMIN_ID:
            return await query.answer("❌ Admin သီးသန့်ဖြစ်ပါသည်။", show_alert=True)
        page = int(data.replace("glist_", ""))
        await render_glist_page(query, context, page=page)
        await query.answer()
        return

    # cardlist Pagination Handling
    if data.startswith("clist_"):
        parts = data.split("_")
        page = int(parts[1])
        owner_id = int(parts[2]) if len(parts) > 2 else None

        if owner_id and user.id != owner_id:
            return await query.answer("❌ သင် ခေါ်ယူထားသော Card List မဟုတ်ပါ!", show_alert=True)

        await render_cardlist_page(query, context, page=page, owner_id=owner_id)
        await query.answer()
        return

    if data.startswith("bet_"):
        game = active_games.get(chat_id)
        if not game:
            return await query.answer("❌ ဒီပွဲ ပွဲပြီးသွားပါပြီ။", show_alert=True)

        choice = data.replace("bet_", "")
        game["bets"][user.id] = choice
        game["user_names"][user.id] = get_mention(user.id, user.first_name)

        await query.answer("✅ လောင်းကြေးထပ်ပြီးပါပြီ!")
        return

    # Leaderboard ပြန်ထွက်ရန် Back Action
    if data == "lb_back":
        original_text = last_results.get(msg_id, "🎗️ 𝗠𝗮𝘁𝗰𝗵 𝗥𝗲𝘀𝘂𝗹𝘁")
        original_markup = get_leaderboard_buttons()

        if result_media:
            if result_media['type'] == 'photo':
                media = InputMediaPhoto(media=result_media['file_id'], caption=original_text, parse_mode="HTML")
            else:
                media = InputMediaVideo(media=result_media['file_id'], caption=original_text, parse_mode="HTML")
            try:
                await query.edit_message_media(media=media, reply_markup=original_markup)
            except Exception:
                try:
                    await query.edit_message_caption(caption=original_text, parse_mode="HTML", reply_markup=original_markup)
                except Exception:
                    pass
        else:
            try:
                if query.message.caption:
                    await query.edit_message_caption(caption=original_text, parse_mode="HTML", reply_markup=original_markup)
                else:
                    await query.edit_message_text(text=original_text, parse_mode="HTML", reply_markup=original_markup)
            except Exception:
                pass

        await query.answer()
        return

    # Global Top Teams Media Paging Action
    if data.startswith("lb_teams_page_"):
        page_num = int(data.replace("lb_teams_page_", ""))
        await render_top_teams_view(query, page=page_num)
        await query.answer()
        return

    # Leaderboard Actions
    if data.startswith("lb_"):
        lb_type = data.replace("lb_", "")
        async with db_pool.acquire() as conn:
            if lb_type == "gp":
                rows = await conn.fetch("""
                    SELECT u.user_id, u.name, u.coins, COALESCE(SUM(uc.amount), 0) AS total_cards
                    FROM users u
                    JOIN group_members gm ON u.user_id = gm.user_id
                    LEFT JOIN user_cards uc ON u.user_id = uc.user_id
                    WHERE gm.chat_id = $1 AND u.coins > 0
                    GROUP BY u.user_id, u.name, u.coins
                    ORDER BY u.coins DESC
                    LIMIT 10
                """, chat_id)
                title = "🏆 <b>Top In Group</b>"
            elif lb_type == "global":
                rows = await conn.fetch("""
                    SELECT user_id, name, coins FROM users 
                    WHERE coins > 0 
                    ORDER BY coins DESC LIMIT 10
                """)
                title = "🌍 <b>Global Top 10 Users</b>"
            elif lb_type == "cards":
                rows = await conn.fetch("""
                    SELECT u.user_id, u.name, SUM(uc.amount) AS card_count
                    FROM user_cards uc
                    JOIN users u ON uc.user_id = u.user_id
                    WHERE uc.amount > 0
                    GROUP BY u.user_id, u.name
                    ORDER BY card_count DESC
                    LIMIT 10
                """)
                title = "💎 <b>Richest Card Owners (Top 10)</b>"
            elif lb_type == "groups":
                rows = await conn.fetch("SELECT title FROM groups LIMIT 10")
                title = "🏰 <b>Top Groups</b>"

        if not rows:
            text = f"{title}\n\n<i>စာရင်းမရှိသေးပါ သို့မဟုတ် စာရင်းဝင်ရှိသူ မရှိသေးပါ။</i>"
        else:
            if lb_type == "gp":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — {r['coins']} 🩸Kachi Coin ({r['total_cards']} Cards)" for i, r in enumerate(rows)])
            elif lb_type == "global":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — {r['coins']} 🩸Kachi Coin" for i, r in enumerate(rows)])
            elif lb_type == "cards":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — <b>{r['card_count']}</b> Cards" for i, r in enumerate(rows)])
            else:
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {r['title']}" for i, r in enumerate(rows)])

        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="lb_back")]])
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=back_markup)
            else:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=back_markup)
        except Exception:
            pass
        await query.answer()

async def post_init(app: Application):
    await init_db()

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # Public User Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("kc", check_kc_cmd))
    app.add_handler(CommandHandler("set", set_card_cmd))
    app.add_handler(CommandHandler("kbox", kbox_cmd))
    app.add_handler(CommandHandler("kgift", kgift_cmd))
    app.add_handler(CommandHandler("card", card_detail_cmd))
    app.add_handler(CommandHandler("team", team_cmd))
    app.add_handler(CommandHandler("myteam", myteam_cmd))
    app.add_handler(CommandHandler("dele", delete_team_cmd))
    app.add_handler(CommandHandler("join", join_team_cmd))
    app.add_handler(CommandHandler("out", out_team_cmd))

    # Admin Exclusive Commands
    app.add_handler(CommandHandler("game", manual_game_cmd))
    app.add_handler(CommandHandler("cardlist", cardlist_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("c", set_count_cmd))
    app.add_handler(CommandHandler("cbox", cbox_cmd))
    app.add_handler(CommandHandler("wait", set_wait_time_cmd))
    app.add_handler(CommandHandler("glist", glist_cmd))
    app.add_handler(CommandHandler(["g", "r"], media_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("k", admin_coin_cmd))
    app.add_handler(CommandHandler("add", add_card_cmd))
    app.add_handler(CommandHandler("del", del_card_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), message_handler))

    print("🤖 Python Game Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
