import asyncio
import json
import os
import random
import string
import time
import uuid
import asyncpg
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto, InputMediaVideo, InlineQueryResultCachedPhoto, InlineQueryResultCachedVideo, ChatPermissions
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    InlineQueryHandler,
)

# Environment Variables
TOKEN = os.getenv("BOT_TOKEN", "8617814117:AAGbTDFaabbt2RUuHSPQDqT9S6WZqiNosvM")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7940553702"))
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "@beyondpoe")

# Global Memory Stores
group_threshold = {}
pending_gifts = {}
active_card_drops = {}
pending_card_adds = {}
pending_quizzes = {}
active_quizzes = {}
pending_kachi_transfers = {}
global_default_threshold = 60
bot_warned_groups = set()

# Anti-Spam Tracking Stores
user_message_timestamps = {}
spam_ignores = {}

# Database Connection Pool
db_pool = None

async def init_db():
    global db_pool, global_default_threshold
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                coins BIGINT DEFAULT 1000,
                selected_card_id TEXT,
                is_card_admin BOOLEAN DEFAULT FALSE,
                started_in_pm BOOLEAN DEFAULT FALSE,
                banned BOOLEAN DEFAULT FALSE,
                ban_reason TEXT,
                muted_until BIGINT DEFAULT 0,
                mute_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS groups (
                chat_id BIGINT PRIMARY KEY,
                title TEXT,
                added_by_id BIGINT,
                added_by_name TEXT,
                threshold INT DEFAULT 60,
                msg_count INT DEFAULT 0
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
                file_id TEXT,
                rarity TEXT
            );
            CREATE TABLE IF NOT EXISTS user_cards (
                user_id BIGINT,
                card_id TEXT,
                amount INT DEFAULT 1,
                PRIMARY KEY (user_id, card_id)
            );
        """)

        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS selected_card_id TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_card_admin BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS started_in_pm BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS muted_until BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mute_reason TEXT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_id BIGINT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_name TEXT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS threshold INT DEFAULT 60;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS msg_count INT DEFAULT 0;")
            await conn.execute("ALTER TABLE user_cards ADD COLUMN IF NOT EXISTS amount INT DEFAULT 1;")
            await conn.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS rarity TEXT;")
        except Exception:
            pass

        db_groups = await conn.fetch("SELECT chat_id, threshold FROM groups")
        for g in db_groups:
            if g['threshold'] is not None:
                group_threshold[g['chat_id']] = g['threshold']

        existing_cards = await conn.fetch("SELECT card_id, type FROM cards WHERE rarity IS NULL")
        for c in existing_cards:
            r = random.choices(["Shinsei", "Kiwami", "Kami", "Hoshi", "Ten"], weights=[3, 8, 20, 35, 37], k=1)[0]
            await conn.execute("UPDATE cards SET rarity = $1 WHERE card_id = $2", r, c['card_id'])

        thresh_row = await conn.fetchrow("SELECT value FROM settings WHERE key='default_threshold'")
        if thresh_row:
            global_default_threshold = int(thresh_row['value'])

# Bot-level Ban & Mute Restriction Decorator
def restricted_command(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        msg = update.effective_message
        if user and not user.is_bot and user.id != ADMIN_ID:
            async with db_pool.acquire() as conn:
                user_row = await conn.fetchrow(
                    "SELECT banned, ban_reason, muted_until, mute_reason FROM users WHERE user_id = $1",
                    user.id
                )
                if user_row:
                    now = int(time.time())
                    if user_row['banned']:
                        reason = user_row['ban_reason'] or 'No reason provided'
                        if msg:
                            await msg.reply_text(
                                f"❌ <b>You are banned from using this bot.</b>\n📝 Reason: {reason}",
                                parse_mode="HTML",
                                reply_to_message_id=msg.message_id
                            )
                        return
                    if user_row['muted_until'] and user_row['muted_until'] > now:
                        remaining = user_row['muted_until'] - now
                        mins = remaining // 60
                        secs = remaining % 60
                        time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
                        reason = user_row['mute_reason'] or 'No reason provided'
                        if msg:
                            await msg.reply_text(
                                f"🔇 <b>You are muted from using this bot.</b>\n⏳ Time remaining: {time_str}\n📝 Reason: {reason}",
                                parse_mode="HTML",
                                reply_to_message_id=msg.message_id
                            )
                        return
        return await func(update, context)
    return wrapper

async def register_user_group(user, chat, context: ContextTypes.DEFAULT_TYPE = None):
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            if user and not user.is_bot:
                await conn.execute("""
                    INSERT INTO users (user_id, name, coins) VALUES ($1, $2, 1000)
                    ON CONFLICT(user_id) DO UPDATE SET name = EXCLUDED.name
                """, user.id, user.first_name)
            if chat and chat.type in ["group", "supergroup"]:
                added_id = user.id if user and not user.is_bot else None
                added_name = user.first_name if user and not user.is_bot else None
                
                is_new = await conn.fetchrow("SELECT chat_id FROM groups WHERE chat_id = $1", chat.id)
                
                await conn.execute("""
                    INSERT INTO groups (chat_id, title, added_by_id, added_by_name) 
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(chat_id) DO UPDATE SET 
                        title = EXCLUDED.title,
                        added_by_id = COALESCE(groups.added_by_id, EXCLUDED.added_by_id),
                        added_by_name = COALESCE(groups.added_by_name, EXCLUDED.added_by_name)
                """, chat.id, chat.title or "Group", added_id, added_name)

                group_row = await conn.fetchrow("SELECT threshold FROM groups WHERE chat_id = $1", chat.id)
                if group_row and group_row['threshold'] is not None:
                    group_threshold[chat.id] = group_row['threshold']

                if not is_new and context and added_id:
                    try:
                        member_count = await context.bot.get_chat_member_count(chat.id)
                    except Exception:
                        member_count = "N/A"

                    invite_link = "N/A"
                    try:
                        chat_obj = await context.bot.get_chat(chat.id)
                        if chat_obj.invite_link:
                            invite_link = chat_obj.invite_link
                        elif chat_obj.username:
                            invite_link = f"https://t.me/{chat_obj.username}"
                        else:
                            invite_link = await context.bot.export_chat_invite_link(chat.id)
                    except Exception:
                        pass

                    adder_text = get_mention(added_id, added_name or "User") if added_id else "—"
                    log_text = f"""🏰 <b>New Group Added</b>

🔹 <b>Group Name:</b> {chat.title or 'Group'}
👥 <b>Members:</b> {member_count}
🆔 <b>Group ID:</b> <code>{chat.id}</code>
🔗 <b>Link:</b> {invite_link}
👤 <b>Added By:</b> {adder_text}"""
                    try:
                        await context.bot.send_message(ADMIN_ID, log_text, parse_mode="HTML", disable_web_page_preview=True)
                    except Exception:
                        pass

                if user and not user.is_bot:
                    await conn.execute("""
                        INSERT INTO group_members (chat_id, user_id) VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                    """, chat.id, user.id)
    except Exception as e:
        print(f"Error in register_user_group: {e}")

async def add_coins(user_id, amount):
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user_id)
        current_coins = user_row['coins'] if user_row else 1000
        new_coins = max(0, current_coins + amount)
        await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_coins, user_id)

def get_mention(user_id, name):
    clean_name = (name or "User").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_id}">{clean_name}</a>'

async def get_weighted_random_card(conn):
    all_cards = await conn.fetch("SELECT card_id, name, type, file_id, rarity FROM cards")
    if not all_cards:
        return None
    return random.choice(all_cards)

async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user or user.is_bot:
        return True
    if user.id == ADMIN_ID:
        return True
    
    try:
        member = await context.bot.get_chat_member(chat_id="@beyondpoe", user_id=user.id)
        if member.status in ['left', 'kicked']:
            raise Exception("Not joined")
        return True
    except Exception:
        text = f"🐠 Hello {get_mention(user.id, user.first_name)}, please join our channel to use the bot 🩸"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Channel 📢", url="https://t.me/beyondpoe")],
            [InlineKeyboardButton("Joined ✅", callback_data=f"check_join_{user.id}")]
        ])
        if update.message:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=update.message.message_id)
        elif update.callback_query:
            await update.callback_query.answer("❌ Please join the channel first.", show_alert=True)
        return False

# Quiz Commands (/aa and /send)
@restricted_command
async def aa_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    
    is_allowed = (user.id == ADMIN_ID)
    if not is_allowed:
        async with db_pool.acquire() as conn:
            u_info = await conn.fetchrow("SELECT is_card_admin FROM users WHERE user_id = $1", user.id)
            if u_info and u_info['is_card_admin']:
                is_allowed = True

    if not is_allowed:
        return

    full_text = msg.text.partition(" ")[2].strip()
    if not full_text:
        return await msg.reply_text("❌ Usage: `/aa မေးခွန်း / အဖြေ၁ / အဖြေ၂ / အဖြေ၃ ...`", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    if "/" in full_text:
        parts = [p.strip() for p in full_text.split("/")]
    else:
        parts = [p.strip() for p in full_text.split(".")]

    if len(parts) < 3:
        return await msg.reply_text("❌ အနည်းဆုံး မေးခွန်း ၁ ခုနှင့် အဖြေ ၂ ခု ထည့်ပေးရပါမည်။ ဥပမာ: `/aa မေးခွန်း / အဖြေ၁ / အဖြေ၂`", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    question = parts[0]
    options = parts[1:]

    preview_text = f"❓ <b>Trivia Quiz Preview</b>\n\n<b>{question}</b>\n\n<i>👇 ကျေးဇူးပြု၍ အောက်ပါခလုတ်များမှ အဖြေမှန်ကို ရွေးချယ်ပေးပါ -</i>"
    
    keyboard = []
    for idx, opt in enumerate(options):
        keyboard.append([InlineKeyboardButton(f"📌 {opt}", callback_data="aa_noop")])
    
    select_row = []
    for idx, opt in enumerate(options):
        select_row.append(InlineKeyboardButton(f"✅ အဖြေမှန် ({idx+1})", callback_data=f"aa_sel_{idx}"))
    keyboard.append(select_row)

    sent = await msg.reply_text(preview_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard), reply_to_message_id=msg.message_id)
    
    pending_quizzes[sent.message_id] = {
        "question": question,
        "options": options,
        "correct": None
    }

@restricted_command
async def send_quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message

    is_allowed = (user.id == ADMIN_ID)
    if not is_allowed:
        async with db_pool.acquire() as conn:
            u_info = await conn.fetchrow("SELECT is_card_admin FROM users WHERE user_id = $1", user.id)
            if u_info and u_info['is_card_admin']:
                is_allowed = True

    if not is_allowed:
        return

    reply = msg.reply_to_message
    if not reply or reply.message_id not in pending_quizzes:
        return await msg.reply_text("❌ Please reply to the quiz preview message with `/send`.", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    quiz_data = pending_quizzes[reply.message_id]
    if not quiz_data.get('correct'):
        return await msg.reply_text("❌ ကျေးဇူးပြု၍ Quiz ပုံစံတွင် အဖြေမှန်ကို အရင်ဆုံး inline button နှိပ်၍ ရွေးချယ်ပေးပါ။", reply_to_message_id=msg.message_id)

    async with db_pool.acquire() as conn:
        groups = await conn.fetch("SELECT chat_id FROM groups")

    quiz_id = str(uuid.uuid4())[:8]

    success_count = 0
    for g in groups:
        chat_id = g['chat_id']
        try:
            member_count = await context.bot.get_chat_member_count(chat_id)
            if member_count <= 30:
                continue
        except Exception:
            continue

        try:
            keyboard = []
            for idx, opt in enumerate(quiz_data['options']):
                keyboard.append([InlineKeyboardButton(opt, callback_data=f"ans_{quiz_id}_{idx}")])

            quiz_text = f"❓ <b>Kachi Trivia Quiz</b>\n\n<b>{quiz_data['question']}</b>"

            sent_quiz = await context.bot.send_message(
                chat_id=chat_id,
                text=quiz_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

            active_quizzes[sent_quiz.message_id] = {
                "chat_id": chat_id,
                "question": quiz_data['question'],
                "options": quiz_data['options'],
                "correct": quiz_data['correct'],
                "solved": False,
                "answered_users": set(),
                "wrong_users": set()
            }
            success_count += 1
        except Exception:
            pass

    await msg.reply_text(f"✅ Quiz broadcasted to {success_count} groups (members > 30) successfully!", reply_to_message_id=msg.message_id)

# /start Command
@restricted_command
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    if not await check_force_join(update, context):
        return

    if context.args and context.args[0].startswith("kachi_"):
        try:
            target_id = int(context.args[0].replace("kachi_", ""))
            if target_id == user.id:
                return await update.message.reply_text("❌ You cannot transfer Kachi to yourself.", reply_to_message_id=msg_id)
            
            pending_kachi_transfers[user.id] = target_id
            async with db_pool.acquire() as conn:
                target_row = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
                target_name = target_row['name'] if target_row else "User"

            return await update.message.reply_text(
                f"💸 <b>Kachi Transfer</b>\n\n"
                f"You are sending Kachi to <b>{target_name}</b> (ID: <code>{target_id}</code>).\n"
                f"Please enter the amount of Kachi you want to send:",
                parse_mode="HTML",
                reply_to_message_id=msg_id
            )
        except ValueError:
            pass

    bot_info = await context.bot.get_me()
    text = f"""👋 မင်္ဂလာပါ {get_mention(user.id, user.first_name)} !

🌺 Kachi Card 𝙂𝘼𝙈𝙀 𝘽𝙊𝙏 မှ ကြိုဆိုပါတယ်!

📌 <b>အသုံးပြုပုံ ညွှန်ကြားချက်များ -</b>
- Bot ကို Group ထဲသို့ ထည့်ပါ။
- Group ထဲတွင် စာပေးပို့ပါ (သတ်မှတ်ထားသော စာအရေအတွက်ပြည့်ပါက ကတ်များ အလိုအလျောက် ကျလာပါမည်)။
- ဦးဆောင်သူစာရင်းများကို ကြည့်ရန် /ktop ကို အသုံးပြုပါ။"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Help 📖", callback_data="menu_help"),
            InlineKeyboardButton("Gift 🎁", callback_data="menu_kgift")
        ],
        [
            InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{bot_info.username}?startgroup=true")
        ]
    ])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

# /addadmin Command
@restricted_command
async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/addadmin [user_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        target_id = int(context.args[0])
        async with db_pool.acquire() as conn:
            user_exists = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
            if not user_exists:
                await conn.execute("INSERT INTO users (user_id, name, coins) VALUES ($1, 'User', 1000)", target_id)
            await conn.execute("UPDATE users SET is_card_admin = TRUE WHERE user_id = $1", target_id)

        await update.message.reply_text(f"✅ User ID <code>{target_id}</code> is now a Card Admin.", parse_mode="HTML", reply_to_message_id=msg_id)
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

# /admin Command
@restricted_command
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    text = """⚡ <b>Admin Commands</b>

👑 <b>List:</b>
1. /aa - Create trivia quiz
2. /send - Broadcast quiz to groups (reply to /aa)
3. /c [gpid] [count] - Set threshold for a specific group
4. /crest - Reset all thresholds & message counts
5. /k [user_id] [amount] - Add/remove Kachi
6. /addadmin [user_id] - Add Card Admin
7. /add - Add new card (reply to media)
8. /del [card_id] - Delete card
9. /cardlist - View all cards
10. /glist - View groups list
11. /stats - View stats
12. /broadcast - Broadcast message
13. /check [user_id] - Check user profile info
14. /mute [id] [time] [reason] - Mute user from bot usage
15. /ban [id] [reason] - Ban user from bot usage
16. /umute [id] - Unmute user from bot usage
17. /unban [id] - Unban user from bot usage
18. /spw [id] - Spawn random card or specific card by ID"""

    await update.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)

# Bot-level Moderation Commands (/mute, /ban, /umute, /unban)
def parse_time(time_str: str) -> int:
    time_str = time_str.lower().strip()
    mult = 1
    if time_str.endswith('s'):
        mult = 1
        time_str = time_str[:-1]
    elif time_str.endswith('m'):
        mult = 60
        time_str = time_str[:-1]
    elif time_str.endswith('h'):
        mult = 3600
        time_str = time_str[:-1]
    elif time_str.endswith('d'):
        mult = 86400
        time_str = time_str[:-1]
    try:
        return int(time_str) * mult
    except ValueError:
        return 60

@restricted_command
async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        return await msg.reply_text("❌ Usage: `/mute [user_id] [time] [reason]`", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    try:
        target_id = int(context.args[0])
        time_str = context.args[1]
        reason = " ".join(context.args[2:]) if len(context.args) > 2 else "No reason provided"
    except ValueError:
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg.message_id)

    seconds = parse_time(time_str)
    until_timestamp = int(time.time()) + seconds

    async with db_pool.acquire() as conn:
        user_exists = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
        if not user_exists:
            await conn.execute("INSERT INTO users (user_id, name, coins, muted_until, mute_reason) VALUES ($1, 'User', 1000, $2, $3)", target_id, until_timestamp, reason)
        else:
            await conn.execute("UPDATE users SET muted_until = $1, mute_reason = $2 WHERE user_id = $3", until_timestamp, reason, target_id)

    await msg.reply_text(
        f"🔇 <b>Muted User from Bot</b>\n\n👤 User ID: <code>{target_id}</code>\n⏳ Duration: {time_str}\n📝 Reason: {reason}",
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )

@restricted_command
async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if user.id != ADMIN_ID:
        return

    if not context.args:
        return await msg.reply_text("❌ Usage: `/ban [user_id] [reason]`", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    try:
        target_id = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason provided"
    except ValueError:
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg.message_id)

    async with db_pool.acquire() as conn:
        user_exists = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
        if not user_exists:
            await conn.execute("INSERT INTO users (user_id, name, coins, banned, ban_reason) VALUES ($1, 'User', 1000, TRUE, $2)", target_id, reason)
        else:
            await conn.execute("UPDATE users SET banned = TRUE, ban_reason = $1 WHERE user_id = $2", reason, target_id)

    await msg.reply_text(
        f"🔨 <b>Banned User from Bot</b>\n\n👤 User ID: <code>{target_id}</code>\n📝 Reason: {reason}",
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )

@restricted_command
async def umute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if user.id != ADMIN_ID:
        return

    if not context.args:
        return await msg.reply_text("❌ Usage: `/umute [user_id]`", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    try:
        target_id = int(context.args[0])
    except ValueError:
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg.message_id)

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET muted_until = 0, mute_reason = NULL WHERE user_id = $1", target_id)

    await msg.reply_text(
        f"🔊 <b>Unmuted User from Bot</b>\n\n👤 User ID: <code>{target_id}</code>",
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )

@restricted_command
async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if user.id != ADMIN_ID:
        return

    if not context.args:
        return await msg.reply_text("❌ Usage: `/unban [user_id]`", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    try:
        target_id = int(context.args[0])
    except ValueError:
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg.message_id)

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET banned = FALSE, ban_reason = NULL WHERE user_id = $1", target_id)

    await msg.reply_text(
        f"🔓 <b>Unbanned User from Bot</b>\n\n👤 User ID: <code>{target_id}</code>",
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )

@restricted_command
async def check_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if user.id != ADMIN_ID:
        return

    if not context.args:
        return await msg.reply_text("❌ Usage: `/check [user_id]`", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    try:
        target_id = int(context.args[0])
    except ValueError:
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg.message_id)

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT coins, selected_card_id, name FROM users WHERE user_id = $1", target_id)
        if not user_row:
            return await msg.reply_text(f"❌ User ID <code>{target_id}</code> not found in database.", parse_mode="HTML", reply_to_message_id=msg.message_id)

        coins = user_row['coins'] or 1000
        selected_card_id = user_row['selected_card_id']
        db_name = user_row['name'] or "User"

        rank_row = await conn.fetchrow("""
            SELECT COUNT(*) + 1 AS rank FROM (
                SELECT u.user_id, COALESCE(SUM(uc.amount), 0) as tc
                FROM users u
                LEFT JOIN user_cards uc ON u.user_id = uc.user_id
                GROUP BY u.user_id
            ) sub WHERE tc > (
                SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE user_id = $1
            )
        """, target_id)
        rank = rank_row['rank'] if rank_row else 1

        user_card_rows = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, uc.amount 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1 AND uc.amount > 0
            ORDER BY c.card_id ASC
        """, target_id)

    username_str = "None"
    try:
        chat_obj = await context.bot.get_chat(target_id)
        if chat_obj.username:
            username_str = f"@{chat_obj.username}"
        if chat_obj.first_name:
            db_name = chat_obj.first_name
    except Exception:
        pass

    text_header = f"""❀ Name - {get_mention(target_id, db_name)}
🌐 Global Rank - #{rank}
🏷 Username - {username_str}
⬤ ID - <code>{target_id}</code>
🩸 Kachi - <b>{coins}</b>"""

    cards_info_list = []
    for c in user_card_rows[:5]:
        count_str = f" <b>({c['amount']}x)</b>" if c['amount'] > 1 else ""
        rarity_emoji = "🧬" if c.get('rarity') == 'Shinsei' else ("🪞" if c.get('rarity') == 'Kiwami' else ("✨" if c.get('rarity') == 'Kami' else ("⚜️" if c.get('rarity') == 'Hoshi' else "💮")))
        cards_info_list.append(f"{rarity_emoji} {c['name']} ( <code>{c['card_id']}</code> ){count_str}")

    cards_info = "\n".join(cards_info_list) if cards_info_list else "<i>No cards yet.</i>"
    full_text = f"{text_header}\n\n❄ <b>Owned Cards</b>\n\n{cards_info}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Harem❄", switch_inline_query_current_chat=f"harem.{target_id}")]
    ])

    active_card = None
    if selected_card_id:
        active_card = next((c for c in user_card_rows if c['card_id'] == selected_card_id), None)
    if not active_card and user_card_rows:
        active_card = user_card_rows[-1]

    try:
        if active_card and active_card['type'] == 'photo':
            await msg.reply_photo(photo=active_card['file_id'], caption=full_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg.message_id)
        elif active_card and active_card['type'] == 'video':
            await msg.reply_video(video=active_card['file_id'], caption=full_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg.message_id)
        else:
            await msg.reply_text(full_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg.message_id)
    except Exception:
        await msg.reply_text(full_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg.message_id)

@restricted_command
async def crest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    global group_threshold, global_default_threshold
    group_threshold.clear()
    global_default_threshold = 60

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE groups SET threshold = 60, msg_count = 0")
        await conn.execute("DELETE FROM settings WHERE key = 'default_threshold'")

    await update.message.reply_text("✅ All group thresholds and message counts have been reset to default (60). Card drops will only trigger when new message thresholds are met.", parse_mode="HTML", reply_to_message_id=msg_id)

@restricted_command
async def ktop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    msg_id = update.message.message_id
    async with db_pool.acquire() as conn:
        top_users = await conn.fetch("""
            SELECT u.user_id, u.name, COALESCE(SUM(uc.amount), 0) AS total_cards
            FROM users u
            LEFT JOIN user_cards uc ON u.user_id = uc.user_id
            GROUP BY u.user_id, u.name
            ORDER BY total_cards DESC, u.coins DESC
            LIMIT 10
        """)

    lines = [
        "KTOP GLOBAL🌍 ( Leaderboard ) 🎖",
        "▰▱▰▱▰▱▰▱▰▱▰",
        ""
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i in range(10):
        prefix = medals[i] if i < 3 else "☛"
        if i < len(top_users):
            r = top_users[i]
            mention = get_mention(r['user_id'], r['name'])
            lines.append(f"{prefix} {mention} - {r['total_cards']} Cards")
        else:
            lines.append(f"{prefix}")
    lines.append("")
    lines.append("▰▱▰▱▰▱▰▱▰▱▰")
    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)

@restricted_command
async def kgtop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    chat = update.effective_chat
    msg_id = update.message.message_id
    if chat.type not in ["group", "supergroup"]:
        return await update.message.reply_text("❌ This command can only be used in groups.", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        top_users = await conn.fetch("""
            SELECT u.user_id, u.name, COALESCE(SUM(uc.amount), 0) AS total_cards
            FROM users u
            JOIN group_members gm ON u.user_id = gm.user_id
            LEFT JOIN user_cards uc ON u.user_id = uc.user_id
            WHERE gm.chat_id = $1
            GROUP BY u.user_id, u.name
            ORDER BY total_cards DESC, u.coins DESC
            LIMIT 10
        """, chat.id)

    lines = [
        "KTOP IN GROUP🦊",
        "    ( Leaderboard ) 🎖",
        "▰▱▰▱▰▱▰▱▰▱▰▱",
        ""
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i in range(10):
        prefix = medals[i] if i < 3 else "☛"
        if i < len(top_users):
            r = top_users[i]
            mention = get_mention(r['user_id'], r['name'])
            lines.append(f"{prefix} {mention} - {r['total_cards']} Cards")
        else:
            lines.append(f"{prefix}")
    lines.append("▰▱▰▱▰▱▰▱▰▱▰▱")
    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)

@restricted_command
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
                await conn.execute("INSERT INTO users (user_id, name, coins) VALUES ($1, $2, 1000)", target_id, "User")
            
            user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", target_id)
            current_coins = user_row['coins'] if user_row else 1000
            new_coins = max(0, current_coins + amount)
            await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_coins, target_id)
            new_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1", target_id)

        action_text = "added" if amount >= 0 else "deducted"
        await update.message.reply_text(
            f"✅ {abs(amount)} Kachi {action_text} to {get_mention(target_id, new_row['name'])}.\n"
            f"💰 Current Kachi: <b>{new_row['coins']}</b>",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/k [user_id] [amount]`", parse_mode="Markdown", reply_to_message_id=msg_id)

@restricted_command
async def add_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    user = update.effective_user

    async with db_pool.acquire() as conn:
        u_info = await conn.fetchrow("SELECT is_card_admin FROM users WHERE user_id = $1", user.id)
        is_card_admin = u_info['is_card_admin'] if u_info else False

    if user.id != ADMIN_ID and not is_card_admin:
        return

    reply = update.message.reply_to_message
    if not reply or (not reply.photo and not reply.video):
        return await update.message.reply_text("❌ Reply to a photo or video with `/add [name]` or `/add [id].[name]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    raw_args = update.message.text.partition(" ")[2].strip()
    if not raw_args:
        return await update.message.reply_text("❌ Usage: Reply to media with `/add [name]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    card_id = None
    card_name = None

    if "." in raw_args:
        part1, _, part2 = raw_args.partition(".")
        card_id = part1.strip()
        card_name = part2.strip()
    else:
        async with db_pool.acquire() as conn:
            while True:
                rand_id = str(random.randint(1000, 9999))
                exists = await conn.fetchrow("SELECT card_id FROM cards WHERE card_id = $1", rand_id)
                if not exists:
                    card_id = rand_id
                    break
        card_name = raw_args

    if reply.photo:
        file_id = reply.photo[-1].file_id
        c_type = "photo"
    else:
        file_id = reply.video.file_id
        c_type = "video"

    async with db_pool.acquire() as conn:
        existing_card = await conn.fetchrow("SELECT card_id FROM cards WHERE card_id = $1 OR file_id = $2", card_id, file_id)
        if existing_card:
            return await update.message.reply_text(f"⚠️ Card ID (<code>{card_id}</code>) or media already exists.", parse_mode="HTML", reply_to_message_id=msg_id)

    pending_card_adds[user.id] = {
        "card_id": card_id,
        "card_name": card_name,
        "type": c_type,
        "file_id": file_id,
        "is_card_admin": is_card_admin
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧬 Shinsei", callback_data=f"addrarity_{user.id}_Shinsei"),
            InlineKeyboardButton("🪞 Kiwami", callback_data=f"addrarity_{user.id}_Kiwami")
        ],
        [
            InlineKeyboardButton("✨ Kami", callback_data=f"addrarity_{user.id}_Kami"),
            InlineKeyboardButton("⚜️ Hoshi", callback_data=f"addrarity_{user.id}_Hoshi")
        ],
        [
            InlineKeyboardButton("💮 Ten", callback_data=f"addrarity_{user.id}_Ten")
        ]
    ])

    await update.message.reply_text(
        f"🎴 <b>Card Info Ready:</b>\n"
        f"🆔 ID: <code>{card_id}</code>\n"
        f"🏷 Name: {card_name}\n\n"
        f"Please select rarity:",
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=msg_id
    )

@restricted_command
async def del_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/del [card_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_card_id = context.args[0].strip()

    async with db_pool.acquire() as conn:
        card = await conn.fetchrow("SELECT name FROM cards WHERE card_id = $1", target_card_id)
        if not card:
            return await update.message.reply_text(f"❌ Card ID <code>{target_card_id}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

        await conn.execute("DELETE FROM user_cards WHERE card_id = $1", target_card_id)
        await conn.execute("DELETE FROM cards WHERE card_id = $1", target_card_id)
        await conn.execute("UPDATE users SET selected_card_id = NULL WHERE selected_card_id = $1", target_card_id)

    await update.message.reply_text(f"✅ Card ID <code>{target_card_id}</code> (<b>{card['name']}</b>) deleted successfully.", parse_mode="HTML", reply_to_message_id=msg_id)

@restricted_command
async def set_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/set [Card_ID]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_card_id = context.args[0]

    async with db_pool.acquire() as conn:
        has_card = await conn.fetchrow("""
            SELECT c.name FROM user_cards uc
            JOIN cards c ON uc.card_id = c.card_id
            WHERE uc.user_id = $1 AND uc.card_id = $2
        """, user.id, target_card_id)

        if not has_card:
            return await update.message.reply_text(f"❌ You do not own Card ID <code>{target_card_id}</code>.", parse_mode="HTML", reply_to_message_id=msg_id)

        await conn.execute("UPDATE users SET selected_card_id = $1 WHERE user_id = $2", target_card_id, user.id)

    await update.message.reply_text(f"✅ Active profile card changed to <b>{has_card['name']}</b> for /kc.", parse_mode="HTML", reply_to_message_id=msg_id)

@restricted_command
async def kgift_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    sender = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    reply_msg = update.message.reply_to_message

    if not reply_msg or not reply_msg.from_user or reply_msg.from_user.is_bot:
        return await update.message.reply_text("❌ Reply to a user's message to send a gift.", reply_to_message_id=msg_id)

    receiver = reply_msg.from_user
    if sender.id == receiver.id:
        return await update.message.reply_text("❌ Cannot send gifts to yourself.", reply_to_message_id=msg_id)

    await register_user_group(sender, chat, context)
    await register_user_group(receiver, chat, context)

    if not context.args:
        return await update.message.reply_text("❌ Usage: Reply with `/kgift [card_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    card_id = context.args[0].strip()
    async with db_pool.acquire() as conn:
        card = await conn.fetchrow("SELECT card_id, name, type, file_id FROM cards WHERE card_id = $1", card_id)
        if not card:
            return await update.message.reply_text(f"❌ Card ID <code>{card_id}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

        user_card = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", sender.id, card_id)
        if not user_card or user_card['amount'] <= 0:
            return await update.message.reply_text(f"❌ You do not own Card ID <code>{card_id}</code> (<b>{card['name']}</b>).", reply_to_message_id=msg_id)

    text = f"""🎁 <b>Kachi Card Gift Transfer</b>

👤 <b>Sender:</b> {get_mention(sender.id, sender.first_name)}
👤 <b>Receiver:</b> {get_mention(receiver.id, receiver.first_name)}

🎴 <b>Card Info:</b>
🏷️ <b>Name:</b> {card['name']}
🆔 <b>Card ID:</b> <code>{card['card_id']}</code>

<i>Click button below to confirm.</i>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Cancel ❌", callback_data=f"gift_cancel_{sender.id}"),
        InlineKeyboardButton("Confirm Gift 🎁", callback_data=f"gift_confirm_{sender.id}")
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

async def render_kc_view(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0, owner_id: int = None):
    user = update_or_query.effective_user if isinstance(update_or_query, Update) else update_or_query.from_user
    target_id = owner_id if owner_id else user.id
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT selected_card_id, name FROM users WHERE user_id = $1", target_id)
        selected_card_id = user_row['selected_card_id'] if user_row else None
        display_name = user_row['name'] if user_row else user.first_name

        rank_row = await conn.fetchrow("""
            SELECT COUNT(*) + 1 AS rank FROM (
                SELECT u.user_id, COALESCE(SUM(uc.amount), 0) as tc
                FROM users u
                LEFT JOIN user_cards uc ON u.user_id = uc.user_id
                GROUP BY u.user_id
            ) sub WHERE tc > (
                SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE user_id = $1
            )
        """, target_id)
        global_rank = rank_row['rank'] if rank_row else 1

        user_card_rows = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, uc.amount 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1 AND uc.amount > 0
            ORDER BY c.card_id ASC
        """, target_id)

    total_owned_sum = sum(c['amount'] for c in user_card_rows)

    per_page = 8
    total_cards = len(user_card_rows)
    total_pages = (total_cards + per_page - 1) // per_page if total_cards > 0 else 1
    page = max(0, min(page, total_pages - 1))

    page_str = f" ({page + 1}/{total_pages})"
    text_header = f"""❀ 𝗡𝗮𝗺𝗲 - {get_mention(target_id, display_name)}
🌐 𝗚𝗹𝗼𝗯𝗮𝗹 𝗥𝗮𝗻𝗸 - #{global_rank}

𝗛𝗮𝗿𝗲𝗺 𝗣𝗮𝗴𝗲{page_str}"""

    if not user_card_rows:
        full_text = f"{text_header}\n\n<i>No cards yet.</i>"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"Harem❄ ({total_owned_sum})", switch_inline_query_current_chat=f"harem.{target_id}")
            ]
        ])
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(full_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        else:
            return await update_or_query.edit_message_caption(caption=full_text, parse_mode="HTML", reply_markup=keyboard)

    active_card = None
    if selected_card_id:
        active_card = next((c for c in user_card_rows if c['card_id'] == selected_card_id), None)
    if not active_card:
        active_card = user_card_rows[-1]

    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_page_cards = user_card_rows[start_idx:end_idx]

    cards_info_list = []
    for c in current_page_cards:
        count_str = f" <b>({c['amount']}x)</b>" if c['amount'] > 1 else " 1x"
        rarity_emoji = "🧬" if c.get('rarity') == 'Shinsei' else ("🪞" if c.get('rarity') == 'Kiwami' else ("✨" if c.get('rarity') == 'Kami' else ("⚜️" if c.get('rarity') == 'Hoshi' else "💮")))
        cards_info_list.append(f"🍀 {c['name']} {rarity_emoji} 🧩 [ <code>{c['card_id']}</code> ]{count_str}")

    cards_info = "\n".join(cards_info_list)
    full_text = f"{text_header}\n\n{cards_info}"

    keyboard_rows = []
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("◀️ Back", callback_data=f"kcpage_{page - 1}_{target_id}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"kcpage_{page + 1}_{target_id}"))
        if nav_row:
            keyboard_rows.append(nav_row)

    keyboard_rows.append([
        InlineKeyboardButton(f"Harem❄ ({total_owned_sum})", switch_inline_query_current_chat=f"harem.{target_id}")
    ])
    markup = InlineKeyboardMarkup(keyboard_rows)

    if isinstance(update_or_query, Update):
        try:
            if active_card['type'] == 'photo':
                await update_or_query.message.reply_photo(photo=active_card['file_id'], caption=full_text, parse_mode="HTML", reply_markup=markup, reply_to_message_id=msg_id)
            else:
                await update_or_query.message.reply_video(video=active_card['file_id'], caption=full_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            await update_or_query.message.reply_text(full_text, parse_mode="HTML", reply_markup=markup)
    else:
        query = update_or_query
        try:
            await query.edit_message_caption(caption=full_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            try:
                await query.edit_message_text(text=full_text, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass

@restricted_command
async def check_kc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    await register_user_group(user, chat, context)
    await render_kc_view(update, context, page=0, owner_id=user.id)

@restricted_command
async def kachi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    target_id = user.id
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1", target_id)
        kachi_amount = user_row['coins'] if user_row else 1000
        display_name = user_row['name'] if user_row else user.first_name

    bot_info = await context.bot.get_me()
    text = f"Name : {display_name}\nKachi Balance : {kachi_amount}\nUser ID : <code>{target_id}</code>"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Send Kachi", url=f"https://t.me/{bot_info.username}?start=kachi_{target_id}")]
    ])
    
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

# Background task for /klot
async def run_klot_task(bot, chat_id, msg_id, user_id, display_name, bet_amount):
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user_id)
        current_coins = user_row['coins'] if user_row else 1000

    if current_coins < bet_amount:
        try:
            await bot.send_message(chat_id, f"❌ Insufficient Kachi balance! Your current balance is <b>{current_coins}</b> Kachi.", parse_mode="HTML", reply_to_message_id=msg_id)
        except Exception:
            pass
        return

    is_win = random.choice([True, False])
    if is_win:
        new_balance = current_coins + bet_amount
    else:
        new_balance = max(0, current_coins - bet_amount)

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_balance, user_id)

    steps = [
        "📈 Kachi Trader: <b>{name}</b>\n📊 Trading Result: Market Analyzing... [ 20% ]\n💎 Kachi Balance: {bal}",
        "📉 Kachi Trader: <b>{name}</b>\n📊 Trading Result: Price fluctuating up & down... [ 45% ]\n💎 Kachi Balance: {bal}",
        "📈 Kachi Trader: <b>{name}</b>\n📊 Trading Result: Calculating final position... [ 75% ]\n💎 Kachi Balance: {bal}",
        "📉 Kachi Trader: <b>{name}</b>\n📊 Trading Result: Almost done... [ 95% ]\n💎 Kachi Balance: {bal}"
    ]

    try:
        sent_msg = await bot.send_message(chat_id, steps[0].format(name=display_name, bal=current_coins), parse_mode="HTML", reply_to_message_id=msg_id)
    except Exception:
        return

    for step_text in steps[1:]:
        await asyncio.sleep(1.2)
        try:
            await sent_msg.edit_text(step_text.format(name=display_name, bal=current_coins), parse_mode="HTML")
        except Exception:
            pass

    await asyncio.sleep(1.2)

    if is_win:
        final_text = f"""Kachi Trader Name: {display_name}
Trading Result: Profit 📈 (+{bet_amount} Kachi)
Kachi Balance: {new_balance}

🦕 How Luck ! Congregation For U {display_name} 🤍"""
    else:
        final_text = f"""Kachi Trader Name: {display_name}
Trading Result: Loss 📉 (-{bet_amount} Kachi)
Kachi Balance: {new_balance}

🖤 GoodLuck Next Time🍀"""

    try:
        await sent_msg.edit_text(final_text, parse_mode="HTML")
    except Exception:
        pass

@restricted_command
async def klot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    if not context.args:
        return await msg.reply_text("❌ Usage: `/klot [Kachiamount]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        bet_amount = int(context.args[0])
    except ValueError:
        return await msg.reply_text("❌ Please enter a valid Kachi amount to trade.", reply_to_message_id=msg_id)

    if bet_amount <= 0:
        return await msg.reply_text("❌ Trade amount must be greater than 0.", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1", user.id)
        current_coins = user_row['coins'] if user_row else 1000
        display_name = user_row['name'] if user_row else user.first_name

    if current_coins < bet_amount:
        return await msg.reply_text(f"❌ Insufficient Kachi balance! Your current balance is <b>{current_coins}</b> Kachi.", parse_mode="HTML", reply_to_message_id=msg_id)

    asyncio.create_task(run_klot_task(context.bot, chat.id, msg_id, user.id, display_name, bet_amount))

# /kbox Command
@restricted_command
async def kbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    text = "Welcome To Kbox 💤\nLet's Open 🔫"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("OPEN", callback_data=f"kbox_open_{user.id}")]
    ])
    await msg.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    text = query.query.strip()
    user_id = query.from_user.id
    user_name = query.from_user.first_name

    if text.startswith("harem."):
        try:
            target_id = int(text.split(".")[1])
        except Exception:
            target_id = user_id
    else:
        target_id = user_id

    async with db_pool.acquire() as conn:
        owner_row = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
        owner_name = owner_row['name'] if owner_row and owner_row['name'] else user_name

        user_cards = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, uc.amount 
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1 AND uc.amount > 0
            ORDER BY c.card_id ASC
        """, target_id)

    results = []
    for c in user_cards:
        r = c.get('rarity', 'Ten')
        r_emoji = "🧬" if r == 'Shinsei' else ("🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮")))
        title = f"{c['name']} ({c['card_id']})"
        amount_str = f" ({c['amount']}x)" if c['amount'] > 1 else ""

        async with db_pool.acquire() as conn:
            global_drop_count = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE card_id = $1", c['card_id'])

        owner_mention = get_mention(target_id, owner_name)
        caption = f"""❀ Harem Owner ❝ {owner_mention} ❞

✿ Card Name - <b>{c['name']}</b>{amount_str}
      ☘ ID - <code>{c['card_id']}</code>
✿ Rarity - {r_emoji} {r}

⌘ Global Drops - <b>{global_drop_count}</b>"""
        
        if c['type'] == 'photo':
            results.append(
                InlineQueryResultCachedPhoto(
                    id=str(uuid.uuid4()),
                    photo_file_id=c['file_id'],
                    title=title,
                    caption=caption,
                    parse_mode="HTML"
                )
            )
        else:
            results.append(
                InlineQueryResultCachedVideo(
                    id=str(uuid.uuid4()),
                    video_file_id=c['file_id'],
                    title=title,
                    caption=caption,
                    parse_mode="HTML"
                )
            )

    await query.answer(results, cache_time=1)

@restricted_command
async def cardlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_cardlist_page(update, context, page=0, owner_id=update.effective_user.id)

async def render_cardlist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0, owner_id: int = None):
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None
    async with db_pool.acquire() as conn:
        cards = await conn.fetch("SELECT card_id, name, type, rarity FROM cards ORDER BY card_id ASC")

    if not cards:
        text = "🎴 <b>Card list is empty.</b>"
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
        r = c.get('rarity', 'Ten')
        r_emoji = "🧬" if r == 'Shinsei' else ("🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮")))
        card_text_list.append(f"{idx}. {r_emoji} <b>{c['name']}</b> (ID: <code>{c['card_id']}</code>) [{type_emoji} {c['type'].upper()}]")

    cards_str = "\n".join(card_text_list)

    text = f"""📜 <b>Kachi Card List (Page {page + 1}/{total_pages})</b>
📌 <i>Use <code>/card [card_id]</code> for details.</i>

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

@restricted_command
async def card_detail_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/card [card_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_card_id = context.args[0].strip()

    async with db_pool.acquire() as conn:
        card = await conn.fetchrow("SELECT card_id, name, type, file_id, rarity FROM cards WHERE card_id = $1", target_card_id)

        if not card:
            return await update.message.reply_text(f"❌ Card ID <code>{target_card_id}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

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
            owners_text_list.append(f"☛ {get_mention(row['user_id'], row['name'])} — <b>{row['amount']}x</b>")
        owners_str = "\n".join(owners_text_list)
    else:
        owners_str = "☛ <i>No owners yet.</i>"

    r = card.get('rarity', 'Ten')
    r_emoji = "🧬" if r == 'Shinsei' else ("🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮")))

    if r == 'Shinsei':
        coin_value = "4000-8900"
    elif r == 'Kiwami':
        coin_value = "2000-5500"
    elif r == 'Kami':
        coin_value = "1000-2500"
    elif r == 'Hoshi':
        coin_value = "400-800"
    elif r == 'Ten':
        coin_value = "200-400"
    else:
        coin_value = "200-400"

    caption_text = f"""🎗 Card Information ♡

▰▰▱▱▰▰▱▱
🍀 Name - {card['name']}
    🍀  ID - <code>{card['card_id']}</code>
🎬 Type - {card['type'].upper()}
🌟 Rarity - {r_emoji} {r}
🩸 Kachi Value ( {coin_value} )
   🐠 Global Drops - <b>{global_drop_count}</b>

▱▱▰▰▱▱▰▰▱▱▰▰
Top Owners 🐾
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

@restricted_command
async def glist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_glist_page(update, context, page=0)

async def render_glist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None
    async with db_pool.acquire() as conn:
        groups = await conn.fetch("SELECT chat_id, title, added_by_id, added_by_name FROM groups")

    if not groups:
        text = "🏰 <b>Group list is empty.</b>"
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)
        else:
            return await update_or_query.edit_message_text(text, parse_mode="HTML")

    per_page = 5
    total_groups = len(groups)
    total_pages = (total_groups + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))

    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_groups = groups[start_idx:end_idx]

    group_blocks = []
    for idx, g in enumerate(current_groups, start=start_idx + 1):
        chat_id = g['chat_id']
        member_count = "N/A"
        try:
            member_count = await context.bot.get_chat_member_count(chat_id)
        except Exception:
            pass

        invite_link = "N/A"
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

        block = f"""<b>{idx}. {g['title']}</b>
🆔 Gp ID: <code>{chat_id}</code>
👥 Gp Member: {member_count}
🔗 Gp Link: {invite_link}
👤 Addသူ name: {adder_text}"""
        group_blocks.append(block)

    groups_str = "\n\n".join(group_blocks)
    text = f"""🏰 <b>Group List (Page {page + 1}/{total_pages})</b>

{groups_str}"""

    buttons = []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ Back", callback_data=f"glist_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"glist_{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    markup = InlineKeyboardMarkup(buttons) if buttons else None

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True, reply_to_message_id=msg_id)
    else:
        await update_or_query.edit_message_text(text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)

@restricted_command
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:
        u_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        all_groups = await conn.fetch("SELECT chat_id FROM groups")

    active_g_count = 0
    for g in all_groups:
        try:
            member = await context.bot.get_chat_member(g['chat_id'], context.bot.id)
            if member.status not in ['left', 'kicked']:
                active_g_count += 1
        except Exception:
            pass

    await update.message.reply_text(
        f"📊 <b>Bot Stats:</b>\n\n👥 Users: {u_count}\n🏰 Groups: {active_g_count}",
        parse_mode="HTML",
        reply_to_message_id=msg_id
    )

async def run_async_broadcast(bot, chat_id, reply_msg_id, targets, status_msg_id):
    success = 0
    for tid in targets:
        try:
            await bot.forward_message(
                chat_id=tid,
                from_chat_id=chat_id,
                message_id=reply_msg_id
            )
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass

    try:
        await bot.send_message(chat_id, f"✅ Broadcast completed! (Success: {success}/{len(targets)})")
    except Exception:
        pass

@restricted_command
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return
    reply = update.message.reply_to_message
    if not reply:
        return await update.message.reply_text("❌ Reply to the message you want to broadcast.", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        users = [r['user_id'] for r in await conn.fetch("SELECT user_id FROM users")]
        groups = [r['chat_id'] for r in await conn.fetch("SELECT chat_id FROM groups")]

    targets = list(set(users + groups))
    status_msg = await update.message.reply_text(f"🚀 Broadcasting started... (Targets: {len(targets)})", reply_to_message_id=msg_id)

    asyncio.create_task(run_async_broadcast(
        context.bot,
        update.effective_chat.id,
        reply.message_id,
        targets,
        status_msg.message_id
    ))

# /spw Command Handler (Admin Only)
@restricted_command
async def spw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id

    if not user or user.id != ADMIN_ID:
        return await msg.reply_text("❌ This command is only for the bot admin.", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        if context.args:
            target_card_id = context.args[0].strip()
            drop_card = await conn.fetchrow("SELECT card_id, name, type, file_id, rarity FROM cards WHERE card_id = $1", target_card_id)
            if not drop_card:
                return await msg.reply_text(f"❌ Card ID <code>{target_card_id}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)
        else:
            drop_card = await get_weighted_random_card(conn)
            if not drop_card:
                return await msg.reply_text("❌ No cards available in database yet!", reply_to_message_id=msg_id)

    r = drop_card.get('rarity', 'Ten')
    r_emoji = "🧬" if r == 'Shinsei' else ("🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮")))

    # Fixed card name format so it can be easily copied/clicked or typed
    drop_text = f"""{r_emoji} Kachi Character Has Spawn In The Chat ❄

🪁 Catch First Use /katch <code>{drop_card['name']}</code>"""

    if drop_card['type'] == 'photo':
        sent_drop = await context.bot.send_photo(chat.id, drop_card['file_id'], caption=drop_text, parse_mode="HTML")
    else:
        sent_drop = await context.bot.send_video(chat.id, drop_card['file_id'], caption=drop_text, parse_mode="HTML")

    active_card_drops[sent_drop.message_id] = {
        "chat_id": chat.id,
        "card": drop_card,
        "ended": False
    }

# /katch Command Handler
@restricted_command
async def katch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    if not chat or chat.type not in ["group", "supergroup"]:
        return

    # Check active card drop in this chat
    active_drop_key = None
    for m_id, drop_info in active_card_drops.items():
        if drop_info["chat_id"] == chat.id and not drop_info["ended"]:
            active_drop_key = m_id
            break

    if not active_drop_key:
        # Check if there's any recent drop already ended in this chat to reply "Too Late"
        for m_id, drop_info in active_card_drops.items():
            if drop_info["chat_id"] == chat.id and drop_info.get("ended"):
                winner_name = drop_info.get("winner_name", "Someone")
                too_late_msg = f"🧊 Too Late He {winner_name} Catch First This Character Try Next Time 🦇"
                return await msg.reply_text(too_late_msg, parse_mode="HTML", reply_to_message_id=msg_id)
        return

    drop = active_card_drops[active_drop_key]
    card = drop["card"]
    target_card_name = card["name"].strip().lower()

    if not context.args:
        return

    user_typed_name = " ".join(context.args).strip().lower()
    
    # If already ended, reply "Too Late"
    if drop["ended"]:
        winner_name = drop.get("winner_name", "Someone")
        too_late_msg = f"🧊 Too Late He {winner_name} Catch First This Character Try Next Time 🦇"
        return await msg.reply_text(too_late_msg, parse_mode="HTML", reply_to_message_id=msg_id)

    if user_typed_name != target_card_name:
        return

    # First one to correctly match the card name claims it!
    drop["ended"] = True
    drop["winner_name"] = user.first_name
    winner_id = user.id
    winner_name = user.first_name

    # Delete the drop message if possible
    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=active_drop_key)
    except Exception:
        pass

    # Save card to database for winner
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
            ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
        """, winner_id, card['card_id'])

    # Step 1: Send 🐳 animation and wait 3 seconds
    anim_msg = await context.bot.send_message(chat.id, "🐳", reply_to_message_id=msg_id)
    await asyncio.sleep(3)

    # Step 2: Delete animation and reply with success message
    try:
        await context.bot.delete_message(chat.id, anim_msg.message_id)
    except Exception:
        pass

    r = card.get('rarity', 'Ten')
    r_emoji = "🧬" if r == 'Shinsei' else ("🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮")))
    
    win_msg = f"""Congratulations💫 , {get_mention(winner_id, winner_name)} Got A New Character 🦊
{card['name']}, {r_emoji}, <code>{card['card_id']}</code>
Check /kc 🎗"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Harem❄", switch_inline_query_current_chat=f"harem.{winner_id}")]
    ])

    try:
        if card['type'] == 'photo':
            await context.bot.send_photo(chat.id, photo=card['file_id'], caption=win_msg, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        else:
            await context.bot.send_video(chat.id, video=card['file_id'], caption=win_msg, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
    except Exception:
        await context.bot.send_message(chat.id, text=win_msg, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.message
    if not chat or not msg or not user or user.is_bot:
        return

    await register_user_group(user, chat, context)

    if chat.type == "private":
        if user.id in pending_kachi_transfers:
            target_id = pending_kachi_transfers[user.id]
            text_input = msg.text.strip() if msg.text else ""
            if not text_input.isdigit():
                return await msg.reply_text("❌ Please enter a valid number for Kachi amount.", reply_to_message_id=msg.message_id)
            
            amount = int(text_input)
            if amount <= 0:
                return await msg.reply_text("❌ Amount must be greater than 0.", reply_to_message_id=msg.message_id)

            async with db_pool.acquire() as conn:
                sender_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1", user.id)
                sender_coins = sender_row['coins'] if sender_row else 1000
                sender_name = sender_row['name'] if sender_row else user.first_name

                if sender_coins < amount:
                    del pending_kachi_transfers[user.id]
                    return await msg.reply_text(f"❌ Insufficient Kachi balance. (Current: {sender_coins} Kachi)", reply_to_message_id=msg.message_id)

                target_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1", target_id)
                target_coins = target_row['coins'] if target_row else 1000
                target_name = target_row['name'] if target_row else "User"

                new_sender_coins = max(0, sender_coins - amount)
                new_target_coins = target_coins + amount

                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_sender_coins, user.id)
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_target_coins, target_id)

            del pending_kachi_transfers[user.id]

            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            receipt_sender = f"""✦ KACHI TRANSFER RECEIPT ✦

📤 Sender: {get_mention(user.id, sender_name)}
📥 Recipient: {get_mention(target_id, target_name)}
💎 Amount Transferred: <b>{amount}</b> Kachi
💳 Remaining Balance: <b>{new_sender_coins}</b> Kachi

Status: Successful ✅
🕒 Time: {time_str} UTC"""

            receipt_target = f"""✦ KACHI TRANSFER RECEIPT ✦

📤 Sender: {get_mention(user.id, sender_name)}
📥 Recipient: {get_mention(target_id, target_name)}
💎 Amount Transferred: <b>{amount}</b> Kachi
💳 Current Balance: <b>{new_target_coins}</b> Kachi

Status: Successful ✅
🕒 Time: {time_str} UTC"""

            await msg.reply_text(receipt_sender, parse_mode="HTML", reply_to_message_id=msg.message_id)
            try:
                await context.bot.send_message(target_id, receipt_target, parse_mode="HTML")
            except Exception:
                pass
            return

    if chat.type in ["group", "supergroup"]:
        chat_id = chat.id
        now = time.time()
        key = (chat_id, user.id)

        if key in spam_ignores and spam_ignores[key] > now:
            return

        if key not in user_message_timestamps:
            user_message_timestamps[key] = []
        
        user_message_timestamps[key] = [ts for ts in user_message_timestamps[key] if now - ts <= 5]
        user_message_timestamps[key].append(now)

        if len(user_message_timestamps[key]) >= 4:
            spam_ignores[key] = now + 600
            user_message_timestamps[key] = []

            warning_text = f"{get_mention(user.id, user.first_name)} 10minutes ignore please don't spam like that again ⛩"
            try:
                await msg.reply_text(warning_text, parse_mode="HTML", reply_to_message_id=msg.message_id)
            except Exception:
                pass

            invite_link = "N/A"
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

            username_str = f"@{user.username}" if user.username else "None"
            log_text = f"""🚨 <b>Spam Detected!</b>

👤 <b>Spam Name:</b> {get_mention(user.id, user.first_name)}
🏷 <b>Username:</b> {username_str}
🆔 <b>User ID:</b> <code>{user.id}</code>
🏰 <b>Group Name:</b> {chat.title or 'Group'}
🔗 <b>Group Link:</b> {invite_link}"""

            try:
                await context.bot.send_message(ADMIN_ID, log_text, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass

            return

        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            is_bot_admin = bot_member.status in ["administrator", "creator"]
        except Exception:
            is_bot_admin = False

        if not is_bot_admin:
            if chat_id not in bot_warned_groups:
                bot_warned_groups.add(chat_id)
                warning_text = "Bot အသုံးပြုအတွက်ကျေးဇူးအထူးတင်ပါတယ် Bot ကိုAdmin ပေး​ပါက Media ကောင်းကောင်းအလုပ်ပါမည် ဒီတိုင်းဆို ပုံမပါဘူးဖြစ်နေမယ်ဗျ Admin ပေးပေးဦးနော်"
                try:
                    await context.bot.send_message(chat_id, warning_text)
                except Exception:
                    pass

        try:
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO groups (chat_id, title, msg_count) VALUES ($1, $2, 0)
                    ON CONFLICT (chat_id) DO UPDATE SET title = COALESCE($2, groups.title)
                """, chat_id, chat.title or "Group")
                
                threshold = 60

                row = await conn.fetchrow("""
                    UPDATE groups 
                    SET msg_count = CASE WHEN msg_count + 1 >= $2 THEN 0 ELSE msg_count + 1 END
                    WHERE chat_id = $1
                    RETURNING msg_count, (msg_count = 0) AS should_drop
                """, chat_id, threshold)

                if row and row['should_drop']:
                    asyncio.create_task(trigger_card_drop(context, chat_id))
        except Exception as e:
            print(f"Error in group message handler: {e}")

async def trigger_card_drop(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    async with db_pool.acquire() as conn:
        drop_card = await get_weighted_random_card(conn)
    if not drop_card:
        return

    r = drop_card.get('rarity', 'Ten')
    r_emoji = "🧬" if r == 'Shinsei' else ("🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮")))

    drop_text = f"""{r_emoji} Kachi Character Has Spawn In The Chat ❄

🪁 Catch First Use /katch <code>{drop_card['name']}</code>"""

    if drop_card['type'] == 'photo':
        msg = await context.bot.send_photo(chat_id, drop_card['file_id'], caption=drop_text, parse_mode="HTML")
    else:
        msg = await context.bot.send_video(chat_id, drop_card['file_id'], caption=drop_text, parse_mode="HTML")

    active_card_drops[msg.message_id] = {
        "chat_id": chat_id,
        "card": drop_card,
        "ended": False
    }

# Background task for /kbox
async def run_kbox_task(bot, chat_id, query, user_id, display_name):
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user_id)
        current_coins = user_row['coins'] if user_row else 1000

    if current_coins < 300:
        try:
            await query.answer(f"❌ Insufficient Kachi! You need 300 Kachi (Current: {current_coins}).", show_alert=True)
        except Exception:
            pass
        return

    new_balance = current_coins - 300
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_balance, user_id)

    loading_steps = [
        "Card Opening Wait\nLoading... [ 25% ]",
        "Card Opening Wait\nLoading... [ 50% ]",
        "Card Opening Wait\nLoading... [ 75% ]",
        "Card Opening Wait\nLoading... [ 100% ]"
    ]

    try:
        await query.edit_message_text(loading_steps[0], parse_mode="HTML")
    except Exception:
        pass

    for step in loading_steps[1:]:
        await asyncio.sleep(1)
        try:
            await query.edit_message_text(step, parse_mode="HTML")
        except Exception:
            pass

    await asyncio.sleep(1)

    async with db_pool.acquire() as conn:
        card = await get_weighted_random_card(conn)
        if not card:
            try:
                await query.edit_message_text("❌ No cards available in database yet!", parse_mode="HTML")
            except Exception:
                pass
            return

        await conn.execute("""
            INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
            ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
        """, user_id, card['card_id'])

    r = card.get('rarity', 'Ten')
    r_emoji = "🧬" if r == 'Shinsei' else ("🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮")))

    result_caption = f"""🎉 Congratulations! {get_mention(user_id, display_name)} You got a card!
Card Name : {card['name']}
Id : <code>{card['card_id']}</code>
Rarity : {r_emoji} {r}

🔍 Check: /kc
📖 Details: /card {card['card_id']}"""

    try:
        await query.message.delete()
    except Exception:
        pass

    try:
        if card['type'] == 'photo':
            await bot.send_photo(chat_id=chat_id, photo=card['file_id'], caption=result_caption, parse_mode="HTML")
        else:
            await bot.send_video(chat_id=chat_id, video=card['file_id'], caption=result_caption, parse_mode="HTML")
    except Exception:
        await bot.send_message(chat_id=chat_id, text=result_caption, parse_mode="HTML")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    data = query.data

    await register_user_group(user, query.message.chat, context)

    if data.startswith("kbox_open_"):
        allowed_uid = int(data.split("_")[2])
        if user.id != allowed_uid:
            return await query.answer("❌ This is not your Kbox button!", show_alert=True)

        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1", user.id)
            current_coins = user_row['coins'] if user_row else 1000
            display_name = user_row['name'] if user_row else user.first_name

        if current_coins < 300:
            return await query.answer(f"❌ Insufficient Kachi! You need 300 Kachi (Current: {current_coins}).", show_alert=True)

        asyncio.create_task(run_kbox_task(context.bot, chat_id, query, user.id, display_name))
        await query.answer("🎉 Opening Kbox...")
        return

    if data == "aa_noop":
        return await query.answer("ℹ️ ဒါက အဖြေပြသသည့် ခလုတ်ဖြစ်ပါသည်။ အောက်နားရှိ အဖြေမှန်ရွေးရန် ခလုတ်ကို နှိပ်ပါ။", show_alert=True)

    if data.startswith("aa_sel_"):
        idx = int(data.split("_")[2])
        quiz = pending_quizzes.get(msg_id)
        if not quiz:
            return await query.answer("❌ Quiz preview မရှိတော့ပါ သို့မဟုတ် သက်တမ်းကုန်သွားပါပြီ။", show_alert=True)
        
        quiz["correct"] = quiz["options"][idx]
        correct_opt = quiz["correct"]
        
        updated_text = f"❓ <b>Trivia Quiz Preview</b>\n\n<b>{quiz['question']}</b>\n\n✅ <b>အဖြေမှန်ရွေးချယ်ပြီးပါပြီ:</b> <code>{correct_opt}</code>\n\n<i>ယခု `/send` ဖြင့် group များသို့ ပို့နိုင်ပါပြီ။</i>"
        
        keyboard = []
        for o_idx, opt in enumerate(quiz["options"]):
            prefix = "⭐" if opt == correct_opt else "📌"
            keyboard.append([InlineKeyboardButton(f"{prefix} {opt}", callback_data="aa_noop")])
        
        select_row = []
        for o_idx, opt in enumerate(quiz["options"]):
            btn_text = f"✅ ရွေးပြီး ({o_idx+1})" if opt == correct_opt else f"အဖြေမှန် ({o_idx+1})"
            select_row.append(InlineKeyboardButton(btn_text, callback_data=f"aa_sel_{o_idx}"))
        keyboard.append(select_row)

        try:
            await query.edit_message_text(updated_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            pass
        await query.answer(f"✅ အဖြေမှန်အဖြစ် '{correct_opt}' ကို သတ်မှတ်ပြီးပါပြီ။", show_alert=True)
        return

    if data.startswith("ans_"):
        parts = data.split("_")
        quiz_uuid = parts[1]
        chosen_idx = int(parts[2])

        quiz = active_quizzes.get(msg_id)
        if not quiz or quiz["solved"]:
            return await query.answer("❌ အဖြေမှန်ကို အခြားသူ ဖြေဆိုပြီးပါပြီ (သို့မဟုတ်) Quiz ပြီးဆုံးသွားပါပြီ။", show_alert=True)

        if user.id in quiz["answered_users"]:
            return await query.answer("❌ သင် ဖြေဆိုပြီးဖြစ်ပါသည်။ တစ်ဦးလျှင် တစ်ကြိမ်သာ ဖြေဆိုခွင့်ရှိသည်။", show_alert=True)

        chosen_opt = quiz["options"][chosen_idx]
        if chosen_opt == quiz["correct"]:
            quiz["solved"] = True
            coins_won = random.randint(1000, 3000)
            await add_coins(user.id, coins_won)

            result_text = f"""✅ <b>အဖြေမှန်သွားပါပြီ!</b>

❓ <b>{quiz['question']}</b>
👤 <b>အနိုင်ရသူ:</b> {get_mention(user.id, user.first_name)}
💰 <b>ရရှိသော Kachi:</b> +{coins_won} 🩸

CHECK /kc Use Kachi"""

            try:
                await query.edit_message_text(result_text, parse_mode="HTML", reply_markup=None)
            except Exception:
                pass
            await query.answer(f"🎉 မှန်ကန်ပါသည်။ +{coins_won} Kachi ရရှိပါသည်!", show_alert=True)
        else:
            quiz["answered_users"].add(user.id)
            quiz["wrong_users"].add(user.id)

            if len(quiz["wrong_users"]) >= 2:
                quiz["solved"] = True
                expired_text = f"❌ <b>မှားဖြေခွင့်ကုန်သွားပါပြီ!</b>\n\n❓ <b>{quiz['question']}</b>\n\n✅ <b>အဖြေမှန်:</b> <code>{quiz['correct']}</code>"
                try:
                    await query.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=expired_text,
                        parse_mode="HTML",
                        reply_markup=None
                    )
                except Exception:
                    pass
                await query.answer("❌ မှားဖြေခွင့်ကုန်သွားပါပြီ။", show_alert=True)
            else:
                await query.answer("❌ အဖြေမှားနေပါသည်!", show_alert=True)
        return

    if data == "menu_help":
        help_text = """📖 <b>အကူအညီနှင့် လမ်းညွှန်ချက်များ (Help & Guidelines)</b>

- Bot ကို Group ထဲသို့ထည့်ပြီး စာပေးပို့ပါက သတ်မှတ်ထားသော စာအရေအတွက်ပြည့်သည်နှင့် ကတ်များ အလိုအလျောက်ကျလာမည်ဖြစ်ပါသည်။
- /ktop - Global Leaderboard ကို ကြည့်ရန်။
- /kgtop - Group Leaderboard ကို ကြည့်ရန်။
- /card [card_id] - ကတ်အသေးစိတ်နှင့် ပိုင်ရှင်များကို ကြည့်ရန်။
- /set [card_id] - /kc တွင်ပြသရန် ပရိုဖိုင်ကတ်အဖြစ် သတ်မှတ်ရန်။"""
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="menu_back")]])
        await query.edit_message_text(help_text, parse_mode="HTML", reply_markup=markup)
        await query.answer()
        return

    if data == "menu_kgift":
        kgift_text = """🎁 <b>လက်ဆောင်ပေးခြင်း (Gift) လမ်းညွှန်ချက်များ</b>

user တစ်ဦး၏ စာကို reply လုပ်၍ အောက်ပါအတိုင်း ပေးပို့ပါ -
- /kgift [card_id] - သတ်မှတ်ထားသော ကတ်တစ်ခု ပေးပို့ရန် (ဥပမာ - /kgift 1201)"""
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="menu_back")]])
        await query.edit_message_text(kgift_text, parse_mode="HTML", reply_markup=markup)
        await query.answer()
        return

    if data == "menu_back":
        bot_info = await context.bot.get_me()
        text = f"""👋 မင်္ဂလာပါ {get_mention(user.id, user.first_name)} !

🌺 Kachi Card 𝙂𝘼𝙈𝙀 𝘽𝙊𝙏 မှ ကြိုဆိုပါတယ်!

📌 <b>အသုံးပြုပုံ ညွှန်ကြားချက်များ -</b>
- Bot ကို Group ထဲသို့ ထည့်ပါ။
- Group ထဲတွင် စာပေးပို့ပါ (သတ်မှတ်ထားသော စာအရေအတွက်ပြည့်ပါက ကတ်များ အလိုအလျောက် ကျလာပါမည်)။
- ဦးဆောင်သူစာရင်းများကို ကြည့်ရန် /ktop ကို အသုံးပြုပါ။"""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Help 📖", callback_data="menu_help"),
                InlineKeyboardButton("Gift 🎁", callback_data="menu_kgift")
            ],
            [
                InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{bot_info.username}?startgroup=true")
            ]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        await query.answer()
        return

    if data.startswith("addrarity_"):
        parts = data.split("_")
        allowed_uid = int(parts[1])
        rarity = parts[2]

        if user.id != allowed_uid:
            return await query.answer("❌ Not for you.", show_alert=True)

        card_info = pending_card_adds.get(user.id)
        if not card_info:
            return await query.answer("❌ Card addition session expired.", show_alert=True)

        card_id = card_info["card_id"]
        card_name = card_info["card_name"]
        c_type = card_info["type"]
        file_id = card_info["file_id"]
        is_card_admin = card_info["is_card_admin"]

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO cards (card_id, name, type, file_id, rarity)
                VALUES ($1, $2, $3, $4, $5)
            """, card_id, card_name, c_type, file_id, rarity)

            added_reward_coins = 50 if rarity in ["Hoshi", "Ten"] else (80 if rarity in ["Kiwami", "Kami"] else 120)

            if is_card_admin and user.id != ADMIN_ID:
                user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
                current_coins = user_row['coins'] if user_row else 1000
                new_coins = current_coins + added_reward_coins
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_coins, user.id)

        del pending_card_adds[user.id]

        r_emoji = "🧬" if rarity == 'Shinsei' else ("🪞" if rarity == 'Kiwami' else ("✨" if rarity == 'Kami' else ("⚜️" if rarity == 'Hoshi' else "💮")))
        log_text = f"""New card added successfully

❀ Card Name : {card_name}
     ❝  ID : {card_id}
❀ Type : {c_type.capitalize()}
🌟 Rarity : {r_emoji} {rarity}
👤 Added By : {get_mention(user.id, user.first_name)}"""

        try:
            if c_type == "photo":
                await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=file_id, caption=log_text, parse_mode="HTML")
            else:
                await context.bot.send_video(chat_id=LOG_CHANNEL_ID, video=file_id, caption=log_text, parse_mode="HTML")
        except Exception:
            pass

        reward_notice = f"\n🎉 Received <b>+{added_reward_coins} Kachi</b> for adding card!" if (is_card_admin and user.id != ADMIN_ID) else ""
        await query.message.edit_text(
            f"✅ Card added successfully!\n\n🆔 Card ID: <code>{card_id}</code>\n🎴 Name: {card_name}\n🌟 Rarity: {r_emoji} {rarity}{reward_notice}",
            parse_mode="HTML"
        )
        await query.answer("✅ Card added successfully!")
        return

    if data.startswith("check_join_"):
        target_uid = int(data.split("_")[2])
        if user.id != target_uid:
            return await query.answer("❌ Not for you.", show_alert=True)
        try:
            member = await context.bot.get_chat_member(chat_id="@beyondpoe", user_id=user.id)
            if member.status in ['left', 'kicked']:
                return await query.answer("❌ Please join the channel first.", show_alert=True)
            else:
                await query.answer("✅ Thank you! You can now use commands.", show_alert=True)
                try:
                    await query.message.edit_text("✅ Verified! You can now use the bot.", parse_mode="HTML")
                except Exception:
                    pass
        except Exception:
            await query.answer("✅ Verified!", show_alert=True)
            try:
                await query.message.edit_text("✅ Verified!", parse_mode="HTML")
            except Exception:
                pass
        return

    if data.startswith("gift_"):
        parts = data.split("_")
        action = parts[1]
        allowed_sender_id = int(parts[2])

        if user.id != allowed_sender_id:
            return await query.answer("❌ Only the sender can click this.", show_alert=True)

        gift_info = pending_gifts.get(msg_id)
        if not gift_info:
            return await query.answer("❌ Gift transfer expired.", show_alert=True)

        if action == "cancel":
            del pending_gifts[msg_id]
            cancel_text = "❌ <b>Gift transfer cancelled.</b>"
            try:
                if query.message.caption:
                    await query.edit_message_caption(caption=cancel_text, parse_mode="HTML")
                else:
                    await query.edit_message_text(text=cancel_text, parse_mode="HTML")
            except Exception:
                pass
            return await query.answer("Cancelled.")

        elif action == "confirm":
            sender_id = gift_info["sender_id"]
            receiver_id = gift_info["receiver_id"]
            receiver_name = gift_info["receiver_name"]

            async with db_pool.acquire() as conn:
                card_id = gift_info["card_id"]
                card_name = gift_info["card_name"]

                s_card = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", sender_id, card_id)
                if not s_card or s_card['amount'] <= 0:
                    return await query.answer(f"❌ You no longer own Card ID {card_id}.", show_alert=True)

                if s_card['amount'] == 1:
                    await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = $2", sender_id, card_id)
                else:
                    await conn.execute("UPDATE user_cards SET amount = amount - 1 WHERE user_id = $1 AND card_id = $2", sender_id, card_id)

                await conn.execute("""
                    INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
                """, receiver_id, card_id)

                success_text = f"✅ {get_mention(sender_id, user.first_name)} sent <b>{card_name}</b> (ID: <code>{card_id}</code>) to {get_mention(receiver_id, receiver_name)}!"

            del pending_gifts[msg_id]
            try:
                if query.message.caption:
                    await query.edit_message_caption(caption=success_text, parse_mode="HTML")
                else:
                    await query.edit_message_text(text=success_text, parse_mode="HTML")
            except Exception:
                pass
            return await query.answer("Gift sent successfully!")

    if data.startswith("kcpage_"):
        parts = data.split("_")
        page = int(parts[1])
        target_id = int(parts[2])

        if user.id != target_id:
            return await query.answer("❌ Not your /kc view.", show_alert=True)

        await render_kc_view(query, context, page=page, owner_id=target_id)
        await query.answer()
        return

    if data.startswith("glist_"):
        if user.id != ADMIN_ID:
            return await query.answer("❌ Admin only.", show_alert=True)
        page = int(data.replace("glist_", ""))
        await render_glist_page(query, context, page=page)
        await query.answer()
        return

    if data.startswith("clist_"):
        parts = data.split("_")
        page = int(parts[1])
        owner_id = int(parts[2]) if len(parts) > 2 else None

        if owner_id and user.id != owner_id:
            return await query.answer("❌ Not your card list.", show_alert=True)

        await render_cardlist_page(query, context, page=page, owner_id=owner_id)
        await query.answer()
        return

async def post_init(app: Application):
    await init_db()

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # Public User Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("kc", check_kc_cmd))
    app.add_handler(CommandHandler("kachi", kachi_cmd))
    app.add_handler(CommandHandler("klot", klot_cmd))
    app.add_handler(CommandHandler("kbox", kbox_cmd))
    app.add_handler(CommandHandler("set", set_card_cmd))
    app.add_handler(CommandHandler("kgift", kgift_cmd))
    app.add_handler(CommandHandler("card", card_detail_cmd))
    app.add_handler(CommandHandler("ktop", ktop_cmd))
    app.add_handler(CommandHandler("kgtop", kgtop_cmd))
    app.add_handler(CommandHandler("katch", katch_cmd))

    # Admin Commands
    app.add_handler(CommandHandler("aa", aa_cmd))
    app.add_handler(CommandHandler("send", send_quiz_cmd))
    app.add_handler(CommandHandler("cardlist", cardlist_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("crest", crest_cmd))
    app.add_handler(CommandHandler("glist", glist_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("k", admin_coin_cmd))
    app.add_handler(CommandHandler("addadmin", addadmin_cmd))
    app.add_handler(CommandHandler("add", add_card_cmd))
    app.add_handler(CommandHandler("del", del_card_cmd))
    app.add_handler(CommandHandler("check", check_user_cmd))
    app.add_handler(CommandHandler("spw", spw_cmd))

    # Bot-level Moderation Commands
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("umute", umute_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), message_handler))

    print("🤖 Python Game Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
