import asyncio
import json
import os
import random
import asyncpg
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Environment Variables မှ ယူသုံးခြင်း (Railway Setup အတွက်)
TOKEN = os.getenv("BOT_TOKEN", "8617814117:AAGbTDFaabbt2RUuHSPQDqT9S6WZqiNosvM")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7940553702"))
DATABASE_URL = os.getenv("DATABASE_URL")  # Railway PostgreSQL Connection String

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
game_media = None
result_media = None
global_default_threshold = 10

# Database Connection Pool Global Instance
db_pool = None

async def init_db():
    global db_pool, game_media, result_media, global_default_threshold
    # Connection Pool ဖန်တီးခြင်း (High Concurrency အတွက်)
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                coins BIGINT DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS groups (
                chat_id BIGINT PRIMARY KEY,
                title TEXT,
                added_by_id BIGINT,
                added_by_name TEXT
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
                PRIMARY KEY (user_id, card_id)
            );
        """)

        # Database Schema Update (added_by Columns ထည့်ရန်)
        try:
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_id BIGINT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_name TEXT;")
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

async def add_coins(user_id, amount):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET coins = GREATEST(0, coins + $1) WHERE user_id = $2",
            amount, user_id
        )

def get_mention(user_id, name):
    clean_name = (name or "User").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_id}">{clean_name}</a>'

# /start Command
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    await register_user_group(user, chat)

    bot_info = await context.bot.get_me()
    text = f"""👋 မင်္ဂလာပါ {get_mention(user.id, user.first_name)} !

🌺 𝙆𝘼𝘾𝙃𝙄 𝙂𝘼𝙈𝙀 𝘽𝙊𝙏 မှ ကြိုဆိုပါတယ်။

📌 ဂိမ်းကစားနည်း
- Bot ကို Group တွင် Add ပါ။
- Group အတွင်း စာစကားပြောရင်း သတ်မှတ်စာကြောင်းပြည့်လျှင် Game ကျလာပါမည်။
- မိမိနှစ်သက်ရာ အသင်း သို့မဟုတ် Draw ကို 1 မိနစ်အတွင်း ရွေးချယ်လောင်းကြေးထပ်နိုင်ပါသည်။

ဆုကြေးများ / 𝙋𝙧𝙞𝙘𝙚
- အသင်းနိုင်လျှင်: 10 🩸Kachi Coin
- Draw နိုင်လျှင်: 30 🩸Kachi Coin

🕸️ /kc ဖြင့် မိမိ Coin သို့မဟုတ် ပိုင်ဆိုင်ထားသော Card များ စစ်ဆေးနိုင်ပါသည်။"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("➕ Add To Group", url=f"https://t.me/{bot_info.username}?startgroup=true")
    ]])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

# /c Command
async def set_count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global global_default_threshold
    if update.effective_user.id != ADMIN_ID:
        return
    if update.effective_chat.type != "private":
        return await update.message.reply_text("❌ ဒီ Command ကို Bot DM မွာပဲ သံုးလို့ရပါမယ္။")

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
            parse_mode="Markdown"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ အသုံးပြုနည်း: `/c 6`", parse_mode="Markdown")

# Admin Coin Give/Take (/k id amount)
async def admin_coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            parse_mode="HTML"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ အသုံးပြုနည်း: `/k 1928382 200` သို့မဟုတ် `/k 1928382 -200`", parse_mode="Markdown")

# /add Command (Add Card by Admin)
async def add_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    reply = update.message.reply_to_message
    if not reply or (not reply.photo and not reply.video):
        return await update.message.reply_text("❌ ပုံ သို့မဟုတ် Video ကို Reply ထောက်ပြီး `/add card_id card_name` ဟု ရိုက်ပါ။", parse_mode="Markdown")

    try:
        args = context.args
        if len(args) < 2:
            return await update.message.reply_text("❌ အသုံးပြုနည်း: Reply ထောက်ပြီး `/add [card_id] [card_name]` ရိုက်ပါ (ဥပမာ: `/add 001 Naruto`)", parse_mode="Markdown")
        
        card_id = args[0]
        card_name = " ".join(args[1:])

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

        await update.message.reply_text(f"✅ Card အသစ်ထည့်သွင်းပြီးပါပြီ!\n\n🆔 Card ID: <code>{card_id}</code>\n🎴 Card Name: {card_name}", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ ထည့်သွင်းရာတွင် အမှားအယွင်းရှိပါသည်: {e}")

# /kbox Command (Box Spin Initialization)
async def kbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
        coins = row['coins'] if row else 0

    if coins < 300:
        return await update.message.reply_text(
            f"❌ မင်္ဂလာပါ {get_mention(user.id, user.first_name)}၊ Box လှည့်ရန် Kachi Coin 300 လိုအပ်ပါသည်။\nသင့်ထံတွင် {coins} Coin သာရှိပါသည်။",
            parse_mode="HTML"
        )

    reply_to_msg_id = update.message.message_id
    text = (
        f"{get_mention(user.id, user.first_name)} Box ဖောက်နေပါပြီ၊ ဘယ်ဟာလေး ကံကောင်းသွားမလဲ မစောင့်နိုင်တော့ဘူး..."
    )
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎰 စလှည့်ရန်", callback_data=f"spin_{user.id}")
    ]])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=reply_to_msg_id
    )

# /kc Command
async def check_kc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
        coins = row['coins'] if row else 0

        rank_row = await conn.fetchrow("SELECT COUNT(*) + 1 AS rank FROM users WHERE coins > $1", coins)
        rank = rank_row['rank']

        # ကဒ်များ ဆွဲထုတ်ခြင်း
        user_card_rows = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1
        """, user.id)

    text = f"""◓𝙉𝘼𝙈𝙀〇 {get_mention(user.id, user.first_name)}
        ◒ 𝙸𝙳⊝ <code>{user.id}</code>
◓𝙆𝙖𝙘𝙝𝙞 𝘾𝙤𝙞𝙣⊖ {coins} 🩸
         ◓𝙶𝙻𝙾𝙱𝙰𝙻 𝙽𝙾 ▷ #{rank}"""

    if not user_card_rows:
        text += "\n\n🎴 <i>ပိုင်ဆိုင်ထားသော ကဒ် မရှိသေးပါ။</i>"
        await update.message.reply_text(text, parse_mode="HTML")
    else:
        last_card = user_card_rows[-1]
        cards_info = "\n".join([f"• <b>{c['name']}</b> (ID: <code>{c['card_id']}</code>)" for c in user_card_rows])
        full_text = f"{text}\n\n🎴 <b>ပိုင်ဆိုင်ထားသော ကဒ်များ:</b>\n{cards_info}"

        try:
            if last_card['type'] == 'photo':
                await update.message.reply_photo(photo=last_card['file_id'], caption=full_text, parse_mode="HTML")
            else:
                await update.message.reply_video(video=last_card['file_id'], caption=full_text, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(full_text, parse_mode="HTML")

# /cardlist Command
async def cardlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await render_cardlist_page(update, context, page=0)

async def render_cardlist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    async with db_pool.acquire() as conn:
        cards = await conn.fetch("SELECT card_id, name, type, file_id FROM cards ORDER BY card_id ASC")

    if not cards:
        text = "🎴 **Card List ထဲတွင် ကဒ်များ မရှိသေးပါ။**"
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(text, parse_mode="Markdown")
        else:
            return await update_or_query.edit_message_text(text, parse_mode="Markdown")

    total_cards = len(cards)
    c = cards[page]

    text = f"""🎴 <b>Card List ({page + 1}/{total_cards})</b>

🔸 <b>Card Name:</b> {c['name']}
🆔 <b>Card ID:</b> <code>{c['card_id']}</code>
📂 <b>Type:</b> {c['type'].upper()}"""

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"clist_{page - 1}"))
    if page < total_cards - 1:
        buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"clist_{page + 1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if isinstance(update_or_query, Update):
        if c['type'] == 'photo':
            await update_or_query.message.reply_photo(photo=c['file_id'], caption=text, parse_mode="HTML", reply_markup=markup)
        else:
            await update_or_query.message.reply_video(video=c['file_id'], caption=text, parse_mode="HTML", reply_markup=markup)
    else:
        query = update_or_query
        try:
            media = {"type": c['type'], "media": c['file_id'], "caption": text, "parse_mode": "HTML"}
            from telegram import InputMediaPhoto, InputMediaVideo
            input_media = InputMediaPhoto(c['file_id'], caption=text, parse_mode="HTML") if c['type'] == 'photo' else InputMediaVideo(c['file_id'], caption=text, parse_mode="HTML")
            await query.edit_message_media(media=input_media, reply_markup=markup)
        except Exception:
            await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=markup)

# /glist Command for Admin
async def glist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_glist_page(update, context, page=0)

async def render_glist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    async with db_pool.acquire() as conn:
        groups = await conn.fetch("SELECT chat_id, title, added_by_id, added_by_name FROM groups")

    if not groups:
        text = "🏰 **Group List ခွင့်ပြုထားသော Group မရှိသေးပါ။**"
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(text, parse_mode="Markdown")
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
        buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"glist_{page - 1}"))
    if page < total_groups - 1:
        buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"glist_{page + 1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
    else:
        await update_or_query.edit_message_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)

# Media Commands (/g, /r)
async def media_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        return await update.message.reply_text(f"🗑️ {'Game' if target == 'g' else 'Result'} Media ကို ဖျက်လိုက်ပါပြီ။")

    reply = update.message.reply_to_message
    if not reply:
        return await update.message.reply_text("❌ ပုံ သို့မဟုတ် Video ပို့ထားတဲ့ စာကို Reply ထောက်ပြီး Command ရိုက်ပါ။")

    media_obj = None
    if reply.photo:
        media_obj = {"type": "photo", "file_id": reply.photo[-1].file_id}
    elif reply.video:
        media_obj = {"type": "video", "file_id": reply.video.file_id}
    else:
        return await update.message.reply_text("❌ Photo သို့မဟုတ် Video ဖြင့် Reply တွဲပါ။")

    if target == "g":
        game_media = media_obj
    else:
        result_media = media_obj

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
        """, key, json.dumps(media_obj))

    await update.message.reply_text(f"✅ {'Game' if target == 'g' else 'Result'} Media သတ်မှတ်ပြီးပါပြီ။")

# /stats Command
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:
        u_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        g_count = await conn.fetchval("SELECT COUNT(*) FROM groups")

    await update.message.reply_text(
        f"📊 **Bot Statistics:**\n\n👥 Users: {u_count}\n🏰 Groups: {g_count}",
        parse_mode="Markdown"
    )

# /broadcast Command Fix
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    reply = update.message.reply_to_message
    if not reply:
        return await update.message.reply_text("❌ Broadcast ပို့ချင်သော Message ကို Reply ထောက်ပြီး /broadcast ဟု ရိုက်ပါ။")

    async with db_pool.acquire() as conn:
        users = [r['user_id'] for r in await conn.fetch("SELECT user_id FROM users")]
        groups = [r['chat_id'] for r in await conn.fetch("SELECT chat_id FROM groups")]

    targets = list(set(users + groups))
    await update.message.reply_text(f"🚀 Broadcast စတင်နေပါပြီ... (Target: {len(targets)})")

    success = 0
    for tid in targets:
        try:
            await context.bot.copy_message(
                chat_id=tid,
                from_chat_id=update.effective_chat.id,
                message_id=reply.message_id
            )
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass

    await update.message.reply_text(f"✅ Broadcast ပို့ဆောင်ပြီးပါပြီ! (အောင်မြင်: {success}/{len(targets)})")

# Message Handler
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type not in ["group", "supergroup"]:
        return

    await register_user_group(user, chat)
    chat_id = chat.id

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
        [InlineKeyboardButton("🏰 Top Groups", callback_data="lb_groups")],
    ])

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

    # Countdown Loop
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
    for uid, choice in game_state["bets"].items():
        uname = game_state["user_names"][uid]
        if choice == win_choice:
            reward = 30 if win_choice == "draw" else 10
            await add_coins(uid, reward)
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

# Callbacks
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    user = query.from_user
    data = query.data

    await register_user_group(user, query.message.chat)

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

            # Coin နှုတ်ခြင်း
            await conn.execute("UPDATE users SET coins = coins - 300 WHERE user_id = $1", user.id)

        await query.answer("🎰 Box စတင်လှည့်နေပါပြီ...")

        # 4 Seconds Edit Message Loading Animation
        frames = ["🔄 [▰▱▱▱▱▱▱▱▱▱] Loading 10%...", "🔄 [▰▰▰▰▱▱▱▱▱▱] Loading 40%...", "🔄 [▰▰▰▰▰▰▰▱▱▱] Loading 70%...", "🔄 [▰▰▰▰▰▰▰▰▰▰] Complete!"]
        for frame in frames:
            try:
                await query.edit_message_text(f"🎁 {get_mention(user.id, user.first_name)} မင်္ဂလာပါ!\n\n{frame}", parse_mode="HTML")
            except Exception:
                pass
            await asyncio.sleep(1)

        # Random Card ပေးခြင်း
        won_card = random.choice(cards)

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id) VALUES ($1, $2)
                ON CONFLICT (user_id, card_id) DO NOTHING
            """, user.id, won_card['card_id'])

            rem_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)

        # Loading Message ဖျက်ပြီး Card ပြသခြင်း
        try:
            await query.message.delete()
        except Exception:
            pass

        win_text = f"""🎉 <b>Congratulations {get_mention(user.id, user.first_name)}!</b>

🆔 <b>User ID:</b> <code>{user.id}</code>
💰 <b>Kachi Coin လက်ကျန်:</b> {rem_coins} 🩸

🎴 <b>ရရှိသွားသော Card အချက်အလက်:</b>
🏷️ <b>Name:</b> {won_card['name']}
🔢 <b>Card ID:</b> <code>{won_card['card_id']}</code>"""

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
        page = int(data.replace("clist_", ""))
        await render_cardlist_page(query, context, page=page)
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

    if data == "lb_back":
        original_text = last_results.get(msg_id, "🎗️ 𝗠𝗮𝘁𝗰𝗵 𝗥𝗲𝘀𝘂𝗹𝘁")
        original_markup = get_leaderboard_buttons()
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=original_text, parse_mode="HTML", reply_markup=original_markup)
            else:
                await query.edit_message_text(text=original_text, parse_mode="HTML", reply_markup=original_markup)
        except Exception:
            pass
        await query.answer()
        return

    if data.startswith("lb_"):
        lb_type = data.replace("lb_", "")
        async with db_pool.acquire() as conn:
            if lb_type in ["gp", "global"]:
                rows = await conn.fetch("SELECT name, coins FROM users ORDER BY coins DESC LIMIT 10")
                title = "🏆 <b>Top 10 In Group</b>" if lb_type == "gp" else "🌍 <b>Global Top 10 Users</b>"
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {r['name']} — {r['coins']} 🩸Kachi Coin" for i, r in enumerate(rows)])
            elif lb_type == "groups":
                rows = await conn.fetch("SELECT title FROM groups LIMIT 10")
                text = "🏰 <b>Top 10 Groups</b>\n\n" + "\n".join([f"{i+1}. {r['title']}" for i, r in enumerate(rows)])

        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="lb_back")]])
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

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("c", set_count_cmd))
    app.add_handler(CommandHandler("kc", check_kc_cmd))
    app.add_handler(CommandHandler("glist", glist_cmd))
    app.add_handler(CommandHandler(["g", "r"], media_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    
    # Newly Added Handlers
    app.add_handler(CommandHandler("k", admin_coin_cmd))
    app.add_handler(CommandHandler("add", add_card_cmd))
    app.add_handler(CommandHandler("kbox", kbox_cmd))
    app.add_handler(CommandHandler("cardlist", cardlist_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))

    print("🤖 Python Game Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
