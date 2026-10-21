import asyncio
import json
import os
import random
import string
import time
import uuid
import asyncpg
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto, InputMediaVideo, InlineQueryResultCachedPhoto, InlineQueryResultCachedVideo, ChatPermissions
from telegram.error import TelegramError, NetworkError, TimedOut
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

# Main Group Link for /kbox, /klot, /kdaily, and /pre restriction
MAIN_GROUP_LINK = "https://t.me/Kachi_sGroup"

# Global Memory Stores (Non-blocking per user/action)
group_threshold = {}
pending_gifts = {}
active_card_drops = {}
pending_card_adds = {}
pending_quizzes = {}
active_quizzes = {}
pending_kachi_transfers = {}
pending_card_buys = {}
active_kbox_users = set()  # Track ongoing Kbox sessions per user
kshop_prices = {}  # Track shop card prices per user session

# Cooldown Stores for /klot, /kbox, and /kslot (30s-35s rules)
klot_cooldowns = {}
kbox_cooldowns = {}
kslot_cooldowns = {}
active_kslot_spins = {}  # Track pending slot spin replies

global_default_threshold = 60
bot_warned_groups = set()

# Anti-Spam Tracking Stores
user_message_timestamps = {}
spam_ignores = {}

# Caching Sets to Avoid Redundant Heavy DB Writes on Every Message
seen_registered_users = set()
seen_registered_groups = set()

# Database Connection Pool (Optimized for High Concurrency - Thousands of Users)
db_pool = None

async def init_db():
    global db_pool, global_default_threshold
    db_pool = await asyncpg.create_pool(
        DATABASE_URL, 
        min_size=50, 
        max_size=200, 
        command_timeout=60
    )
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                coins BIGINT DEFAULT 1000,
                selected_card_id TEXT,
                is_card_admin BOOLEAN DEFAULT FALSE,
                is_card_buyer BOOLEAN DEFAULT FALSE,
                started_in_pm BOOLEAN DEFAULT FALSE,
                banned BOOLEAN DEFAULT FALSE,
                ban_reason TEXT,
                muted_until BIGINT DEFAULT 0,
                mute_reason TEXT,
                last_kdaily BIGINT DEFAULT 0,
                pre_count INT DEFAULT 0,
                last_pre_reset BIGINT DEFAULT 0,
                kbox_count INT DEFAULT 0,
                last_kbox_reset BIGINT DEFAULT 0,
                kc_rarity_mode TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS groups (
                chat_id BIGINT PRIMARY KEY,
                title TEXT,
                added_by_id BIGINT,
                added_by_name TEXT,
                threshold INT DEFAULT 60,
                msg_count INT DEFAULT 0,
                admin_warned BOOLEAN DEFAULT FALSE
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
                rarity TEXT,
                collection TEXT,
                is_locked BOOLEAN DEFAULT FALSE
            );
            CREATE TABLE IF NOT EXISTS user_cards (
                user_id BIGINT,
                card_id TEXT,
                amount INT DEFAULT 1,
                PRIMARY KEY (user_id, card_id)
            );
            CREATE INDEX IF NOT EXISTS idx_user_cards_user_id ON user_cards(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_cards_card_id ON user_cards(card_id);
            CREATE INDEX IF NOT EXISTS idx_group_members_chat_user ON group_members(chat_id, user_id);
        """)

        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS selected_card_id TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_card_admin BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_card_buyer BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS started_in_pm BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS muted_until BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mute_reason TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_kdaily BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS pre_count INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_pre_reset BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS kbox_count INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_kbox_reset BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS kc_rarity_mode TEXT DEFAULT NULL;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_id BIGINT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_name TEXT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS threshold INT DEFAULT 60;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS msg_count INT DEFAULT 0;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS admin_warned BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE user_cards ADD COLUMN IF NOT EXISTS amount INT DEFAULT 1;")
            await conn.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS rarity TEXT;")
            await conn.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS collection TEXT;")
            await conn.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS is_locked BOOLEAN DEFAULT FALSE;")
        except Exception:
            pass

        db_groups = await conn.fetch("SELECT chat_id, threshold FROM groups")
        for g in db_groups:
            if g['threshold'] is not None:
                group_threshold[g['chat_id']] = g['threshold']

        existing_cards = await conn.fetch("SELECT card_id, type FROM cards WHERE rarity IS NULL")
        for c in existing_cards:
            r = random.choices(["Shinsei", "Kiwami", "Kami", "Hoshi", "Ten"], weights=[1, 30, 30, 30, 30], k=1)[0]
            await conn.execute("UPDATE cards SET rarity = $1 WHERE card_id = $2", r, c['card_id'])

        collections_list = [
            "🎞 Ope Ope No Mi [ 🩺]",
            "🎞 Hito Hito No Mi [🌕]",
            "🎞 Mera Mera No Mi [🔥]",
            "🎞 Hana Hana No Mi [🌸]",
            "🎞 Yomi Yomi No Mi [💀]",
            "🎞 Tori Tori No Mi [🦅]",
            "🎞 Yami Yami No Mi [🌑]"
        ]
        unassigned_cards = await conn.fetch("SELECT card_id FROM cards WHERE collection IS NULL")
        for uc in unassigned_cards:
            rand_col = random.choice(collections_list)
            await conn.execute("UPDATE cards SET collection = $1 WHERE card_id = $2", rand_col, uc['card_id'])

        thresh_row = await conn.fetchrow("SELECT value FROM settings WHERE key='default_threshold'")
        if thresh_row:
            global_default_threshold = int(thresh_row['value'])

def get_rarity_emoji(r):
    if r == 'Yugen':
        return "🎐"
    elif r == 'Shinsei':
        return "🧬"
    elif r == 'Kiwami':
        return "🪞"
    elif r == 'Kami':
        return "✨"
    elif r == 'Hoshi':
        return "⚜️"
    else:
        return "💮"

async def check_and_auto_lock_card(conn, card_id):
    card_info = await conn.fetchrow("SELECT rarity, is_locked FROM cards WHERE card_id = $1", card_id)
    if card_info and card_info['rarity'] == 'Yugen' and not card_info['is_locked']:
        total_drops = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE card_id = $1", card_id)
        if total_drops >= 25:
            await conn.execute("UPDATE cards SET is_locked = TRUE WHERE card_id = $1", card_id)

def restricted_command(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        msg = update.effective_message
        if user and not user.is_bot and user.id != ADMIN_ID:
            try:
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
                                try:
                                    await msg.reply_text(
                                        f"❌ <b>You are banned from using this bot.</b>\n📝 Reason: {reason}",
                                        parse_mode="HTML",
                                        reply_to_message_id=msg.message_id
                                    )
                                except Exception:
                                    pass
                            return
                        if user_row['muted_until'] and user_row['muted_until'] > now:
                            remaining = user_row['muted_until'] - now
                            mins = remaining // 60
                            secs = remaining % 60
                            time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
                            reason = user_row['mute_reason'] or 'No reason provided'
                            if msg:
                                try:
                                    await msg.reply_text(
                                        f"🔇 <b>You are muted from using this bot.</b>\n⏳ Time remaining: {time_str}\n📝 Reason: {reason}",
                                        parse_mode="HTML",
                                        reply_to_message_id=msg.message_id
                                    )
                                except Exception:
                                    pass
                            return
            except Exception:
                pass
        return await func(update, context)
    return wrapper

async def register_user_group(user, chat, context: ContextTypes.DEFAULT_TYPE = None):
    if not db_pool:
        return
    try:
        user_id = user.id if user and not user.is_bot else None
        chat_id = chat.id if chat and chat.type in ["group", "supergroup"] else None

        user_cached = user_id in seen_registered_users if user_id else True
        group_cached = chat_id in seen_registered_groups if chat_id else True

        if user_cached and group_cached:
            return

        async with db_pool.acquire() as conn:
            if user_id:
                await conn.execute("""
                    INSERT INTO users (user_id, name, coins) VALUES ($1, $2, 1000)
                    ON CONFLICT(user_id) DO UPDATE SET name = EXCLUDED.name
                """, user_id, user.first_name)
                seen_registered_users.add(user_id)

            if chat_id:
                added_id = user.id if user and not user.is_bot else None
                added_name = user.first_name if user and not user.is_bot else None
                
                is_new = await conn.fetchrow("SELECT chat_id, admin_warned FROM groups WHERE chat_id = $1", chat_id)
                
                await conn.execute("""
                    INSERT INTO groups (chat_id, title, added_by_id, added_by_name) 
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(chat_id) DO UPDATE SET 
                        title = EXCLUDED.title,
                        added_by_id = COALESCE(groups.added_by_id, EXCLUDED.added_by_id),
                        added_by_name = COALESCE(groups.added_by_name, EXCLUDED.added_by_name)
                """, chat_id, chat.title or "Group", added_id, added_name)

                seen_registered_groups.add(chat_id)

                group_row = await conn.fetchrow("SELECT threshold, admin_warned FROM groups WHERE chat_id = $1", chat_id)
                if group_row and group_row['threshold'] is not None:
                    group_threshold[chat_id] = group_row['threshold']

                if group_row and not group_row['admin_warned']:
                    await conn.execute("UPDATE groups SET admin_warned = TRUE WHERE chat_id = $1", chat_id)
                    try:
                        await context.bot.send_message(
                            chat_id,
                            "Bot အသုံးပြုအတွက်ကျေးဇူးအထူးတင်ပါတယ် Bot ကို Admin ပေးပါက Media ကောင်းကောင်းအလုပ်လုပ်ပါမည်。"
                        )
                    except Exception:
                        pass

                if not is_new and context and added_id:
                    try:
                        member_count = await context.bot.get_chat_member_count(chat_id)
                    except Exception:
                        member_count = "N/A"

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

                    adder_text = get_mention(added_id, added_name or "User") if added_id else "—"
                    log_text = f"""🏰 <b>New Group Added</b>

🔹 <b>Group Name:</b> {chat.title or 'Group'}
👥 <b>Members:</b> {member_count}
🆔 <b>Group ID:</b> <code>{chat_id}</code>
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
                    """, chat_id, user.id)
    except Exception as e:
        print(f"Error in register_user_group: {e}")

async def add_coins(user_id, amount):
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                UPDATE users 
                SET coins = GREATEST(0, coins + $1) 
                WHERE user_id = $2
            """, amount, user_id)

def get_mention(user_id, name):
    clean_name = (name or "User").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_id}">{clean_name}</a>'

async def get_weighted_random_card(conn):
    all_cards = await conn.fetch("SELECT card_id, name, type, file_id, rarity, collection, is_locked FROM cards WHERE is_locked = FALSE")
    if not all_cards:
        all_cards = await conn.fetch("SELECT card_id, name, type, file_id, rarity, collection, is_locked FROM cards")
        if not all_cards:
            return None
    
    weights = []
    for c in all_cards:
        r = c.get('rarity', 'Ten')
        if r == 'Yugen':
            weights.append(1)
        elif r == 'Shinsei':
            weights.append(1)
        elif r == 'Kiwami':
            weights.append(30)
        elif r == 'Kami':
            weights.append(30)
        elif r == 'Hoshi':
            weights.append(30)
        else:
            weights.append(30)
            
    return random.choices(all_cards, weights=weights, k=1)[0]

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
            try:
                await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=update.message.message_id)
            except Exception:
                pass
        elif update.callback_query:
            try:
                await update.callback_query.answer("❌ Please join the channel first.", show_alert=True)
            except Exception:
                pass
        return False

async def check_main_group_restriction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    msg = update.message
    if not chat or not msg:
        return True
    
    if chat.type in ["group", "supergroup"]:
        is_main_group = False
        if chat.username and chat.username.lower() == "kachi_sgroup".lower():
            is_main_group = True
        
        if not is_main_group:
            restriction_text = (
                "This Command Will Work In This Main Group\n"
                "Heyy သူများGpမှာမဖောက်ပါနဲ့နော် သူများမျက်စိနှောက်လိမ့်မယ် "
                "အဲ့ဒီ command တွေကိုတော့ ဒီGroupမှာပဲ လာဖောက်ပေးပါနော် ✨"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Main Group 🏰", url=MAIN_GROUP_LINK)]
            ])
            try:
                await msg.reply_text(restriction_text, reply_markup=keyboard, reply_to_message_id=msg.message_id)
            except Exception:
                pass
            return False
    return True

# /pre Command Implementation
@restricted_command
async def pre_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    now = int(time.time())
    cooldown = 86400

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            user_row = await conn.fetchrow(
                "SELECT pre_count, last_pre_reset, name FROM users WHERE user_id = $1 FOR UPDATE",
                user.id
            )
            pre_count = user_row['pre_count'] if user_row else 0
            last_pre_reset = user_row['last_pre_reset'] if user_row else 0
            display_name = user_row['name'] if user_row else user.first_name

            if now - last_pre_reset >= cooldown:
                pre_count = 0
                last_pre_reset = now

            if pre_count >= 3:
                remaining = cooldown - (now - last_pre_reset)
                hours = remaining // 3600
                mins = (remaining % 3600) // 60
                secs = remaining % 60
                time_str = f"{hours}h {mins}m {secs}s" if hours > 0 else (f"{mins}m {secs}s" if mins > 0 else f"{secs}s")
                return await msg.reply_text(
                    f"⏳ မင်္ဂလာပါ {get_mention(user.id, display_name)}၊ /pre ကို တစ်နေ့လျှင် 3 ကြိမ်သာ ဖောက်ယူနိုင်ပါသည်။\n"
                    f"⏱ ကျန်ရှိသောအချိန်: <b>{time_str}</b>",
                    parse_mode="HTML",
                    reply_to_message_id=msg_id
                )

            all_cards = await conn.fetch(
                "SELECT card_id, name, type, file_id, rarity, collection, is_locked FROM cards WHERE rarity IN ('Shinsei', 'Kiwami', 'Kami', 'Hoshi', 'Ten') AND is_locked = FALSE"
            )
            if not all_cards:
                all_cards = await conn.fetch(
                    "SELECT card_id, name, type, file_id, rarity, collection, is_locked FROM cards WHERE rarity IN ('Shinsei', 'Kiwami', 'Kami', 'Hoshi', 'Ten')"
                )
                if not all_cards:
                    all_cards = await conn.fetch("SELECT card_id, name, type, file_id, rarity, collection, is_locked FROM cards")
                    if not all_cards:
                        return await msg.reply_text("❌ No cards available in database!", reply_to_message_id=msg_id)

            weights = []
            for c in all_cards:
                r = c.get('rarity', 'Ten')
                if r == 'Shinsei':
                    weights.append(1)
                elif r == 'Kiwami':
                    weights.append(30)
                elif r == 'Kami':
                    weights.append(30)
                elif r == 'Hoshi':
                    weights.append(30)
                else:
                    weights.append(30)

            card = random.choices(all_cards, weights=weights, k=1)[0]

            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, user.id, card['card_id'])

            pre_count += 1
            await conn.execute(
                "UPDATE users SET pre_count = $1, last_pre_reset = $2 WHERE user_id = $3",
                pre_count, last_pre_reset, user.id
            )

    async with db_pool.acquire() as conn:
        global_drop_count = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE card_id = $1", card['card_id']
        )

    r = card.get('rarity', 'Ten')
    r_emoji = get_rarity_emoji(r)
    col_name = card.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"

    if r == 'Shinsei':
        coin_value = "2000-3000"
    elif r == 'Kiwami':
        coin_value = "1500-1900"
    elif r == 'Kami':
        coin_value = "800-1200"
    elif r == 'Hoshi':
        coin_value = "350-500"
    else:
        coin_value = "150-300"

    caption_text = f"""🎗 Congratulations , {get_mention(user.id, display_name)} You Got A New Character in Pre 

▰▰▱▱▰▰▱▱
🍀 Name - {card['name']}
    🍀  ID - <code>{card['card_id']}</code> 

🌟 Rarity - {r_emoji} {r}
📚 Collection - {col_name}
🩸 Kachi Value ({coin_value})
   🐠 Global Drops - <b>{global_drop_count}</b> 

▰▰▱▱▰▰▱▱
❄Check /kc ❄"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Harem❄", switch_inline_query_current_chat=f"harem.{user.id}")]
    ])

    if card['type'] == 'photo':
        try:
            await msg.reply_photo(photo=card['file_id'], caption=caption_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        except Exception:
            await msg.reply_text(caption_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
    else:
        try:
            await msg.reply_video(video=card['file_id'], caption=caption_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        except Exception:
            await msg.reply_text(caption_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

@restricted_command
async def aa_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    
    is_allowed = (user.id == ADMIN_ID)
    if not is_allowed:
        try:
            async with db_pool.acquire() as conn:
                u_info = await conn.fetchrow("SELECT is_card_admin FROM users WHERE user_id = $1", user.id)
                if u_info and u_info['is_card_admin']:
                    is_allowed = True
        except Exception:
            pass

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
        try:
            async with db_pool.acquire() as conn:
                u_info = await conn.fetchrow("SELECT is_card_admin FROM users WHERE user_id = $1", user.id)
                if u_info and u_info['is_card_admin']:
                    is_allowed = True
        except Exception:
            pass

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
            InlineKeyboardButton("Sell Card 💸", callback_data="menu_ksellcard")
        ],
        [
            InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{bot_info.username}?startgroup=true")
        ]
    ])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

@restricted_command
async def ksellcard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    if chat.type in ["group", "supergroup"]:
        return await msg.reply_text("❌ This command can only be used in Private Chat with the bot.", reply_to_message_id=msg_id)

    if not context.args:
        return await msg.reply_text(
            "❌ <b>ကတ်ရောင်းချလိုပါက အောက်ပါပုံစံအတိုင်း ရိုက်ထည့်ပေးပါ -</b>\n"
            "ဥပမာ: `/ksellcard 1296 827x2`",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )

    raw_items = context.args
    items_to_sell = []

    for token in raw_items:
        token = token.strip()
        if not token:
            continue
        c_id = None
        qty = 1
        if 'x' in token.lower():
            parts = token.lower().split('x', 1)
            p1 = parts[0].strip()
            p2 = parts[1].strip()
            if p1.isdigit() and p2.isdigit():
                if len(p1) <= 2 and len(p2) >= 3:
                    qty = int(p1)
                    c_id = p2
                else:
                    c_id = p1
                    qty = int(p2) if p2 else 1
            elif p1.isdigit() and not p2:
                c_id = p1
                qty = 1
            elif not p1.isdigit() and p2.isdigit():
                qty = int(p2)
                c_id = p1
            else:
                c_id = p1
                qty = 1
        else:
            c_id = token
            qty = 1

        if c_id:
            items_to_sell.append({"card_id": c_id, "amount": qty})

    if not items_to_sell:
        return await msg.reply_text("❌ No valid cards specified to sell.", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            missing_cards = []
            verified_sales = []
            total_earned_coins = 0

            for item in items_to_sell:
                input_c_id = item['card_id']
                req_amount = item['amount']

                card_info = await conn.fetchrow("""
                    SELECT card_id, name, rarity FROM cards 
                    WHERE card_id = $1 
                       OR ltrim(card_id, '0') = ltrim($1, '0') 
                       OR card_id = ltrim($1, '0') 
                       OR ltrim(card_id, '0') = $1
                """, input_c_id)

                if not card_info:
                    missing_cards.append(f"Card ID <code>{input_c_id}</code> (Not found in DB)")
                    continue

                actual_card_id = card_info['card_id']
                rarity = card_info['rarity'] or 'Ten'

                user_card_row = await conn.fetchrow("""
                    SELECT uc.amount FROM user_cards uc
                    WHERE uc.user_id = $1 AND (
                        uc.card_id = $2 
                        OR ltrim(uc.card_id, '0') = ltrim($2, '0')
                        OR uc.card_id = ltrim($2, '0')
                        OR ltrim(uc.card_id, '0') = $2
                    ) FOR UPDATE
                """, user.id, actual_card_id)

                owned_amount = user_card_row['amount'] if user_card_row else 0

                if owned_amount < req_amount:
                    missing_cards.append(f"<b>{card_info['name']}</b> (ID: <code>{actual_card_id}</code>) - Needed: {req_amount}x, Owned: {owned_amount}x")
                else:
                    item_coins_total = 0
                    for _ in range(req_amount):
                        if rarity == 'Yugen':
                            item_coins_total += random.randint(4000, 6000)
                        elif rarity == 'Shinsei':
                            item_coins_total += random.randint(300, 500)
                        elif rarity == 'Kiwami':
                            item_coins_total += random.randint(150, 250)
                        elif rarity == 'Kami':
                            item_coins_total += random.randint(100, 150)
                        elif rarity == 'Hoshi':
                            item_coins_total += random.randint(70, 90)
                        else:
                            item_coins_total += random.randint(70, 90)

                    total_earned_coins += item_coins_total
                    verified_sales.append({
                        "card_id": actual_card_id,
                        "name": card_info['name'],
                        "rarity": rarity,
                        "amount": req_amount,
                        "earned": item_coins_total
                    })

            if missing_cards:
                missing_str = "\n".join(missing_cards)
                return await msg.reply_text(
                    f"❌ <b>You do not own the required cards or amounts!</b>\n\n{missing_str}",
                    parse_mode="HTML",
                    reply_to_message_id=msg_id
                )

            for vs in verified_sales:
                c_id = vs['card_id']
                req_amount = vs['amount']
                uc_row = await conn.fetchrow("""
                    SELECT card_id, amount FROM user_cards WHERE user_id = $1 AND card_id = $2 FOR UPDATE
                """, user.id, c_id)
                if not uc_row:
                    continue
                current_amt = uc_row['amount']
                new_amt = current_amt - req_amount
                if new_amt <= 0:
                    await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = $2", user.id, c_id)
                else:
                    await conn.execute("UPDATE user_cards SET amount = $1 WHERE user_id = $2 AND card_id = $3", new_amt, user.id, c_id)

            await conn.execute("""
                UPDATE users 
                SET coins = coins + $1 
                WHERE user_id = $2
            """, total_earned_coins, user.id)

            user_updated = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
            current_balance = user_updated['coins'] if user_updated else total_earned_coins

    sales_desc_list = []
    for vs in verified_sales:
        r_emoji = get_rarity_emoji(vs['rarity'])
        sales_desc_list.append(f"• {r_emoji} {vs['name']} (ID: <code>{vs['card_id']}</code>) — <b>{vs['amount']}x</b> (+{vs['earned']} Kachi)")
    sales_desc_str = "\n".join(sales_desc_list)

    success_receipt = f"""💸 <b>Card Sale Successful!</b>

👤 <b>Seller:</b> {get_mention(user.id, user.first_name)}

🎴 <b>Sold Cards:</b>
{sales_desc_str}

💎 <b>Total Earned:</b> +<b>{total_earned_coins}</b> Kachi 🩸
💰 <b>Current Balance:</b> <b>{current_balance}</b> Kachi ✨"""

    await msg.reply_text(success_receipt, parse_mode="HTML", reply_to_message_id=msg_id)

@restricted_command
async def kdaily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_main_group_restriction(update, context):
        return
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    now = int(time.time())
    cooldown = 86400

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            user_row = await conn.fetchrow("SELECT last_kdaily, coins, name FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            last_claim = user_row['last_kdaily'] if user_row else 0
            current_coins = user_row['coins'] if user_row else 1000
            display_name = user_row['name'] if user_row else user.first_name

            if now - last_claim < cooldown:
                remaining = cooldown - (now - last_claim)
                hours = remaining // 3600
                mins = (remaining % 3600) // 60
                secs = remaining % 60
                time_str = f"{hours}h {mins}m {secs}s" if hours > 0 else (f"{mins}m {secs}s" if mins > 0 else f"{secs}s")
                return await msg.reply_text(
                    f"⏳ မင်္ဂလာပါ {get_mention(user.id, display_name)}၊ /kdaily ဆုလက်ဆောင်ကို 24 နာရီမှ တစ်ကြိမ်သာ ထုတ်ယူနိုင်ပါသည်။\n"
                    f"⏱ ကျန်ရှိသောအချိန်: <b>{time_str}</b>",
                    parse_mode="HTML",
                    reply_to_message_id=msg_id
                )

            new_coins = current_coins + 600
            await conn.execute("UPDATE users SET coins = $1, last_kdaily = $2 WHERE user_id = $3", new_coins, now, user.id)

    await msg.reply_text(
        f"🎁 <b>Daily Kachi Claimed Successfully!</b>\n\n"
        f"👤 User: {get_mention(user.id, display_name)}\n"
        f"💎 Reward: <b>+600 Kachi</b> 🩸\n"
        f"💰 Total Balance: <b>{new_coins}</b> Kachi\n\n"
        f"<i>ကျေးဇူးတင်ပါတယ်! မနက်ဖြန်လည်း ထပ်မံလာရောက် ထုတ်ယူနိုင်ပါပြီ ✨</i>",
        parse_mode="HTML",
        reply_to_message_id=msg_id
    )

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

@restricted_command
async def badmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/badmin [user_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        target_id = int(context.args[0])
        async with db_pool.acquire() as conn:
            user_exists = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
            if not user_exists:
                await conn.execute("INSERT INTO users (user_id, name, coins) VALUES ($1, 'User', 1000)", target_id)
            await conn.execute("UPDATE users SET is_card_buyer = TRUE WHERE user_id = $1", target_id)

        await update.message.reply_text(f"✅ User ID <code>{target_id}</code> is now designated as the Card Buyer.", parse_mode="HTML", reply_to_message_id=msg_id)
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

@restricted_command
async def got_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    user = update.effective_user

    if user.id != ADMIN_ID:
        return

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/got [card_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_card_id = context.args[0].strip()

    async with db_pool.acquire() as conn:
        card = await conn.fetchrow("SELECT card_id, name, type, file_id, rarity, collection FROM cards WHERE card_id = $1", target_card_id)
        if not card:
            return await update.message.reply_text(f"❌ Card ID <code>{target_card_id}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

        async with conn.transaction():
            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, ADMIN_ID, target_card_id)
            await check_and_auto_lock_card(conn, target_card_id)

    r = card.get('rarity', 'Ten')
    r_emoji = get_rarity_emoji(r)

    await update.message.reply_text(
        f"✅ Successfully added card <b>{card['name']}</b> (ID: <code>{card['card_id']}</code>, Rarity: {r_emoji} {r}) to your inventory!",
        parse_mode="HTML",
        reply_to_message_id=msg_id
    )

@restricted_command
async def unlock_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/unlock [card_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    arg = context.args[0].strip().lower()
    
    async with db_pool.acquire() as conn:
        if arg == "all":
            await conn.execute("UPDATE cards SET is_locked = FALSE")
            return await update.message.reply_text("🔓 All cards have been successfully unlocked!", parse_mode="HTML", reply_to_message_id=msg_id)
        else:
            card = await conn.fetchrow("SELECT name, rarity, is_locked FROM cards WHERE card_id = $1", context.args[0].strip())
            if not card:
                return await update.message.reply_text(f"❌ Card ID <code>{context.args[0].strip()}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

            if not card['is_locked']:
                return await update.message.reply_text(f"ℹ️ Card ID <code>{context.args[0].strip()}</code> (<b>{card['name']}</b>) is already unlocked.", parse_mode="HTML", reply_to_message_id=msg_id)

            await conn.execute("UPDATE cards SET is_locked = FALSE WHERE card_id = $1", context.args[0].strip())
            return await update.message.reply_text(
                f"✅ Card ID <code>{context.args[0].strip()}</code> (<b>{card['name']}</b>) has been successfully unlocked and can now drop in drops & Kboxes!",
                parse_mode="HTML",
                reply_to_message_id=msg_id
            )

@restricted_command
async def lock_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/lock [card_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    arg = context.args[0].strip().lower()

    async with db_pool.acquire() as conn:
        if arg == "all":
            await conn.execute("UPDATE cards SET is_locked = TRUE")
            return await update.message.reply_text("🔒 All cards have been successfully locked!", parse_mode="HTML", reply_to_message_id=msg_id)
        else:
            card = await conn.fetchrow("SELECT name, rarity, is_locked FROM cards WHERE card_id = $1", context.args[0].strip())
            if not card:
                return await update.message.reply_text(f"❌ Card ID <code>{context.args[0].strip()}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

            if card['is_locked']:
                return await update.message.reply_text(f"ℹ️ Card ID <code>{context.args[0].strip()}</code> (<b>{card['name']}</b>) is already locked.", parse_mode="HTML", reply_to_message_id=msg_id)

            await conn.execute("UPDATE cards SET is_locked = TRUE WHERE card_id = $1", context.args[0].strip())
            return await update.message.reply_text(
                f"🔒 Card ID <code>{context.args[0].strip()}</code> (<b>{card['name']}</b>) has been successfully locked and will no longer drop in drops & Kboxes!",
                parse_mode="HTML",
                reply_to_message_id=msg_id
            )

@restricted_command
async def spw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    chat = update.effective_chat
    if update.effective_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:
        if context.args:
            target_id = context.args[0].strip()
            card = await conn.fetchrow("SELECT card_id, name, type, file_id, rarity, collection FROM cards WHERE card_id = $1", target_id)
            if not card:
                return await update.message.reply_text(f"❌ Card ID <code>{target_id}</code> not found in database.", parse_mode="HTML", reply_to_message_id=msg_id)
        else:
            cards = await conn.fetch("SELECT card_id, name, type, file_id, rarity, collection FROM cards")
            if not cards:
                return await update.message.reply_text("❌ No cards available in database!", reply_to_message_id=msg_id)
            card = random.choice(cards)

    r = card.get('rarity', 'Ten')
    r_emoji = get_rarity_emoji(r)
    col_name = card.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"

    joined_names = []
    joined_str = "\n".join(joined_names) if joined_names else "<i>No one joined yet.</i>"

    drop_text = f"""{r_emoji} A Character Card Spawned In The Chat ❄

[ 𝗝𝗢𝗜𝗡 ] Fast For The Claim
 Card ❀

{joined_str}

GoodLuck 🍀 Time (50sec)"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("𝗝𝗢𝗜𝗡(0/5)", callback_data="join_card_drop")
    ]])

    try:
        if card['type'] == 'photo':
            msg = await context.bot.send_photo(chat.id, card['file_id'], caption=drop_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        else:
            msg = await context.bot.send_video(chat.id, card['file_id'], caption=drop_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
    except Exception:
        return

    active_card_drops[msg.message_id] = {
        "chat_id": chat.id,
        "card": card,
        "joined_users": {},
        "timer": 50,
        "ended": False
    }

    asyncio.create_task(run_card_drop_timer(context, msg.message_id))

@restricted_command
async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    msg_id = msg.message_id

    is_buyer = (user.id == ADMIN_ID)
    if not is_buyer:
        try:
            async with db_pool.acquire() as conn:
                u_info = await conn.fetchrow("SELECT is_card_buyer FROM users WHERE user_id = $1", user.id)
                if u_info and u_info['is_card_buyer']:
                    is_buyer = True
        except Exception:
            pass

    if not is_buyer:
        return await msg.reply_text("❌ You are not authorized to use the /buy command.", reply_to_message_id=msg_id)

    seller_id = None
    raw_items = []

    if context.args:
        first_arg = context.args[0].strip()
        if first_arg.isdigit() and len(first_arg) >= 5:
            try:
                seller_id = int(first_arg)
                raw_items = context.args[1:]
            except ValueError:
                pass

    if not seller_id:
        if msg.reply_to_message and msg.reply_to_message.from_user:
            seller_id = msg.reply_to_message.from_user.id
            raw_items = context.args
        else:
            return await msg.reply_text(
                "❌ ကျေးဇူးပြု၍ ရောင်းသူ၏ User ID ထည့်ပါ သို့မဟုတ် ရောင်းသူ၏စာကို Reply လုပ်၍ `/buy [card_id]` ဟု အသုံးပြုပါ။\n"
                "ဥပမာ: `/buy 7940553702 0192x 1111` သို့မဟုတ် Reply လုပ်၍ಗೊಳပီး `/buy 0192x`",
                parse_mode="Markdown",
                reply_to_message_id=msg_id
            )

    if seller_id == user.id:
        return await msg.reply_text("❌ You cannot buy cards from yourself.", reply_to_message_id=msg_id)

    items_to_buy = []

    for token in raw_items:
        token = token.strip()
        if not token:
            continue
        c_id = None
        qty = 1
        if 'x' in token.lower():
            parts = token.lower().split('x', 1)
            p1 = parts[0].strip()
            p2 = parts[1].strip()
            if p1.isdigit() and p2.isdigit():
                if len(p1) <= 2 and len(p2) >= 3:
                    qty = int(p1)
                    c_id = p2
                else:
                    c_id = p1
                    qty = int(p2) if p2 else 1
            elif p1.isdigit() and not p2:
                c_id = p1
                qty = 1
            elif not p1.isdigit() and p2.isdigit():
                qty = int(p2)
                c_id = p1
            else:
                c_id = p1
                qty = 1
        else:
            c_id = token
            qty = 1

        if c_id:
            items_to_buy.append({"card_id": c_id, "amount": qty})

    if not items_to_buy:
        return await msg.reply_text("❌ No valid cards specified to buy.", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        seller_row = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", seller_id)
        if not seller_row:
            return await msg.reply_text(f"❌ Seller ID <code>{seller_id}</code> not found in database.", parse_mode="HTML", reply_to_message_id=msg_id)
        seller_name = seller_row['name'] or "User"

        missing_cards = []
        verified_items = []

        for item in items_to_buy:
            input_c_id = item['card_id']
            req_amount = item['amount']

            card_info = await conn.fetchrow("""
                SELECT card_id, name, rarity FROM cards 
                WHERE card_id = $1 
                   OR ltrim(card_id, '0') = ltrim($1, '0') 
                   OR card_id = ltrim($1, '0') 
                   OR ltrim(card_id, '0') = $1
            """, input_c_id)

            if not card_info:
                missing_cards.append(f"Card ID <code>{input_c_id}</code> (Not found in DB)")
                continue

            actual_card_id = card_info['card_id']

            user_card_row = await conn.fetchrow("""
                SELECT uc.amount FROM user_cards uc
                WHERE uc.user_id = $1 AND (
                    uc.card_id = $2 
                    OR ltrim(uc.card_id, '0') = ltrim($2, '0')
                    OR uc.card_id = ltrim($2, '0')
                    OR ltrim(uc.card_id, '0') = $2
                )
            """, seller_id, actual_card_id)

            owned_amount = user_card_row['amount'] if user_card_row else 0

            if owned_amount < req_amount:
                missing_cards.append(f"<b>{card_info['name']}</b> (ID: <code>{actual_card_id}</code>) - Needed: {req_amount}x, Owned: {owned_amount}x")
            else:
                verified_items.append({
                    "card_id": actual_card_id,
                    "name": card_info['name'],
                    "rarity": card_info['rarity'],
                    "amount": req_amount
                })

        if missing_cards:
            missing_str = "\n".join(missing_cards)
            return await msg.reply_text(
                f"❌ <b>Seller does not have the required cards or amounts!</b>\n\n{missing_str}",
                parse_mode="HTML",
                reply_to_message_id=msg_id
            )

    items_desc_list = []
    for vi in verified_items:
        items_desc_list.append(f"• {vi['name']} (ID: <code>{vi['card_id']}</code>) — <b>{vi['amount']}x</b>")
    items_desc_str = "\n".join(items_desc_list)

    buy_text = f"""🛒 <b>Card Purchase Confirmation</b>

👤 <b>Buyer:</b> {get_mention(user.id, user.first_name)}
👤 <b>Seller:</b> {get_mention(seller_id, seller_name)}

🎴 <b>Cards to Remove:</b>
{items_desc_str}

<i>Click the button below to confirm.</i>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("ဝယ်မည် ✅", callback_data=f"buy_confirm_{user.id}_{seller_id}")
    ]])

    sent_msg = await msg.reply_text(buy_text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

    pending_card_buys[sent_msg.message_id] = {
        "buyer_id": user.id,
        "seller_id": seller_id,
        "seller_name": seller_name,
        "items": verified_items
    }

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
7. /badmin [user_id] - Set Card Buyer
8. /buy [seller_id] [card_id] ... - Buy cards from user (removes from seller)
9. /got [card_id] - Get card directly to your inventory (Admin only)
10. /add - Add new card (reply to media)
11. /unlock [card_id/all] - Unlock Yugen, locked card, or all cards
12. /lock [card_id/all] - Lock card or all cards
13. /spw [card_id] - Spawn random card or specific card
14. /del [card_id_or_name] - Delete card by ID or Name
15. /cardlist - View all cards
16. /seelock - View Yugen cards lock status and drops (Admin only)
17. /glist - View groups list
18. /stats - View stats
19. /broadcast - Broadcast message
20. /check [user_id] - Check user profile info
21. /mute [id] [time] [reason] - Mute user from bot usage
22. /ban [id] [reason] - Ban user from bot usage
23. /umute [id] - Unmute user from bot usage
24. /unban [id] - Unban user from bot usage"""

    await update.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)

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
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

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
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

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
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

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
        return await msg.reply_text("❌ Usage: `/unban [user_id]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        target_id = int(context.args[0])
    except ValueError:
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

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
        return await msg.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

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
            SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, c.collection, uc.amount 
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
        rarity_emoji = get_rarity_emoji(c.get('rarity'))
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

    global global_default_threshold
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
            async with conn.transaction():
                user_exists = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1 FOR UPDATE", target_id)
                if not user_exists:
                    await conn.execute("INSERT INTO users (user_id, name, coins) VALUES ($1, $2, 1000)", target_id, "User")
                
                await conn.execute("""
                    UPDATE users 
                    SET coins = GREATEST(0, coins + $1) 
                    WHERE user_id = $2
                """, amount, target_id)
                
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
        
        if any(c.isalpha() for c in card_id):
            return await update.message.reply_text(
                "❌ Card ID ထဲတွင် English စာလုံးများ (Letters) ပါဝင်၍ မရပါ။ နံပတ် (Numbers) သာ ဖြစ်ရပါမည် (ဥပမာ - 02873)။",
                parse_mode="HTML",
                reply_to_message_id=msg_id
            )
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
            InlineKeyboardButton("🎐 Yugen", callback_data=f"addrarity_{user.id}_Yugen"),
            InlineKeyboardButton("🧬 Shinsei", callback_data=f"addrarity_{user.id}_Shinsei")
        ],
        [
            InlineKeyboardButton("🪞 Kiwami", callback_data=f"addrarity_{user.id}_Kiwami"),
            InlineKeyboardButton("✨ Kami", callback_data=f"addrarity_{user.id}_Kami")
        ],
        [
            InlineKeyboardButton("⚜️ Hoshi", callback_data=f"addrarity_{user.id}_Hoshi"),
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
        return await update.message.reply_text("❌ Usage: `/del [card_id or card_name]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_query = " ".join(context.args).strip()

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            card = await conn.fetchrow("SELECT card_id, name FROM cards WHERE card_id = $1 OR name = $2", target_query, target_query)
            if not card:
                card = await conn.fetchrow("SELECT card_id, name FROM cards WHERE card_id = $1 OR name ILIKE $1", target_query)

            if not card:
                return await update.message.reply_text(f"❌ Card (ID or Name) <code>{target_query}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

            target_card_id = card['card_id']
            card_name = card['name']

            await conn.execute("DELETE FROM user_cards WHERE card_id = $1", target_card_id)
            await conn.execute("DELETE FROM cards WHERE card_id = $1", target_card_id)
            await conn.execute("UPDATE users SET selected_card_id = NULL WHERE selected_card_id = $1", target_card_id)

    await update.message.reply_text(f"✅ Card ID <code>{target_card_id}</code> (<b>{card_name}</b>) deleted successfully.", parse_mode="HTML", reply_to_message_id=msg_id)

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
        async with conn.transaction():
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
async def khmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    text = "🎯 <b>Select Rarity Mode for /kc</b>\n\nကျေးဇူးပြု၍ စုပြလိုသော Rarity တစ်ခုကို ရွေးချယ်ပေးပါ -"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎐 Yugen", callback_data=f"khset_{user.id}_Yugen"),
            InlineKeyboardButton("🧬 Shinsei", callback_data=f"khset_{user.id}_Shinsei")
        ],
        [
            InlineKeyboardButton("🪞 Kiwami", callback_data=f"khset_{user.id}_Kiwami"),
            InlineKeyboardButton("✨ Kami", callback_data=f"khset_{user.id}_Kami")
        ],
        [
            InlineKeyboardButton("⚜️ Hoshi", callback_data=f"khset_{user.id}_Hoshi"),
            InlineKeyboardButton("💮 Ten", callback_data=f"khset_{user.id}_Ten")
        ]
    ])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

@restricted_command
async def resethmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET kc_rarity_mode = NULL WHERE user_id = $1", user.id)

    await update.message.reply_text("✅ Reset Successful! /kc တွင် ကတ်အားလုံးကို ပုံမှန်အတိုင်း ပြန်လည်ပြသမည် ဖြစ်ပါသည်။", parse_mode="HTML", reply_to_message_id=msg_id)

@restricted_command
async def kshop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    text = f"""Hello {user.first_name}
You can buy the highest-tier 🎐Yugen / 🧬Shinsei / 🪞 Kiwami rarity cards here"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎐 Yugen", callback_data=f"kshop_rarity_{user.id}_Yugen"),
            InlineKeyboardButton("🧬 Shinsei", callback_data=f"kshop_rarity_{user.id}_Shinsei")
        ],
        [
            InlineKeyboardButton("🪞 Kiwami", callback_data=f"kshop_rarity_{user.id}_Kiwami")
        ]
    ])
    await msg.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

async def render_kshop_card(query, context, user_id, rarity, index):
    async with db_pool.acquire() as conn:
        cards = await conn.fetch("SELECT card_id, name, type, file_id, rarity, collection FROM cards WHERE rarity = $1 ORDER BY card_id ASC", rarity)
    
    if not cards:
        return await query.answer("❌ No cards available in this rarity!", show_alert=True)
    
    index = max(0, min(index, len(cards) - 1))
    card = cards[index]
    
    price_key = (user_id, card['card_id'])
    if price_key not in kshop_prices:
        if rarity == 'Kiwami':
            kshop_prices[price_key] = random.randint(2500, 3000)
        elif rarity == 'Shinsei':
            kshop_prices[price_key] = random.randint(4000, 5500)
        elif rarity == 'Yugen':
            kshop_prices[price_key] = random.randint(6800, 8000)
        else:
            kshop_prices[price_key] = 2500
    price = kshop_prices[price_key]

    async with db_pool.acquire() as conn:
        global_drop_count = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE card_id = $1", card['card_id'])

    r_emoji = get_rarity_emoji(rarity)
    col_name = card.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"

    caption_text = f"""🎗 Card Information ♡

▰▰▱▱▰▰▱▱
🍀 Name - {card['name']}
    🍀  ID - <code>{card['card_id']}</code>
🎬 Type - {card['type'].upper()}
🌟 Rarity - {r_emoji} {rarity}
📚 Collection - {col_name}
🩸 Kachi Price - <b>{price}</b>
   🐠 Global Drops - <b>{global_drop_count}</b>

▰▰▱▱▰▰▱▱▰▰ ({index + 1}/{len(cards)})"""

    keyboard_rows = []
    nav_row = []
    if index > 0:
        nav_row.append(InlineKeyboardButton("◀️ Back", callback_data=f"kshop_nav_{user_id}_{rarity}_{index - 1}"))
    if index < len(cards) - 1:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"kshop_nav_{user_id}_{rarity}_{index + 1}"))
    if nav_row:
        keyboard_rows.append(nav_row)

    keyboard_rows.append([
        InlineKeyboardButton("Buy This Card", callback_data=f"kshop_buy_{user_id}_{rarity}_{card['card_id']}_{price}")
    ])
    keyboard_rows.append([
        InlineKeyboardButton("◀️ Back Menu", callback_data=f"kshop_back_{user_id}")
    ])
    markup = InlineKeyboardMarkup(keyboard_rows)

    media = InputMediaPhoto(media=card['file_id'], caption=caption_text, parse_mode="HTML") if card['type'] == 'photo' else InputMediaVideo(media=card['file_id'], caption=caption_text, parse_mode="HTML")

    try:
        await query.edit_message_media(media=media, reply_markup=markup)
    except Exception:
        try:
            await query.edit_message_caption(caption=caption_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass

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
        card = await conn.fetchrow("SELECT card_id, name, type, file_id, collection FROM cards WHERE card_id = $1", card_id)
        if not card:
            return await update.message.reply_text(f"❌ Card ID <code>{card_id}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

        user_card = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", sender.id, card_id)
        if not user_card or user_card['amount'] <= 0:
            return await update.message.reply_text(f"❌ You do not own Card ID <code>{card_id}</code> (<b>{card['name']}</b>).", parse_mode="HTML", reply_to_message_id=msg_id)

    col_name = card.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"
    text = f"""🎁 <b>Kachi Card Gift Transfer</b>

👤 <b>Sender:</b> {get_mention(sender.id, sender.first_name)}
👤 <b>Receiver:</b> {get_mention(receiver.id, receiver.first_name)}

🎴 <b>Card Info:</b>
🏷️ <b>Name:</b> {card['name']}
🆔 <b>Card ID:</b> <code>{card['card_id']}</code>
📚 <b>Collection:</b> {col_name}

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
        user_row = await conn.fetchrow("SELECT selected_card_id, name, kc_rarity_mode FROM users WHERE user_id = $1", target_id)
        selected_card_id = user_row['selected_card_id'] if user_row else None
        display_name = user_row['name'] if user_row else user.first_name
        rarity_mode = user_row['kc_rarity_mode'] if user_row else None

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

        if rarity_mode:
            user_card_rows = await conn.fetch("""
                SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, c.collection, uc.amount 
                FROM user_cards uc 
                JOIN cards c ON uc.card_id = c.card_id 
                WHERE uc.user_id = $1 AND uc.amount > 0 AND c.rarity = $2
                ORDER BY c.card_id ASC
            """, target_id, rarity_mode)
        else:
            user_card_rows = await conn.fetch("""
                SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, c.collection, uc.amount 
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

    mode_title = f" [{get_rarity_emoji(rarity_mode)} {rarity_mode} Mode]" if rarity_mode else ""
    text_header = f"""❀ 𝙉𝘼𝙈𝙀 - {get_mention(target_id, display_name)}
❀ 𝙂𝙡𝙤𝙗𝙖𝙡 𝙉𝙤 - #{global_rank}

𝗛𝗔𝗥𝗘𝗠 𝗣𝗔𝗚𝗘{mode_title} ({page + 1}/{total_pages})"""

    if not user_card_rows:
        full_text = f"{text_header}\n\nCollection\n<i>No cards found.</i>"
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

    collections_dict = {}
    for c in current_page_cards:
        col = c.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"
        if col not in collections_dict:
            collections_dict[col] = []
        collections_dict[col].append(c)

    content_blocks = ["Collection"]
    for col_name, cards_in_col in collections_dict.items():
        content_blocks.append("")
        content_blocks.append(f"      {col_name}")
        for c in cards_in_col:
            r_emoji = get_rarity_emoji(c.get('rarity'))
            count_str = f" {c['amount']}x" if c['amount'] > 1 else " 1x"
            content_blocks.append(f"🍀{c['name']} {r_emoji} 🧩 [ {c['card_id']} ]{count_str}")

    cards_info = "\n".join(content_blocks)
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

async def run_klot_task(bot, chat_id, msg_id, user_id, display_name, bet_amount):
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user_id)
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
    finally:
        pass

# /klot Command Implementation
@restricted_command
async def klot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    now = time.time()
    last_klot = klot_cooldowns.get(user.id, 0)
    if now - last_klot < 35:
        remaining = int(35 - (now - last_klot))
        return await msg.reply_text(
            f"⏳ မင်္ဂလာပါ {get_mention(user.id, user.first_name)}၊ /klot ကို တစ်ပွဲပြီးလျှင် <b>35 စက္ကန့်</b> စောင့်ဆိုင်းပေးပါ။\n"
            f"⏱ ကျန်ရှိသောအချိန်: <b>{remaining}s</b>",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )
    klot_cooldowns[user.id] = now

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


# --- /kslot Command Implementation ---
@restricted_command
async def kslot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    now = time.time()
    last_kslot = kslot_cooldowns.get(user.id, 0)
    if now - last_kslot < 30:
        remaining = int(30 - (now - last_kslot))
        return await msg.reply_text(
            f"⏳ မင်္ဂလာပါ {get_mention(user.id, user.first_name)}၊ /kslot ကို တစ်ပွဲပြီးလျှင် <b>30 စက္ကန့်</b> စောင့်ဆိုင်းပေးပါ။\n"
            f"⏱ ကျန်ရှိသောအချိန်: <b>{remaining}s</b>",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )

    amounts = [300, 500, 800, 1500, 2500, 4500, 7000]
    keyboard_rows = []
    row = []
    for amt in amounts:
        row.append(InlineKeyboardButton(f"{amt} Kachi 🩸", callback_data=f"kslot_bet_{user.id}_{amt}"))
        if len(row) == 2:
            keyboard_rows.append(row)
            row = []
    if row:
        keyboard_rows.append(row)

    text = f"""🎰 <b>Kachi Slot Machine Game</b>

👤 Player: {get_mention(user.id, user.first_name)}
👇 ကျေးဇူးပြု၍ ဂိမ်းစတင်ရန် လောင်းကြေးပမာဏ (Betting Amount) ကို ရွေးချယ်ပါ -"""

    await msg.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard_rows), reply_to_message_id=msg_id)


def decode_slot_dice(value):
    # Telegram slot dice value (1-64)
    idx = value - 1
    d1 = idx // 16
    d2 = (idx // 4) % 4
    d3 = idx % 4

    symbols = []
    total_score = 0

    for d in [d1, d2, d3]:
        if d == 3:
            s_name = "7"
            s_score = random.randint(11, 12)
        elif d == 2:
            s_name = "🍋"
            s_score = random.randint(9, 10)
        elif d == 1:
            s_name = "🍇"
            s_score = random.randint(7, 8)
        else:
            s_name = "BAR"
            s_score = random.randint(6, 7)
        symbols.append(s_name)
        total_score += s_score

    return symbols, total_score
# -------------------------------------


# /kbox Command Implementation
@restricted_command
async def kbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg = update.message
    msg_id = msg.message_id
    await register_user_group(user, chat, context)

    now = time.time()
    last_kbox = kbox_cooldowns.get(user.id, 0)
    if now - last_kbox < 35:
        remaining = int(35 - (now - last_kbox))
        return await msg.reply_text(
            f"⏳ မင်္ဂလာပါ {get_mention(user.id, user.first_name)}၊ /kbox ကို တစ်ပွဲပြီးလျှင် <b>35 စက္ကန့်</b> စောင့်ဆိုင်းပေးပါ။\n"
            f"⏱ ကျန်ရှိသောအချိန်: <b>{remaining}s</b>",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )
    kbox_cooldowns[user.id] = now

    if user.id in active_kbox_users:
        return await msg.reply_text("❌ သင့်မှာ Kbox တစ်ခု ဖွင့်နေဆဲ ရှိပါသေးသည်။ အရင်ဟာ ပြီးဆုံးသည်အထိ စောင့်ဆိုင်းပေးပါ။", reply_to_message_id=msg_id)

    cooldown = 86400

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT kbox_count, last_kbox_reset, coins, name FROM users WHERE user_id = $1", user.id)
        kbox_count = user_row['kbox_count'] if user_row else 0
        last_kbox_reset = user_row['last_kbox_reset'] if user_row else 0
        coins = user_row['coins'] if user_row else 1000
        display_name = user_row['name'] if user_row else user.first_name

        if now - last_kbox_reset >= cooldown:
            kbox_count = 0
            last_kbox_reset = now
            await conn.execute("UPDATE users SET kbox_count = 0, last_kbox_reset = $1 WHERE user_id = $2", now, user.id)

        if kbox_count >= 7:
            remaining = cooldown - (now - last_kbox_reset)
            hours = remaining // 3600
            mins = (remaining % 3600) // 60
            secs = remaining % 60
            time_str = f"{hours}h {mins}m {secs}s" if hours > 0 else (f"{mins}m {secs}s" if mins > 0 else f"{secs}s")
            return await msg.reply_text(
                f"⏳ မင်္ဂလာပါ {get_mention(user.id, display_name)}၊ /kbox ကို တစ်နေ့လျှင် 7 ကြိမ်သာ ဖွင့်လှစ်နိုင်ပါသည်။\n"
                f"⏱ ကျန်ရှိသောအချိန်: <b>{time_str}</b>",
                parse_mode="HTML",
                reply_to_message_id=msg_id
            )

        if coins < 300:
            return await msg.reply_text(f"❌ Insufficient Kachi! You need 300 Kachi (Current: {coins}).", reply_to_message_id=msg_id)

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

    offset = int(query.offset) if query.offset and query.offset.isdigit() else 0
    limit = 50

    async with db_pool.acquire() as conn:
        owner_row = await conn.fetchrow("SELECT name FROM users WHERE user_id = $1", target_id)
        owner_name = owner_row['name'] if owner_row and owner_row['name'] else user_name

        user_cards = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, c.collection, uc.amount 
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1 AND uc.amount > 0
            ORDER BY c.card_id ASC
            LIMIT $2 OFFSET $3
        """, target_id, limit, offset)

    results = []
    for c in user_cards:
        r = c.get('rarity', 'Ten')
        r_emoji = get_rarity_emoji(r)
        col_name = c.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"
        title = f"{c['name']} ({c['card_id']})"[:64]
        description = f"ID: {c['card_id']} | Rarity: {r}"
        amount_str = f" ({c['amount']}x)" if c['amount'] > 1 else ""

        async with db_pool.acquire() as conn:
            global_drop_count = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE card_id = $1", c['card_id'])

        owner_mention = get_mention(target_id, owner_name)
        caption = f"""❀ Harem Owner ❝ {owner_mention} ❞

✿ Card Name - <b>{c['name']}</b>{amount_str}
      ☘ ID - <code>{c['card_id']}</code>
✿ Rarity - {r_emoji} {r}
✿ Collection - {col_name}

⌘ Global Drops - <b>{global_drop_count}</b>"""
        
        if c['type'] == 'photo':
            results.append(
                InlineQueryResultCachedPhoto(
                    id=str(uuid.uuid4()),
                    photo_file_id=c['file_id'],
                    title=title,
                    description=description,
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
                    description=description,
                    caption=caption,
                    parse_mode="HTML"
                )
            )

    try:
        next_offset = str(offset + limit) if len(user_cards) == limit else ""
        await query.answer(results, next_offset=next_offset, cache_time=1)
    except Exception:
        pass

@restricted_command
async def cardlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_cardlist_page(update, context, page=0, owner_id=update.effective_user.id)

@restricted_command
async def seelock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_seelock_page(update, context, page=0, owner_id=update.effective_user.id)

async def render_seelock_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0, owner_id: int = None):
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None
    async with db_pool.acquire() as conn:
        cards = await conn.fetch("SELECT card_id, name, type, rarity, collection, is_locked FROM cards WHERE rarity = 'Yugen' ORDER BY card_id ASC")

    if not cards:
        text = "🎴 <b>Yugen card list is empty.</b>"
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)
        else:
            return await update_or_query.edit_message_text(text, parse_mode="HTML")

    per_page = 15
    total_cards = len(cards)
    total_pages = (total_cards + per_page - 1) // per_page

    page = max(0, min(page, total_pages - 1))
    start_idx = page * per_page
    end_idx = start_idx + per_page
    current_page_cards = cards[start_idx:end_idx]

    card_text_list = []
    async with db_pool.acquire() as conn:
        for idx, c in enumerate(current_page_cards, start=start_idx + 1):
            r = c.get('rarity', 'Yugen')
            r_emoji = get_rarity_emoji(r)
            lock_str = "🔒 LOCKED" if c.get('is_locked') else "🔓 UNLOCKED"
            total_drops = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM user_cards WHERE card_id = $1", c['card_id'])
            card_text_list.append(f"{idx}. {r_emoji} <b>{c['name']}</b> (ID: <code>{c['card_id']}</code>) | {lock_str} | Drops: <b>{total_drops}</b>")

    cards_str = "\n".join(card_text_list)

    text = f"""🎐 <b>Yugen Cards Lock Status (Page {page + 1}/{total_pages})</b>

{cards_str}"""

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"seelock_{page - 1}_{owner_id}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"seelock_{page + 1}_{owner_id}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    if isinstance(update_or_query, Update):
        await update_or_query.message.reply_text(text, parse_mode="HTML", reply_markup=markup, reply_to_message_id=msg_id)
    else:
        query = update_or_query
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass

async def render_cardlist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0, owner_id: int = None):
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None
    async with db_pool.acquire() as conn:
        cards = await conn.fetch("SELECT card_id, name, type, rarity, collection, is_locked FROM cards ORDER BY card_id ASC")

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
        r_emoji = get_rarity_emoji(r)
        lock_status = " 🔒[LOCKED]" if c.get('is_locked') else ""
        col_name = c.get('collection') or "—"
        card_text_list.append(f"{idx}. {r_emoji} <b>{c['name']}</b> (ID: <code>{c['card_id']}</code>) [{type_emoji} {c['type'].upper()}]{lock_status}\n     └ {col_name}")

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
        card = await conn.fetchrow("SELECT card_id, name, type, file_id, rarity, collection, is_locked FROM cards WHERE card_id = $1", target_card_id)

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
    r_emoji = get_rarity_emoji(r)
    col_name = card.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"
    lock_str = "\n🔒 <b>Status: Locked</b>" if card.get('is_locked') else ""

    if r == 'Yugen':
        coin_value = "4000-6000"
    elif r == 'Shinsei':
        coin_value = "2000-3000"
    elif r == 'Kiwami':
        coin_value = "1500-1900"
    elif r == 'Kami':
        coin_value = "800-1200"
    elif r == 'Hoshi':
        coin_value = "350-500"
    elif r == 'Ten':
        coin_value = "150-300"
    else:
        coin_value = "150-300"

    caption_text = f"""🎗 Card Information ♡

▰▰▱▱▰▰▱▱
🍀 Name - {card['name']}
    🍀  ID - <code>{card['card_id']}</code>
🎬 Type - {card['type'].upper()}
🌟 Rarity - {r_emoji} {r}
📚 Collection - {col_name}{lock_str}
🩸 Kachi Value ( {coin_value} )
   🐠 Global Drops - <b>{global_drop_count}</b>

▰▰▱▱▰▰▱▱▰▰
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

async def check_group_active(bot, chat_id):
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        if member.status not in ['left', 'kicked']:
            return True
    except Exception:
        pass
    return False

@restricted_command
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:
        u_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        all_groups = await conn.fetch("SELECT chat_id FROM groups")

    tasks = [check_group_active(context.bot, g['chat_id']) for g in all_groups]
    results = await asyncio.gather(*tasks)
    active_g_count = sum(1 for r in results if r)

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

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.message
    if not chat or not msg or not user or user.is_bot:
        return

    await register_user_group(user, chat, context)

    # --- Check for Slot Spin Reply ---
    if msg.reply_to_message and msg.reply_to_message.message_id in active_kslot_spins:
        spin_info = active_kslot_spins[msg.reply_to_message.message_id]
        if msg.from_user.id != spin_info["user_id"]:
            return await msg.reply_text("❌ This is not your slot spin reply!", reply_to_message_id=msg.message_id)
        
        if not msg.dice or msg.dice.emoji != "🎰":
            return await msg.reply_text("❌ ကျေးဇူးပြု၍ Telegram Emoji ထဲမှ 🎰 (Slot Machine) Animation ကို Reply အဖြစ် ပို့ပေးပါ။", reply_to_message_id=msg.message_id)
        
        del active_kslot_spins[msg.reply_to_message.message_id]
        kslot_cooldowns[user.id] = time.time()

        dice_val = msg.dice.value
        symbols, score = decode_slot_dice(dice_val)
        bet_amount = spin_info["bet_amount"]
        user_id = spin_info["user_id"]
        display_name = spin_info["display_name"]

        if score >= 32:
            payout = bet_amount * 3  # Return bet + 2x profit
            result_type = "Win 2x 🏆"
            net_gain = f"+{bet_amount * 2}"
        elif score >= 28:
            payout = int(bet_amount * 2.5)  # Return bet + 1.5x profit
            result_type = "Win 1.5x ✨"
            net_gain = f"+{int(bet_amount * 1.5)}"
        elif score >= 26:
            payout = bet_amount  # Refund 1x
            result_type = "Draw / Refund 1x 🤝"
            net_gain = "0"
        else:
            payout = 0
            result_type = "Loss 0x 💔"
            net_gain = f"-{bet_amount}"

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", payout, user_id)
                updated_user = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user_id)
                new_balance = updated_user['coins'] if updated_user else payout

        sym_str = " | ".join(symbols)
        result_text = f"""🎰 <b>Kachi Slot Machine Result</b>

👤 Player: {get_mention(user_id, display_name)}
🎲 Symbols: <b>{sym_str}</b>
📊 Score: <b>{score}</b>
🎯 Result: <b>{result_type}</b> ({net_gain} Kachi)
💰 Current Balance: <b>{new_balance}</b> Kachi ✨"""

        return await msg.reply_text(result_text, parse_mode="HTML", reply_to_message_id=msg.message_id)
    # ---------------------------------

    if chat.type == "private":
        has_pending = user.id in pending_kachi_transfers
        if has_pending:
            target_id = pending_kachi_transfers[user.id]
            text_input = msg.text.strip() if msg.text else ""
            if not text_input.isdigit():
                return await msg.reply_text("❌ Please enter a valid number for Kachi amount.", reply_to_message_id=msg.message_id)
            
            amount = int(text_input)
            if amount <= 0:
                return await msg.reply_text("❌ Amount must be greater than 0.", reply_to_message_id=msg.message_id)

            async with db_pool.acquire() as conn:
                async with conn.transaction():
                    sender_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1 FOR UPDATE", user.id)
                    sender_coins = sender_row['coins'] if sender_row else 1000
                    sender_name = sender_row['name'] if sender_row else user.first_name

                    if sender_coins < amount:
                        if user.id in pending_kachi_transfers:
                            del pending_kachi_transfers[user.id]
                        return await msg.reply_text(f"❌ Insufficient Kachi balance. (Current: {sender_coins} Kachi)", reply_to_message_id=msg.message_id)

                    target_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1 FOR UPDATE", target_id)
                    target_coins = target_row['coins'] if target_row else 1000
                    target_name = target_row['name'] if target_row else "User"

                    new_sender_coins = max(0, sender_coins - amount)
                    new_target_coins = target_coins + amount

                    await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_sender_coins, user.id)
                    await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_target_coins, target_id)

            if user.id in pending_kachi_transfers:
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

        is_spamming = len(user_message_timestamps[key]) >= 4
        if is_spamming:
            spam_ignores[key] = now + 600
            user_message_timestamps[key] = []

        if is_spamming:
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
            async with db_pool.acquire() as conn:
                async with conn.transaction():
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
    try:
        anim_msg = await context.bot.send_message(chat_id, "🐌")
    except Exception:
        anim_msg = None

    await asyncio.sleep(4)
    if anim_msg:
        try:
            await context.bot.delete_message(chat_id, anim_msg.message_id)
        except Exception:
            pass

    async with db_pool.acquire() as conn:
        drop_card = await get_weighted_random_card(conn)
    if not drop_card:
        return

    r = drop_card.get('rarity', 'Ten')
    r_emoji = get_rarity_emoji(r)

    joined_names = []
    joined_str = "\n".join(joined_names) if joined_names else "<i>No one joined yet.</i>"

    drop_text = f"""{r_emoji} A Character Card Spawned In The Chat ❄

[ 𝗝O𝗜𝗡 ] Fast For The Claim
 Card ❀

{joined_str}

GoodLuck 🍀 Time (50sec)"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("𝗝𝗢𝗜𝗡(0/5)", callback_data="join_card_drop")
    ]])

    try:
        if drop_card['type'] == 'photo':
            msg = await context.bot.send_photo(chat_id, drop_card['file_id'], caption=drop_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            msg = await context.bot.send_video(chat_id, drop_card['file_id'], caption=drop_text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        return

    active_card_drops[msg.message_id] = {
        "chat_id": chat_id,
        "card": drop_card,
        "joined_users": {},
        "timer": 50,
        "ended": False
    }

    asyncio.create_task(run_card_drop_timer(context, msg.message_id))

async def run_card_drop_timer(context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    while True:
        await asyncio.sleep(5)
        drop = active_card_drops.get(msg_id)
        if not drop or drop["ended"]:
            break

        drop["timer"] -= 5
        if drop["timer"] <= 0 or len(drop["joined_users"]) >= 5:
            drop["ended"] = True
            should_finalize = True
        else:
            should_finalize = False
            current_count = len(drop["joined_users"])
            chat_id = drop["chat_id"]
            card_copy = drop["card"]
            joined_copy = dict(drop["joined_users"])
            timer_val = drop["timer"]

        if should_finalize:
            await finalize_card_drop(context, msg_id)
            break

        r = card_copy.get('rarity', 'Ten')
        r_emoji = get_rarity_emoji(r)

        joined_names = [f"• {get_mention(uid, name)}" for uid, name in joined_copy.items()]
        joined_str = "\n".join(joined_names) if joined_names else "<i>No one joined yet.</i>"

        drop_text = f"""{r_emoji} A Character Card Spawned In The Chat ❄

[ 𝗝𝗢𝗜𝗡 ] Fast For The Claim
 Card ❀

{joined_str}

GoodLuck 🍀 Time ({timer_val}sec)"""

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"𝗝𝗢𝗜𝗡({current_count}/5)", callback_data="join_card_drop")
        ]])

        try:
            await context.bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=drop_text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass

async def finalize_card_drop(context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    drop = active_card_drops.get(msg_id)
    if not drop or drop.get("finalized"):
        return
    drop["finalized"] = True
    drop["ended"] = True

    chat_id = drop["chat_id"]
    card = drop["card"]
    joined = dict(drop["joined_users"])
    
    if msg_id in active_card_drops:
        del active_card_drops[msg_id]

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass

    try:
        anim_msg = await context.bot.send_message(chat_id, "🐸")
    except Exception:
        anim_msg = None

    await asyncio.sleep(4)
    if anim_msg:
        try:
            await context.bot.delete_message(chat_id, anim_msg.message_id)
        except Exception:
            pass

    if joined:
        winner_id, winner_name = random.choice(list(joined.items()))
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
                """, winner_id, card['card_id'])
                await check_and_auto_lock_card(conn, card['card_id'])

        r = card.get('rarity', 'Ten')
        r_emoji = get_rarity_emoji(r)
        col_name = card.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"
        win_msg = f"⛩ Congratulations , {get_mention(winner_id, winner_name)} Now you got A new Card {card['name']} ID: {card['card_id']} Rarity: {r_emoji} {r} | Collection: {col_name} ❄ Check /kc 🎗"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Harem❄", switch_inline_query_current_chat=f"harem.{winner_id}")]
        ])

        try:
            if card['type'] == 'photo':
                await context.bot.send_photo(chat_id, photo=card['file_id'], caption=win_msg, parse_mode="HTML", reply_markup=keyboard)
            else:
                await context.bot.send_video(chat_id, video=card['file_id'], caption=win_msg, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            try:
                await context.bot.send_message(chat_id, text=win_msg, parse_mode="HTML", reply_markup=keyboard)
            except Exception:
                pass
    else:
        win_msg = f"❌ Card drop for <b>{card['name']}</b> cancelled as no one joined."
        try:
            await context.bot.send_message(chat_id, text=win_msg, parse_mode="HTML")
        except Exception:
            pass

async def run_kbox_task(bot, chat_id, query, user_id, display_name):
    try:
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
            async with conn.transaction():
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
                await check_and_auto_lock_card(conn, card['card_id'])

        r = card.get('rarity', 'Ten')
        r_emoji = get_rarity_emoji(r)
        col_name = card.get('collection') or "🎞 Ope Ope No Mi [ 🩺]"

        result_caption = f"""🎉 Congratulations! {get_mention(user_id, display_name)} You got a card!
Card Name : {card['name']}
Id : <code>{card['card_id']}</code>
Rarity : {r_emoji} {r}
Collection : {col_name}

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
            try:
                await bot.send_message(chat_id=chat_id, text=result_caption, parse_mode="HTML")
            except Exception:
                pass
    finally:
        active_kbox_users.discard(user_id)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    data = query.data

    await register_user_group(user, query.message.chat, context)

    # --- Callbacks for /kslot ---
    if data.startswith("kslot_bet_"):
        parts = data.split("_")
        allowed_uid = int(parts[2])
        bet_amount = int(parts[3])

        if user.id != allowed_uid:
            return await query.answer("❌ This is not your game! Please use /kslot to start your own game.", show_alert=True)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                user_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1 FOR UPDATE", user.id)
                current_coins = user_row['coins'] if user_row else 1000
                display_name = user_row['name'] if user_row else user.first_name

                if current_coins < bet_amount:
                    return await query.answer(f"❌ Insufficient Kachi balance! Your current balance is <b>{current_coins}</b> Kachi.", show_alert=True)

                new_balance = current_coins - bet_amount
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_balance, user.id)

        try:
            sent_msg = await query.edit_message_text(
                f"Now You Spin To Slot 🎰 with Replay\n\n👤 Player: {get_mention(user.id, display_name)}\n🩸 Bet Amount: <b>{bet_amount}</b> Kachi\n\n<i>👇 ကျေးဇူးပြု၍ ဤစာကို Reply လုပ်၍ Telegram Emoji ထဲမှ 🎰 (Slot Machine) ကို ပို့ပေးပါ။</i>",
                parse_mode="HTML",
                reply_markup=None
            )
            active_kslot_spins[sent_msg.message_id] = {
                "user_id": user.id,
                "bet_amount": bet_amount,
                "display_name": display_name
            }
        except Exception:
            pass
        return await query.answer("🎯 Slot spin ready! Please reply with 🎰 emoji.")
    # ----------------------------

    if data.startswith("buy_confirm_"):
        parts = data.split("_")
        allowed_buyer_id = int(parts[2])
        seller_id = int(parts[3])

        if user.id != allowed_buyer_id and user.id != ADMIN_ID:
            return await query.answer("❌ Only the authorized buyer can click this.", show_alert=True)

        buy_info = pending_card_buys.get(msg_id)
        
        if not buy_info:
            return await query.answer("❌ Purchase session expired or already completed.", show_alert=True)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                missing_cards = []
                for item in buy_info["items"]:
                    c_id = item['card_id']
                    req_amount = item['amount']
                    uc_row = await conn.fetchrow("""
                        SELECT amount FROM user_cards WHERE user_id = $1 AND (
                            card_id = $2 OR ltrim(card_id, '0') = ltrim($2, '0')
                        ) FOR UPDATE
                    """, seller_id, c_id)
                    owned = uc_row['amount'] if uc_row else 0
                    if owned < req_amount:
                        missing_cards.append(c_id)

                if missing_cards:
                    if msg_id in pending_card_buys:
                        del pending_card_buys[msg_id]
                    return await query.answer("❌ Seller no longer owns the required cards/amounts!", show_alert=True)

                for item in buy_info["items"]:
                    c_id = item['card_id']
                    req_amount = item['amount']
                    uc_row = await conn.fetchrow("""
                        SELECT card_id, amount FROM user_cards WHERE user_id = $1 AND (
                            card_id = $2 OR ltrim(card_id, '0') = ltrim($2, '0')
                        ) FOR UPDATE
                    """, seller_id, c_id)
                    if not uc_row:
                        continue
                    actual_c_id = uc_row['card_id']
                    current_amt = uc_row['amount']
                    new_amt = current_amt - req_amount
                    if new_amt <= 0:
                        await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = $2", seller_id, actual_c_id)
                    else:
                        await conn.execute("UPDATE user_cards SET amount = $1 WHERE user_id = $2 AND card_id = $3", new_amt, seller_id, actual_c_id)

        if msg_id in pending_card_buys:
            del pending_card_buys[msg_id]

        success_text = f"""✅ <b>Purchase Successful & Cards Removed!</b>

👤 <b>Buyer:</b> {get_mention(buy_info['buyer_id'], user.first_name)}
👤 <b>Seller:</b> {get_mention(seller_id, buy_info['seller_name'])}

🎴 Cards successfully removed from seller's inventory."""

        try:
            await query.edit_message_text(text=success_text, parse_mode="HTML", reply_markup=None)
        except Exception:
            pass
        return await query.answer("✅ Cards purchased and removed successfully!")

    if data.startswith("kbox_open_"):
        allowed_uid = int(data.split("_")[2])
        if user.id != allowed_uid:
            return await query.answer("❌ This is not your Kbox button!", show_alert=True)

        if user.id in active_kbox_users:
            return await query.answer("❌ သင့်၏ Kbox တစ်ခုမှာ ယခုလက်ရှိ ဖွင့်ဆိုဆဲဖြစ်ပါသည်၊ ပြီးဆုံးသည်အထိ စောင့်ပါရန်။", show_alert=True)
        active_kbox_users.add(user.id)

        now = int(time.time())
        cooldown = 86400

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                user_row = await conn.fetchrow("SELECT coins, name, kbox_count, last_kbox_reset FROM users WHERE user_id = $1 FOR UPDATE", user.id)
                current_coins = user_row['coins'] if user_row else 1000
                display_name = user_row['name'] if user_row else user.first_name
                kbox_count = user_row['kbox_count'] if user_row else 0
                last_kbox_reset = user_row['last_kbox_reset'] if user_row else 0

                if now - last_kbox_reset >= cooldown:
                    kbox_count = 0
                    last_kbox_reset = now

                if kbox_count >= 7:
                    active_kbox_users.discard(user.id)
                    return await query.answer("❌ /kbox ကို တစ်နေ့လျှင် 7 ကြိမ်သာ ဖွင့်လှစ်နိုင်ပါတော့သည်။", show_alert=True)

                if current_coins < 300:
                    active_kbox_users.discard(user.id)
                    return await query.answer(f"❌ Insufficient Kachi! You need 300 Kachi (Current: {current_coins}).", show_alert=True)

                new_balance = current_coins - 300
                kbox_count += 1
                await conn.execute("UPDATE users SET coins = $1, kbox_count = $2, last_kbox_reset = $3 WHERE user_id = $4", new_balance, kbox_count, last_kbox_reset, user.id)

        asyncio.create_task(run_kbox_task(context.bot, chat_id, query, user.id, display_name))
        await query.answer("🎉 Opening Kbox...")
        return

    # --- Callbacks for /khmode ---
    if data.startswith("khset_"):
        parts = data.split("_")
        allowed_uid = int(parts[1])
        rarity = parts[2]

        if user.id != allowed_uid:
            return await query.answer("❌ This is not for you!", show_alert=True)

        confirm_text = f"Are You Sure To Set This Rarity On Kc\n\n📌 Selected Rarity: {get_emoji_for_rarity_str(rarity)} {rarity}"
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Cancel ❌", callback_data=f"khcancel_{user.id}"),
                InlineKeyboardButton("Confirm ✅", callback_data=f"khconfirm_{user.id}_{rarity}")
            ],
            [
                InlineKeyboardButton("◀️ Back Menu", callback_data=f"khback_{user.id}")
            ]
        ])
        try:
            await query.edit_message_text(confirm_text, parse_mode="HTML", reply_markup=confirm_keyboard)
        except Exception:
            pass
        await query.answer()
        return

    if data.startswith("khcancel_"):
        allowed_uid = int(data.split("_")[1])
        if user.id != allowed_uid:
            return await query.answer("❌ This is not for you!", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.answer("Cancelled.")
        return

    if data.startswith("khback_"):
        allowed_uid = int(data.split("_")[1])
        if user.id != allowed_uid:
            return await query.answer("❌ This is not for you!", show_alert=True)
        
        text = "🎯 <b>Select Rarity Mode for /kc</b>\n\nကျေးဇူးပြု၍ စုပြလိုသော Rarity တစ်ခုကို ရွေးချယ်ပေးပါ -"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎐 Yugen", callback_data=f"khset_{user.id}_Yugen"),
                InlineKeyboardButton("🧬 Shinsei", callback_data=f"khset_{user.id}_Shinsei")
            ],
            [
                InlineKeyboardButton("🪞 Kiwami", callback_data=f"khset_{user.id}_Kiwami"),
                InlineKeyboardButton("✨ Kami", callback_data=f"khset_{user.id}_Kami")
            ],
            [
                InlineKeyboardButton("⚜️ Hoshi", callback_data=f"khset_{user.id}_Hoshi"),
                InlineKeyboardButton("💮 Ten", callback_data=f"khset_{user.id}_Ten")
            ]
        ])
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
        await query.answer()
        return

    if data.startswith("khconfirm_"):
        parts = data.split("_")
        allowed_uid = int(parts[1])
        rarity = parts[2]

        if user.id != allowed_uid:
            return await query.answer("❌ This is not for you!", show_alert=True)

        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET kc_rarity_mode = $1 WHERE user_id = $2", rarity, user.id)

        try:
            await query.edit_message_text(
                f"✅ <b>Successfully set rarity mode to {get_emoji_for_rarity_str(rarity)} {rarity}!</b>\n\nယခုမှစ၍ `/kc` တွင် ဤ Rarity ကတ်များကိုသာ သီးသန့်ပြသပေးမည် ဖြစ်ပါသည်။",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await query.answer("✅ Rarity mode updated successfully!")
        return
    # -----------------------------

    # --- Callbacks for /kshop ---
    if data.startswith("kshop_rarity_"):
        parts = data.split("_")
        allowed_uid = int(parts[2])
        rarity = parts[3]

        if user.id != allowed_uid:
            return await query.answer("❌ This is not for you!", show_alert=True)

        await render_kshop_card(query, context, user.id, rarity, 0)
        await query.answer()
        return

    if data.startswith("kshop_nav_"):
        parts = data.split("_")
        allowed_uid = int(parts[2])
        rarity = parts[3]
        target_idx = int(parts[4])

        if user.id != allowed_uid:
            return await query.answer("❌ This is not for you!", show_alert=True)

        await render_kshop_card(query, context, user.id, rarity, target_idx)
        await query.answer()
        return

    if data.startswith("kshop_buy_"):
        parts = data.split("_")
        allowed_uid = int(parts[2])
        rarity = parts[3]
        card_id = parts[4]
        price = int(parts[5])

        if user.id != allowed_uid:
            return await query.answer("❌ This is not for you!", show_alert=True)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
                coins = user_row['coins'] if user_row else 1000

                if coins < price:
                    return await query.answer(f"❌ Insufficient Kachi! You need {price} Kachi (Current: {coins}).", show_alert=True)

                new_coins = coins - price
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_coins, user.id)

                await conn.execute("""
                    INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
                """, user.id, card_id)
                await check_and_auto_lock_card(conn, card_id)

                card_info = await conn.fetchrow("SELECT name FROM cards WHERE card_id = $1", card_id)
                card_name = card_info['name'] if card_info else card_id

        return await query.answer(f"✅ Successfully bought {card_name} for {price} Kachi!", show_alert=True)

    if data.startswith("kshop_back_"):
        allowed_uid = int(data.split("_")[2])
        if user.id != allowed_uid:
            return await query.answer("❌ This is not for you!", show_alert=True)

        text = f"""Hello {user.first_name}
You can buy the highest-tier 🎐Yugen / 🧬Shinsei / 🪞 Kiwami rarity cards here"""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎐 Yugen", callback_data=f"kshop_rarity_{user.id}_Yugen"),
                InlineKeyboardButton("🧬 Shinsei", callback_data=f"kshop_rarity_{user.id}_Shinsei")
            ],
            [
                InlineKeyboardButton("🪞 Kiwami", callback_data=f"kshop_rarity_{user.id}_Kiwami")
            ]
        ])
        try:
            await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            try:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)
            except Exception:
                pass
        await query.answer()
        return
    # ----------------------------

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
            solved = True
        else:
            solved = False
            if user.id in quiz["answered_users"]:
                already_answered = True
            else:
                already_answered = False
                quiz["answered_users"].add(user.id)

        if solved:
            return await query.answer("❌ အဖြေမှန်ကို အခြားသူ ဖြေဆိုပြီးပါပြီ (သို့မဟုတ်) Quiz ပြီးဆုံးသွားပါပြီ။", show_alert=True)

        if already_answered:
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
            quiz["wrong_users"].add(user.id)
            wrong_count = len(quiz["wrong_users"])
            is_exhausted = wrong_count >= 2
            if is_exhausted:
                quiz["solved"] = True

            if is_exhausted:
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
        try:
            await query.edit_message_text(help_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        await query.answer()
        return

    if data == "menu_kgift":
        kgift_text = """🎁 <b>လက်ဆောင်ပေးခြင်း (Gift) လမ်းညွှန်ချက်များ</b>

user တစ်ဦး၏ စာကို reply လုပ်၍ အောက်ပါအတိုင်း ပေးပို့ပါ -
- /kgift [card_id] - သတ်မှတ်ထားသော ကတ်တစ်ခု ပေးပို့ရန် (ဥပမာ - /kgift 1201)"""
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="menu_back")]])
        try:
            await query.edit_message_text(kgift_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        await query.answer()
        return

    if data == "menu_ksellcard":
        bot_info = await context.bot.get_me()
        ksell_text = f"""💸 <b>Heyy Wanna Sell Card? So Come Dm</b>

ကဒ်ရောင်းလိုပါက Bot ၏ DM (Private Chat) သို့သွားရောက်၍ အောက်ပါပုံစံအတိုင်း ရိုက်ထည့်ပေးပါ -
👉 `/ksellcard [card_id] [card_id]x[amount]`
ဥပမာ: `/ksellcard 1296 827x2`"""
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Sell Card 💸", url=f"https://t.me/{bot_info.username}?start=sellcard")],
            [InlineKeyboardButton("◀️ Back", callback_data="menu_back")]
        ])
        try:
            await query.edit_message_text(ksell_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
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
                InlineKeyboardButton("Sell Card 💸", callback_data="menu_ksellcard")
            ],
            [
                InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{bot_info.username}?startgroup=true")
            ]
        ])
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
        await query.answer()
        return

    if data.startswith("addrarity_"):
        parts = data.split("_")
        allowed_uid = int(parts[1])
        rarity = parts[2]

        if user.id != allowed_uid:
            return await query.answer("❌ Not for you.", show_alert=True)

        if rarity == 'Yugen' and user.id != ADMIN_ID:
            return await query.answer("❌ Only the Bot Admin can add Yugen rarity cards!", show_alert=True)

        card_info = pending_card_adds.get(user.id)
        if card_info:
            del pending_card_adds[user.id]

        if not card_info:
            return await query.answer("❌ Card addition session expired.", show_alert=True)

        card_info["rarity"] = rarity

        collections_list = [
            "🎞 Ope Ope No Mi [ 🩺]",
            "🎞 Hito Hito No Mi [🌕]",
            "🎞 Mera Mera No Mi [🔥]",
            "🎞 Hana Hana No Mi [🌸]",
            "🎞 Yomi Yomi No Mi [💀]",
            "🎞 Tori Tori No Mi [🦅]",
            "🎞 Yami Yami No Mi [🌑]"
        ]
        selected_collection = random.choice(collections_list)

        card_id = card_info["card_id"]
        card_name = card_info["card_name"]
        c_type = card_info["type"]
        file_id = card_info["file_id"]
        is_card_admin = card_info["is_card_admin"]
        
        is_locked = True if rarity == 'Yugen' else False

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO cards (card_id, name, type, file_id, rarity, collection, is_locked)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, card_id, card_name, c_type, file_id, rarity, selected_collection, is_locked)

                added_reward_coins = 50 if rarity in ["Hoshi", "Ten"] else (80 if rarity in ["Kiwami", "Kami"] else (120 if rarity == 'Shinsei' else 150))

                if is_card_admin and user.id != ADMIN_ID:
                    await conn.execute("""
                        UPDATE users 
                        SET coins = GREATEST(0, coins + $1) 
                        WHERE user_id = $2
                    """, added_reward_coins, user.id)

        r_emoji = get_rarity_emoji(rarity)
        lock_msg_note = "\n🔒 <i>Status: Locked (Will not drop until /unlock is used)</i>" if is_locked else ""
        log_text = f"""New card added successfully

❀ Card Name : {card_name}
     ❝  ID : {card_id}
❀ Type : {c_type.capitalize()}
🌟 Rarity : {r_emoji} {rarity}
📚 Collection : {selected_collection}{lock_msg_note}
👤 Added By : {get_mention(user.id, user.first_name)}"""

        try:
            if c_type == "photo":
                await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=file_id, caption=log_text, parse_mode="HTML")
            else:
                await context.bot.send_video(chat_id=LOG_CHANNEL_ID, video=file_id, caption=log_text, parse_mode="HTML")
        except Exception:
            pass

        reward_notice = f"\n🎉 Received <b>+{added_reward_coins} Kachi</b> for adding card!" if (is_card_admin and user.id != ADMIN_ID) else ""
        try:
            await query.message.edit_text(
                f"✅ Card added successfully!\n\n🆔 Card ID: <code>{card_id}</code>\n🎴 Name: {card_name}\n🌟 Rarity: {r_emoji} {rarity}\n📚 Collection: {selected_collection}{lock_msg_note}{reward_notice}",
                parse_mode="HTML"
            )
        except Exception:
            pass
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

    if data == "join_card_drop":
        drop = active_card_drops.get(msg_id)
        if not drop or drop["ended"]:
            ended = True
        else:
            ended = False
            if user.id in drop["joined_users"]:
                already_joined = True
            else:
                already_joined = False
                if len(drop["joined_users"]) >= 5:
                    full = True
                else:
                    full = False
                    drop["joined_users"][user.id] = user.first_name
                    current_count = len(drop["joined_users"])
                    is_full_now = current_count >= 5

        if ended:
            return await query.answer("❌ This card drop has ended.", show_alert=True)

        if already_joined:
            return await query.answer("❌ You have already joined.", show_alert=True)

        if full:
            return await query.answer("❌ Drop is full (5/5)!", show_alert=True)

        await query.answer("✅ Successfully joined card drop!", show_alert=True)

        if is_full_now:
            await finalize_card_drop(context, msg_id)
        else:
            r = drop["card"].get('rarity', 'Ten')
            r_emoji = get_rarity_emoji(r)

            joined_names = [f"• {get_mention(uid, name)}" for uid, name in drop["joined_users"].items()]
            joined_str = "\n".join(joined_names) if joined_names else "<i>No one joined yet.</i>"

            drop_text = f"""{r_emoji} A Character Card Spawned In The Chat ❄

[ 𝗝𝗢𝗜𝗡 ] Fast For The Claim
 Card ❀

{joined_str}

GoodLuck 🍀 Time ({drop['timer']}sec)"""

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"𝗝𝗢𝗜𝗡({current_count}/5)", callback_data="join_card_drop")
            ]])

            try:
                await query.edit_message_caption(caption=drop_text, parse_mode="HTML", reply_markup=keyboard)
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
        if gift_info:
            del pending_gifts[msg_id]

        if not gift_info:
            return await query.answer("❌ Gift transfer expired.", show_alert=True)

        if action == "cancel":
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
                async with conn.transaction():
                    card_id = gift_info["card_id"]
                    card_name = gift_info["card_name"]

                    s_card = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2 FOR UPDATE", sender_id, card_id)
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
                    await check_and_auto_lock_card(conn, card_id)

                    success_text = f"✅ {get_mention(sender_id, user.first_name)} sent <b>{card_name}</b> (ID: <code>{card_id}</code>) to {get_mention(receiver_id, receiver_name)}!"

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

    if data.startswith("seelock_"):
        parts = data.split("_")
        page = int(parts[1])
        owner_id = int(parts[2]) if len(parts) > 2 else None

        if owner_id and user.id != owner_id:
            return await query.answer("❌ Not your seelock view.", show_alert=True)
        if user.id != ADMIN_ID:
            return await query.answer("❌ Admin only.", show_alert=True)

        await render_seelock_page(query, context, page=page, owner_id=owner_id)
        await query.answer()
        return

def get_emoji_for_rarity_str(rarity):
    if rarity == 'Yugen':
        return "🎐"
    elif rarity == 'Shinsei':
        return "🧬"
    elif rarity == 'Kiwami':
        return "🪞"
    elif rarity == 'Kami':
        return "✨"
    elif rarity == 'Hoshi':
        return "⚜️"
    else:
        return "💮"

async def post_init(app: Application):
    await init_db()

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # Public User Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("pre", pre_cmd))
    app.add_handler(CommandHandler("kc", check_kc_cmd))
    app.add_handler(CommandHandler("khmode", khmode_cmd))
    app.add_handler(CommandHandler("resethmode", resethmode_cmd))
    app.add_handler(CommandHandler("kshop", kshop_cmd))
    app.add_handler(CommandHandler("kachi", kachi_cmd))
    app.add_handler(CommandHandler("klot", klot_cmd))
    app.add_handler(CommandHandler("kslot", kslot_cmd))  # <-- Newly added command handler
    app.add_handler(CommandHandler("kbox", kbox_cmd))
    app.add_handler(CommandHandler("kdaily", kdaily_cmd))
    app.add_handler(CommandHandler("set", set_card_cmd))
    app.add_handler(CommandHandler("kgift", kgift_cmd))
    app.add_handler(CommandHandler("ksellcard", ksellcard_cmd))
    app.add_handler(CommandHandler("card", card_detail_cmd))
    app.add_handler(CommandHandler("ktop", ktop_cmd))
    app.add_handler(CommandHandler("kgtop", kgtop_cmd))

    # Admin Commands
    app.add_handler(CommandHandler("aa", aa_cmd))
    app.add_handler(CommandHandler("send", send_quiz_cmd))
    app.add_handler(CommandHandler("cardlist", cardlist_cmd))
    app.add_handler(CommandHandler("seelock", seelock_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("crest", crest_cmd))
    app.add_handler(CommandHandler("glist", glist_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("k", admin_coin_cmd))
    app.add_handler(CommandHandler("addadmin", addadmin_cmd))
    app.add_handler(CommandHandler("badmin", badmin_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("got", got_card_cmd))
    app.add_handler(CommandHandler("add", add_card_cmd))
    app.add_handler(CommandHandler("unlock", unlock_card_cmd))
    app.add_handler(CommandHandler("lock", lock_card_cmd))
    app.add_handler(CommandHandler("spw", spw_cmd))
    app.add_handler(CommandHandler("del", del_card_cmd))
    app.add_handler(CommandHandler("check", check_user_cmd))

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
