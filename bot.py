import asyncio
import json
import os
import random
import re
import string
import time
import asyncpg
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultMpeg4Gif,
    InlineQueryResultPhoto,
    InputMediaPhoto,
    InputMediaVideo,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

# Environment Variables
TOKEN = os.getenv("BOT_TOKEN", "8617814117:AAGbTDFaabbt2RUuHSPQDqT9S6WZqiNosvM")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7940553702"))
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "@beyondpoe")  # Card Add လျှင် Log ပို့မည့် Channel Username / Chat ID

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

# Database Connection Pool
db_pool = None

async def init_db():
    global db_pool, game_media, result_media, global_default_threshold
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                coins BIGINT DEFAULT 0,
                wins BIGINT DEFAULT 0,
                total_games BIGINT DEFAULT 0,
                selected_card_id TEXT,
                vote_tickets BIGINT DEFAULT 0,
                is_popular BOOLEAN DEFAULT FALSE,
                popular_votes BIGINT DEFAULT 0
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
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vote_tickets BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_popular BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS popular_votes BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_id BIGINT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_name TEXT;")
            await conn.execute("ALTER TABLE user_cards ADD COLUMN IF NOT EXISTS amount INT DEFAULT 1;")
        except Exception:
            pass

        # Clean GemStone from cards table (Kept only as a separate balance/item)
        await conn.execute("DELETE FROM cards WHERE card_id = 'gemstone';")

        # Reset Timer Setup
        reset_row = await conn.fetchrow("SELECT value FROM settings WHERE key='last_team_reset'")
        if not reset_row:
            await conn.execute("INSERT INTO settings (key, value) VALUES ('last_team_reset', $1)", str(int(time.time())))

        g_media_row = await conn.fetchrow("SELECT value FROM settings WHERE key='game_media'")
        if g_media_row:
            game_media = json.loads(g_media_row['value'])

        r_media_row = await conn.fetchrow("SELECT value FROM settings WHERE key='result_media'")
        if r_media_row:
            result_media = json.loads(r_media_row['value'])

        thresh_row = await conn.fetchrow("SELECT value FROM settings WHERE key='default_threshold'")
        if thresh_row:
            global_default_threshold = int(thresh_row['value'])

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

# Helper to fetch user active/last card media
async def get_user_card_media(user_id: int):
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT selected_card_id FROM users WHERE user_id = $1", user_id)
        selected_card_id = user_row['selected_card_id'] if user_row else None

        user_cards = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id 
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.card_id
            WHERE uc.user_id = $1 AND uc.amount > 0 AND c.card_id != 'gemstone'
            ORDER BY c.card_id ASC
        """, user_id)

    if not user_cards:
        return None

    card = None
    if selected_card_id:
        card = next((c for c in user_cards if c['card_id'] == selected_card_id), None)
    if not card:
        card = user_cards[-1]

    return card

# 3-Day Team Reset & Prize Distribution Task
async def team_reset_checker(context: ContextTypes.DEFAULT_TYPE):
    while True:
        await asyncio.sleep(60)
        try:
            async with db_pool.acquire() as conn:
                last_reset_row = await conn.fetchrow("SELECT value FROM settings WHERE key='last_team_reset'")
                last_reset = int(last_reset_row['value']) if last_reset_row else int(time.time())
                now = int(time.time())

                # 3 Days = 3 * 24 * 3600 = 259200 seconds
                if now - last_reset >= 259200:
                    top_teams = await conn.fetch("""
                        SELECT ut.team_code, ut.team_name,
                               COALESCE(SUM(u_all.coins), 0) AS total_coins,
                               CASE WHEN SUM(u_all.total_games) > 0 
                                    THEN ROUND((SUM(u_all.wins)::NUMERIC / SUM(u_all.total_games)::NUMERIC) * 100, 1)
                                    ELSE 0.0 END AS winrate
                        FROM user_teams ut
                        JOIN team_members tm ON ut.team_code = tm.team_code
                        JOIN users u_all ON tm.user_id = u_all.user_id
                        GROUP BY ut.team_code, ut.team_name
                        ORDER BY winrate DESC, total_coins DESC
                        LIMIT 5
                    """)

                    for team in top_teams:
                        members = await conn.fetch("SELECT user_id FROM team_members WHERE team_code = $1", team['team_code'])
                        for m in members:
                            await conn.execute("""
                                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, 'gemstone', 1)
                                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
                            """, m['user_id'])
                            try:
                                await context.bot.send_message(
                                    m['user_id'],
                                    f"🎉 <b>ဂုဏ်ယူပါတယ်!</b> သင်၏ Team <b>{team['team_name']}</b> သည် Top 5 ဝင်ခဲ့သောကြောင့် Prize အဖြစ် <b>GemStone💎 ၁ တုံး</b> ရရှိပါပြီ။",
                                    parse_mode="HTML"
                                )
                            except Exception:
                                pass

                    # Reset Users Wins and Total Games stats
                    await conn.execute("UPDATE users SET wins = 0, total_games = 0")
                    await conn.execute("UPDATE settings SET value = $1 WHERE key = 'last_team_reset'", str(now))
        except Exception:
            pass

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

ဆုကြေးများ / 𝙋𝙧𝙞𝙯𝙚
- အသင်းနိုင်လျှင်: 70 🩸Kachi Coin + 10 🎟️ Vote Tickets
- Draw နိုင်လျှင်: 100 🩸Kachi Coin + 10 🎟️ Vote Tickets

📜 <b>အသုံးပြုနိုင်သော Commands များ:</b>
• /kc - မိမိ Coin နှင့် ကဒ်များ စစ်ဆေးရန်
• /kbox - 650 Coin သုံး၍ Card Box ဖောက်ရန်
• /ksell [amount] - GemStone 💎 တစ်တုံးလျှင် 200 Coin ဖြင့် ရောင်းရန်
• /card [card_id] - Card ပုံ/အချက်အလက်နှင့် Top Owners စစ်ဆေးရန်
• /set [card_id] - /kc တွင် ပြသမည့် Card ပုံကို ပြောင်းရန်
• /vote - Popular စာရင်းတွင် ပါဝင်ရန် သို့မဟုတ် မိမိ၏ Popular Post ကြည့်ရန် (2000 Coin)

🛡️ <b>Team System အသုံးပြုနည်းများ:</b>
• <b>/team</b> - Team တည်ထောင်ရန် (800 Coin)
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
4. <b>/k [user_id] [amount]</b> - User ထံ Coin ထည့်/နှုတ်ရန်
5. <b>/add [card_id].[card_name]</b> - Card အသစ်ထည့်ရန် (Photo/Video ကို Reply လုပ်ပါ)
6. <b>/del [card_id]</b> - Card ဖျက်ရန်
7. <b>/cardlist</b> - ရှိသမျှ Card List များ ကြည့်ရန် (Admin Only)
8. <b>/glist</b> - Bot ရှိနေသော Group များ စာရင်းကြည့်ရန်
9. <b>/g</b> (သို့) <b>/r</b> - Game Media သို့မဟုတ် Result Media သတ်မှတ်ရန်
10. <b>/stats</b> - Bot Statistics စာရင်းကြည့်ရန်
11. <b>/broadcast</b> - Group/User များထံ စာ/မီဒီယာများ Forward ပို့ရန်"""

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
            SELECT u.user_id, u.name, u.coins, u.wins, u.total_games 
            FROM team_members tm
            JOIN users u ON tm.user_id = u.user_id
            WHERE tm.team_code = $1
            ORDER BY u.user_id ASC
        """, team_code)

        # Calculate Global Team Rank
        all_teams_ranked = await conn.fetch("""
            SELECT ut.team_code,
                   COALESCE(SUM(u_all.coins), 0) AS total_coins,
                   CASE WHEN SUM(u_all.total_games) > 0 
                        THEN ROUND((SUM(u_all.wins)::NUMERIC / SUM(u_all.total_games)::NUMERIC) * 100, 1)
                        ELSE 0.0 END AS winrate
            FROM user_teams ut
            JOIN team_members tm ON ut.team_code = tm.team_code
            JOIN users u_all ON tm.user_id = u_all.user_id
            GROUP BY ut.team_code
            ORDER BY winrate DESC, total_coins DESC
        """)

        global_rank = "N/A"
        for idx, tr in enumerate(all_teams_ranked, 1):
            if tr['team_code'] == team_code:
                global_rank = f"#{idx}"
                break

    member_lines = []
    for m in members:
        wr = round((m['wins'] / m['total_games']) * 100, 1) if m['total_games'] > 0 else 0.0
        member_lines.append(f"⇋ {get_mention(m['user_id'], m['name'])} — 🩸{m['coins']} (Played: {m['total_games']} | WR: {wr}%)")

    members_str = "\n".join(member_lines)

    text = f"""TEAM - <b>{t_info['team_name']}</b>
Code: <code>{t_info['team_code']}</code>
🌐 Global No ▷ {global_rank}

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
        text = "ကဲ အခုပဲ Legendary Team တစ်ခုတည်ထောင်ပြီး Top 1 ယူပြီး 𝗚𝗲𝗺𝗦𝘁𝗼𝗻𝗲🗽 ကိုရယူကြစို့ (ကုန်ကျစရိတ်: 800 Coin)"
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
        return await update.message.reply_text("❌ ဒီ Command ကို Bot DM မှာပဲ သုံးလို့ရပါမယ်။", reply_to_message_id=msg_id)

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

# /add Command - With Duplicate Check and Channel Log Posting
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
            # Check ID Duplicate or File ID Duplicate
            existing_card = await conn.fetchrow("SELECT card_id, file_id FROM cards WHERE card_id = $1 OR file_id = $2", card_id, file_id)
            if existing_card:
                return await update.message.reply_text(f"⚠️ <b>သတိပေးချက်:</b> အဆိုပါ Card ID (<code>{card_id}</code>) သို့မဟုတ် ပုံ/Video သည် စနစ်ထဲတွင် ထည့်သွင်းပြီးသား ဖြစ်နေပါသည်။", parse_mode="HTML", reply_to_message_id=msg_id)

            await conn.execute("""
                INSERT INTO cards (card_id, name, type, file_id)
                VALUES ($1, $2, $3, $4)
            """, card_id, card_name, c_type, file_id)

        # Log Message Formulation
        log_text = f"""𝙉𝙚𝙬 𝘾𝙖𝙧𝙙 𝘼𝙙𝙙𝙚𝙙

❀𝘊𝘢𝘳𝘥 𝘕𝘢𝘮𝘦 : {card_name}
     ❝  𝙸𝙳 : {card_id}
❀ 𝘛𝘺𝘱𝘦 : {c_type.capitalize()}"""

        # Send Log to Channel
        try:
            if c_type == "photo":
                await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=file_id, caption=log_text)
            else:
                await context.bot.send_video(chat_id=LOG_CHANNEL_ID, video=file_id, caption=log_text)
        except Exception as log_err:
            print(f"Log Error: {log_err}")

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

# /ksell [amount] Command - Sell GemStone
async def ksell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    if not context.args:
        return await update.message.reply_text("❌ အသုံးပြုနည်း: `/ksell [ရောင်းမည့် ပမာဏ]` (ဥပမာ- `/ksell 1`)", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        sell_amount = int(context.args[0])
        if sell_amount <= 0:
            return await update.message.reply_text("❌ ပမာဏသည် 0 ထက် ကြီးရပါမည်။", reply_to_message_id=msg_id)
    except ValueError:
        return await update.message.reply_text("❌ ပမာဏကို ကိန်းဂဏန်းသီးသန့် ရိုက်ထည့်ပါ။", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        gem_row = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
        curr_gems = gem_row['amount'] if gem_row else 0

        if curr_gems < sell_amount:
            return await update.message.reply_text(f"❌ သင့်ထံတွင် GemStone💎 {sell_amount} တုံး မလုံလောက်ပါ။ (လက်ရှိ: {curr_gems} တုံး)", reply_to_message_id=msg_id)

        coins_earned = sell_amount * 200

        # Deduct GemStone
        if curr_gems == sell_amount:
            await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
        else:
            await conn.execute("UPDATE user_cards SET amount = amount - $1 WHERE user_id = $2 AND card_id = 'gemstone'", sell_amount, user.id)

        # Add Coins
        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", coins_earned, user.id)
        rem_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)

    await update.message.reply_text(
        f"✅ GemStone💎 <b>{sell_amount}</b> တုံးကို အောင်မြင်စွာ ရောင်းချလိုက်ပါပြီ!\n\n"
        f"💰 ရရှိသော Kachi Coin: <b>+{coins_earned}</b> 🩸\n"
        f"💳 လက်ရှိ Coin စုစုပေါင်း: <b>{rem_coins}</b> 🩸",
        parse_mode="HTML",
        reply_to_message_id=msg_id
    )

# Helper function to generate single Popular profile text & keyboard
async def get_popular_profile_data(target_uid: int):
    async with db_pool.acquire() as conn:
        u_info = await conn.fetchrow("""
            SELECT u.user_id, u.name, u.coins, u.selected_card_id, u.popular_votes,
                   (SELECT COUNT(*) + 1 FROM users WHERE coins > u.coins) AS global_rank,
                   (SELECT amount FROM user_cards WHERE user_id = u.user_id AND card_id = 'gemstone') AS gem_count,
                   ut.team_name
            FROM users u
            LEFT JOIN team_members tm ON u.user_id = tm.user_id
            LEFT JOIN user_teams ut ON tm.team_code = ut.team_code
            WHERE u.user_id = $1
        """, target_uid)

    gems = u_info['gem_count'] or 0
    team_str = u_info['team_name'] or "မရှိပါ"
    card_id_str = u_info['selected_card_id'] or "မသတ်မှတ်ထားပါ"
    earned_coins = (u_info['popular_votes'] or 0) * 20

    text = f"""📯 𝗣𝗢𝗣𝗨𝗟𝗔𝗥 𝗠𝗘𝗠𝗕𝗘𝗥        
             𝗣𝗥𝗢𝗙𝗜𝗟𝗘 ◁

🧸 𝙿𝙾𝙿𝚄𝙻𝙰𝚁 𝚅𝙾𝚃𝙴: {u_info['popular_votes']}
🎐  𝚅𝙾𝚃𝙴 𝚃𝙾𝚃𝙰𝙻 𝙴𝙰𝚁𝙽𝙴𝙳 𝙲𝙾𝙸𝙽𝚂: {earned_coins}

🍀𝑁𝑎𝑚𝑒: {get_mention(u_info['user_id'], u_info['name'])}
🍀   𝑈𝑆𝐸𝑅 𝐼𝐷: <code>{u_info['user_id']}</code>
🩸𝐾𝑎𝑐ℎ𝑖 𝐶𝑜𝑖𝑛: {u_info['coins']}
  💎  𝐺𝑒𝑚𝑆𝑡𝑜𝑛𝑒: {gems}
🍀𝑆𝑒𝑙𝑒𝑐𝑡𝑒𝑑 𝐶𝑎𝑟𝑑 𝐼𝐷: <code>{card_id_str}</code>
   🎖 𝐺𝑙𝑜𝑏𝑎𝑙 𝑅𝑎𝑛𝑘: #{u_info['global_rank']}
〇𝑇𝑒𝑎𝑚: {team_str}"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗳️ Vote Him (5 Tickets)", callback_data=f"pop_vote_{target_uid}_0"),
            InlineKeyboardButton("💎 Gem Gift (1 Gem)", callback_data=f"pop_gemgift_{target_uid}_0")
        ]
    ])
    return text, keyboard

# /vote Command - Register or Show User's Own Popular Entry
async def vote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT is_popular FROM users WHERE user_id = $1", user.id)

    # User is already popular -> Show user's popular post with Active/Last Card
    if user_row and user_row['is_popular']:
        text, keyboard = await get_popular_profile_data(user.id)
        card = await get_user_card_media(user.id)
        
        if card:
            try:
                if card['type'] == 'photo':
                    await update.message.reply_photo(photo=card['file_id'], caption=text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
                else:
                    await update.message.reply_video(video=card['file_id'], caption=text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
                return
            except Exception:
                pass

        await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        return

    # User not popular -> Show registration prompt
    text = f"""👋 Hello {get_mention(user.id, user.first_name)} !

🌟 <b>Popular စာရင်းမှာ ပါဝင်ဖို့ Ready ပဲလား?</b>

Popular စာရင်းထဲ ပါဝင်ခွင့်လျှောက်ထားပြီး အခြားသူများ၏ Vote မဲများကို စုဆောင်းလိုက်ပါ!

<i>(ပါဝင်ခွင့် လျှောက်ထားခစရိတ်: <b>2000 Kachi Coin</b> 🩸)</i>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔥 Popular ဖြစ်ရန်", callback_data=f"reg_popular_{user.id}")
    ]])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

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

# /kbox Command - Custom Button on Insufficient Balance
async def kbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
        coins = row['coins'] if row else 0

    if coins < 650:
        # Hide spin button, show only card view button
        insufficient_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎴 ကဒ်များကြည့်ရန်", url="https://t.me/beyondpoe")
        ]])
        return await update.message.reply_text(
            f"❌ မင်္ဂလာပါ {get_mention(user.id, user.first_name)}၊ Box လှည့်ရန် Kachi Coin 650 လိုအပ်ပါသည်။\nသင့်ထံတွင် {coins} Coin သာရှိပါသည်။",
            parse_mode="HTML",
            reply_markup=insufficient_keyboard,
            reply_to_message_id=msg_id
        )

    text = f"{get_mention(user.id, user.first_name)} Box ဖောက်နေပါပြီ၊ ဘယ်ဟာလေး ကံကောင်းသွားမလဲ မစောင့်နိုင်တော့ဘူး..."
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎰 စလှည့်ရန်", callback_data=f"spin_{user.id}"),
        InlineKeyboardButton("🎴 ကဒ်များကြည့်ရန်", url="https://t.me/beyondpoe")
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
        user_row = await conn.fetchrow("SELECT coins, selected_card_id, name, vote_tickets FROM users WHERE user_id = $1", target_id)
        coins = user_row['coins'] if user_row else 0
        tickets = user_row['vote_tickets'] if user_row else 0
        selected_card_id = user_row['selected_card_id'] if user_row else None
        display_name = user_row['name'] if user_row else user.first_name

        rank_row = await conn.fetchrow("SELECT COUNT(*) + 1 AS rank FROM users WHERE coins > $1", coins)
        rank = rank_row['rank']

        gem_row = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", target_id)
        gem_count = gem_row['amount'] if gem_row else 0

        user_card_rows = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id, uc.amount 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1 AND uc.amount > 0
            ORDER BY c.card_id ASC
        """, target_id)

    text_header = f"""❀ 𝙉𝘼𝙈𝙀 : {get_mention(target_id, display_name)}
        ⬤ 𝐼𝐷 : <code>{target_id}</code>
🩸 𝙆𝙖𝙘𝙝𝙞 𝘾𝙤𝙞𝙣 : {coins}
      💎 𝐺𝑒𝑚𝑆𝑡𝑜𝑛𝑒 : {gem_count}
🎟 𝙑𝙤𝙩𝙚 𝙏𝙞𝙘𝙠𝙚𝙩𝙨 : {tickets}
        
❀ ɢʟᴏʙᴀʟ ɴᴏ : #{rank}"""

    if not user_card_rows:
        full_text = f"{text_header}\n\n❄ ပိုင်ဆိုင်ထားသော ကဒ်များ\n\n<i>မရှိသေးပါ။</i>"
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Harem ❄", switch_inline_query_current_chat=f"harem.{target_id}")
        ]])
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(full_text, parse_mode="HTML", reply_markup=markup, reply_to_message_id=msg_id)
        else:
            return await update_or_query.edit_message_caption(caption=full_text, parse_mode="HTML", reply_markup=markup)

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
        cards_info_list.append(f"🍀 <i>{c['name']}</i> ( {c['card_id']} )")

    cards_info = "\n\n".join(cards_info_list)
    full_text = f"{text_header}\n\n❄️ <b>ပိုင်ဆိုင်ထားသော ကဒ်များ</b>\n\n{cards_info}"

    buttons = []
    page_buttons = []
    if total_pages > 1:
        if page > 0:
            page_buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"kcpage_{page - 1}_{target_id}"))
        if page < total_pages - 1:
            page_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"kcpage_{page + 1}_{target_id}"))

    if page_buttons:
        buttons.append(page_buttons)

    # Harem ❄ Inline Query Button ထည့်သွင်းခြင်း
    buttons.append([InlineKeyboardButton("Harem ❄", switch_inline_query_current_chat=f"harem.{target_id}")])

    markup = InlineKeyboardMarkup(buttons)

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

# Inline Query Handler - Card Harem Grid Display (Photos & Videos)
async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    q_text = query.query.strip()
    user_id = query.from_user.id

    # If queried with specific user ID format like "harem.123456"
    if q_text.startswith("harem."):
        try:
            target_id = int(q_text.split(".")[1])
        except ValueError:
            target_id = user_id
    else:
        target_id = user_id

    async with db_pool.acquire() as conn:
        owner_info = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
        owner_name = owner_info['name'] if owner_info else query.from_user.first_name

        user_cards = await conn.fetch("""
            SELECT c.card_id, c.name, c.file_id, c.type, uc.amount 
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.card_id
            WHERE uc.user_id = $1 AND uc.amount > 0 AND c.card_id != 'gemstone'
            ORDER BY c.card_id ASC
        """, target_id)

    results = []
    for idx, card in enumerate(user_cards):
        async with db_pool.acquire() as conn:
            global_drop = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE card_id = $1", card['card_id'])

        # Requested Output Text Format
        caption = f"""Harem ပိုင်ရှင် {owner_name}

❄️<b>CARD NAME</b> : <i>{card['name']}</i>
❄️<b>CARD ID</b> : <code>{card['card_id']}</code>
❄️<b>AMOUNT</b> : {card['amount']}x
❄️<b>GLOBAL DROP</b> : {global_drop}

Use /card {card['card_id']} 💦"""
        
        # Photogrid display (Photo & Video support)
        if card['type'] == 'photo':
            results.append(
                InlineQueryResultPhoto(
                    id=f"{card['card_id']}_{idx}",
                    photo_url=card['file_id'],
                    thumbnail_url=card['file_id'],
                    title=card['name'],
                    description=f"ID: {card['card_id']} | x{card['amount']}",
                    caption=caption,
                    parse_mode="HTML"
                )
            )
        else:
            results.append(
                InlineQueryResultMpeg4Gif(
                    id=f"{card['card_id']}_{idx}",
                    mpeg4_url=card['file_id'],
                    thumbnail_url=card['file_id'],
                    title=card['name'],
                    caption=caption,
                    parse_mode="HTML"
                )
            )

    await query.answer(results, cache_time=5, is_personal=True)

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
        for row in top_owners:
            owners_text_list.append(f"☛ {get_mention(row['user_id'], row['name'])} — {row['amount']}x")
        owners_str = "\n".join(owners_text_list)
    else:
        owners_str = "☛ <i>မည်သူမျှ မပိုင်ဆိုင်ထားသေးပါ။</i>"

    caption_text = f"""🎗️𝘾𝘼𝙍𝘿 𝙄𝙉𝙁𝙊𝙍𝙈𝘼𝙏𝙄𝙊𝙉 ♡

▰▰▱▱▰▰▱▱▰▰▱▱
🍀 𝘕𝘈𝘔𝘌 : {card['name']}
    🍀  𝘐𝘋 : <code>{card['card_id']}</code>
🎬 𝘛𝘠𝘗𝘌 : {card['type'].upper()}
   🐠𝘎𝘓𝘖𝘉𝘈𝘓 𝘋𝘙𝘖𝘗 𝘊𝘖𝘜𝘕𝘛 : {global_drop_count}

▱▱▰▰▱▱▰▰▱▱▰▰
𝘛𝘖𝘗 𝘖𝘞𝘕𝘌𝘙𝘚 🐾
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

# Message Handler - Counting messages ONLY when no active game is running
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
                    if not coins or coins < 800:
                        del team_creation_state[user.id]
                        return await msg.reply_text("❌ သင့်ထံတွင် Kachi Coin 800 မလုံလောက်တော့ပါသဖြင့် Team တည်ထောင်ခြင်းကို ဖျက်သိမ်းလိုက်ပါသည်။", reply_to_message_id=msg.message_id)

                    # Deduct 800 coins upon successful completion
                    await conn.execute("UPDATE users SET coins = coins - 800 WHERE user_id = $1", user.id)

                    await conn.execute("""
                        INSERT INTO user_teams (team_code, team_name, leader_id, member_limit, logo_file_id, logo_type)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, code, t_name, user.id, t_limit, logo_file_id, logo_type)

                    await conn.execute("""
                        INSERT INTO team_members (team_code, user_id) VALUES ($1, $2)
                    """, code, user.id)

                del team_creation_state[user.id]

                await msg.reply_text("✅ Team တည်ထောင်ခြင်း အောင်မြင်ပါပြီ! (800 Coin နှုတ်ယူပြီးပါပြီ)", reply_to_message_id=msg.message_id)
                await
