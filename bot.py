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

TEAMS = [
    # Premier League
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
    {"name": "Burnley", "stadium": "Turf Moor", "emoji": "🟣"},
    {"name": "Sheffield United", "stadium": "Bramall Lane", "emoji": "🔴"},
    {"name": "Luton Town", "stadium": "Kenilworth Road", "emoji": "🟠"},
    
    # La Liga
    {"name": "Real Madrid", "stadium": "Santiago Bernabéu", "emoji": "👑"},
    {"name": "Barcelona", "stadium": "Camp Nou", "emoji": "🔵🔴"},
    {"name": "Atletico Madrid", "stadium": "Metropolitano Stadium", "emoji": "🔴⚪"},
    {"name": "Real Sociedad", "stadium": "Reale Arena", "emoji": "🔵⚪"},
    {"name": "Athletic Bilbao", "stadium": "San Mamés", "emoji": "🔴⚪"},
    {"name": "Real Betis", "stadium": "Benito Villamarín", "emoji": "💚"},
    {"name": "Villarreal", "stadium": "Estadio de la Cerámica", "emoji": "🟡"},
    {"name": "Sevilla", "stadium": "Ramón Sánchez Pizjuán", "emoji": "🔴"},
    {"name": "Valencia", "stadium": "Mestalla", "emoji": "🦇"},
    {"name": "Girona", "stadium": "Montilivi", "emoji": "🔴⚪"},

    # Serie A
    {"name": "Inter Milan", "stadium": "San Siro", "emoji": "🔵⚫"},
    {"name": "AC Milan", "stadium": "San Siro", "emoji": "🔴⚫"},
    {"name": "Juventus", "stadium": "Allianz Stadium", "emoji": "🏳️"},
    {"name": "Napoli", "stadium": "Stadio Diego Armando Maradona", "emoji": "🔵"},
    {"name": "AS Roma", "stadium": "Stadio Olimpico", "emoji": "🟡🔴"},
    {"name": "Lazio", "stadium": "Stadio Olimpico", "emoji": "🦅"},
    {"name": "Atalanta", "stadium": "Gewiss Stadium", "emoji": "🔵⚫"},
    {"name": "Fiorentina", "stadium": "Stadio Artemio Franchi", "emoji": "🟣"},
    {"name": "Bologna", "stadium": "Stadio Renato Dall'Ara", "emoji": "🔴🔵"},
    {"name": "Torino", "stadium": "Stadio Olimpico Grande Torino", "emoji": "🐂"},

    # Bundesliga
    {"name": "Bayern Munich", "stadium": "Allianz Arena", "emoji": "🔴"},
    {"name": "Borussia Dortmund", "stadium": "Signal Iduna Park", "emoji": "🟡"},
    {"name": "Bayer Leverkusen", "stadium": "BayArena", "emoji": "🔴⚫"},
    {"name": "RB Leipzig", "stadium": "Red Bull Arena", "emoji": "🔴⚪"},
    {"name": "Eintracht Frankfurt", "stadium": "Deutsche Bank Park", "emoji": "🦅"},
    {"name": "VfB Stuttgart", "stadium": "MHPArena", "emoji": "⚪🔴"},
    {"name": "Wolfsburg", "stadium": "Volkswagen Arena", "emoji": "🐺"},
    {"name": "Borussia Mönchengladbach", "stadium": "Borussia-Park", "emoji": "🟢"},
    {"name": "Werder Bremen", "stadium": "Weserstadion", "emoji": "🟢⚪"},
    {"name": "Union Berlin", "stadium": "Stadion An der Alten Försterei", "emoji": "🔴"},

    # Ligue 1 & Others
    {"name": "PSG", "stadium": "Parc des Princes", "emoji": "🔵🔴"},
    {"name": "Marseille", "stadium": "Orange Velodrome", "emoji": "🩵"},
    {"name": "Lyon", "stadium": "Groupama Stadium", "emoji": "🔴🔵"},
    {"name": "Monaco", "stadium": "Stade Louis II", "emoji": "🔴⚪"},
    {"name": "Lille", "stadium": "Decathlon Arena", "emoji": "🔴"},
    {"name": "Ajax", "stadium": "Johan Cruijff ArenA", "emoji": "⚪🔴"},
    {"name": "PSV", "stadium": "Philips Stadion", "emoji": "🔴⚪"},
    {"name": "Feyenoord", "stadium": "De Kuip", "emoji": "🔴⚪"},
    {"name": "Porto", "stadium": "Estádio do Dragão", "emoji": "🔵"},
    {"name": "Benfica", "stadium": "Estádio da Luz", "emoji": "🦅"},
    {"name": "Sporting CP", "stadium": "Estádio José Alvalade", "emoji": "🟢"},
    {"name": "Galatasaray", "stadium": "Rams Park", "emoji": "🟡🔴"},
    {"name": "Fenerbahce", "stadium": "Şükrü Saracoğlu Stadium", "emoji": "🟡🔵"},
    {"name": "Besiktas", "stadium": "Vodafone Park", "emoji": "⚫⚪"},
    {"name": "Celtic", "stadium": "Celtic Park", "emoji": "🍀"},
    {"name": "Rangers", "stadium": "Ibrox Stadium", "emoji": "🔵"},
    {"name": "Al Nassr", "stadium": "Al-Awwal Park", "emoji": "🟡"},
    {"name": "Al Hilal", "stadium": "Kingdom Arena", "emoji": "🔵"},
    {"name": "Inter Miami", "stadium": "Chase Stadium", "emoji": "🩷"},
    {"name": "Boca Juniors", "stadium": "La Bombonera", "emoji": "💙💛"},
]

# Global Memory Stores
group_threshold = {}
active_games = {}       # game_id -> game_state
dm_game_previews = {}   # game_id -> game_info (Multiple previews stored with unique IDs)
last_results = {}
active_cboxes = {}
pending_gifts = {}
team_creation_state = {}
pending_joins = {}
active_card_drops = {}
pending_card_adds = {}
pending_quizzes = {}
active_quizzes = {}
last_game_times = {}
game_media = None
result_media = None
global_default_threshold = 60  # Updated to 60 as requested
bot_warned_groups = set()

# Anti-Spam Tracking Stores
user_message_timestamps = {}
spam_ignores = {}

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
                popular_votes BIGINT DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS custom_teams (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE,
                stadium TEXT,
                emoji TEXT
            );
        """)

        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS selected_card_id TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wins BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_games BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vote_tickets BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_popular BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS popular_votes BIGINT DEFAULT 0;")
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

        db_custom_teams = await conn.fetch("SELECT name, stadium, emoji FROM custom_teams")
        for ct in db_custom_teams:
            team_dict = {"name": ct['name'], "stadium": ct['stadium'] or f"{ct['name']} Stadium", "emoji": ct['emoji'] or "⚽"}
            if not any(t['name'].lower() == ct['name'].lower() for t in TEAMS):
                TEAMS.append(team_dict)

        existing_cards = await conn.fetch("SELECT card_id, type FROM cards WHERE rarity IS NULL AND card_id != 'gemstone'")
        for c in existing_cards:
            if c['type'] == 'photo':
                r = random.choice(["Hoshi", "Ten"])
            else:
                r = random.choice(["Kiwami", "Kami"])
            await conn.execute("UPDATE cards SET rarity = $1 WHERE card_id = $2", r, c['card_id'])

        await conn.execute("DELETE FROM cards WHERE card_id = 'gemstone';")

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
                    INSERT INTO users (user_id, name) VALUES ($1, $2)
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
        await conn.execute(
            "UPDATE users SET coins = GREATEST(0, coins + $1) WHERE user_id = $2",
            amount, user_id
        )

def get_mention(user_id, name):
    clean_name = (name or "User").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_id}">{clean_name}</a>'

async def get_weighted_random_card(conn):
    cards = await conn.fetch("SELECT card_id, name, type, file_id, rarity FROM cards WHERE card_id != 'gemstone'")
    if not cards:
        return None
    return random.choice(cards)

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

async def get_user_card_media(user_id: int):
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT selected_card_id FROM users WHERE user_id = $1", user_id)
        selected_card_id = user_row['selected_card_id'] if user_row else None

        user_cards = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id, c.rarity 
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

async def team_reset_checker(context: ContextTypes.DEFAULT_TYPE):
    while True:
        await asyncio.sleep(60)
        try:
            async with db_pool.acquire() as conn:
                last_reset_row = await conn.fetchrow("SELECT value FROM settings WHERE key='last_team_reset'")
                last_reset = int(last_reset_row['value']) if last_reset_row else int(time.time())
                now = int(time.time())

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
                                    f"🎉 <b>Congratulations!</b> Your team <b>{team['team_name']}</b> reached Top 5! Received <b>1 GemStone 💎</b>.",
                                    parse_mode="HTML"
                                )
                            except Exception:
                                pass

                    await conn.execute("UPDATE users SET wins = 0, total_games = 0")
                    await conn.execute("UPDATE settings SET value = $1 WHERE key = 'last_team_reset'", str(now))
        except Exception:
            pass

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

# Coin Box Command
@restricted_command
async def cbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    chat = update.effective_chat
    user = update.effective_user
    msg_id = update.message.message_id

    if user.id != ADMIN_ID:
        return

    if chat.type not in ["group", "supergroup"]:
        return await update.message.reply_text("❌ This command can only be used in groups.", reply_to_message_id=msg_id)

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/cbox [amount]` (e.g. `/cbox 2000`)", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        total_amount = int(context.args[0])
        if total_amount <= 0:
            return await update.message.reply_text("❌ Amount must be greater than 0.", reply_to_message_id=msg_id)
    except ValueError:
        return await update.message.reply_text("❌ Please enter a valid number.", reply_to_message_id=msg_id)

    text = f"""🎁 <b>Kachi Coin Box Spawned!</b> 🩸

💰 <b>Remaining Amount:</b> <code>{total_amount}</code> 🩸
👤 <b>Creator:</b> {get_mention(user.id, user.first_name)}

📋 <b>Claimed List:</b>
<i>No one has claimed yet.</i>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🏴‍☠️ Claim", callback_data="claim_cbox")
    ]])

    sent_msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

    active_cboxes[sent_msg.message_id] = {
        "total_amount": total_amount,
        "remaining": total_amount,
        "creator": user.first_name,
        "claimed_users": {},
    }

# /start Command
@restricted_command
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    if not await check_force_join(update, context):
        return

    bot_info = await context.bot.get_me()
    text = f"""👋 မင်္ဂလာပါ {get_mention(user.id, user.first_name)} !

🌺 Kachi Card 𝙂𝘼𝙈𝙀 𝘽𝙊𝙏 မှ ကြိုဆိုပါတယ်!

📌 <b>အသုံးပြုပုံ ညွှန်ကြားချက်များ -</b>
- Bot ကို Group ထဲသို့ ထည့်ပါ။
- Group ထဲတွင် စာပေးပို့ပါ (သတ်မှတ်ထားသော စာအရေအတွက်ပြည့်ပါက ကတ်များ အလိုအလျောက် ကျလာပါမည်)။
- ဦးဆောင်သူစာရင်းများကို ကြည့်ရန် /ktop နှင့် /popular ကို အသုံးပြုပါ။"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Help 📖", callback_data="menu_help"),
            InlineKeyboardButton("Team 🛡️", callback_data="menu_team"),
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
                await conn.execute("INSERT INTO users (user_id, name, is_card_admin) VALUES ($1, 'User', TRUE)", target_id)
            else:
                await conn.execute("UPDATE users SET is_card_admin = TRUE WHERE user_id = $1", target_id)

        await update.message.reply_text(f"✅ User ID <code>{target_id}</code> is now a Card Admin.", parse_mode="HTML", reply_to_message_id=msg_id)
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

# /addteam Command
@restricted_command
async def addteam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    user = update.effective_user

    async with db_pool.acquire() as conn:
        u_info = await conn.fetchrow("SELECT is_card_admin FROM users WHERE user_id = $1", user.id)
        is_card_admin = u_info['is_card_admin'] if u_info else False

    if user.id != ADMIN_ID and not is_card_admin:
        return

    full_text = update.message.text.partition(" ")[2].strip()
    if not full_text:
        return await update.message.reply_text(
            "❌ Usage: `/addteam name.emoji` or `/addteam name.stadium.emoji`",
            parse_mode="Markdown",
            reply_to_message_id=msg_id
        )

    parts = [p.strip() for p in full_text.split(".")]
    if len(parts) == 2:
        team_name = parts[0]
        stadium_name = f"{team_name} Stadium"
        emoji = parts[1]
    elif len(parts) >= 3:
        team_name = parts[0]
        stadium_name = parts[1]
        emoji = parts[2]
    else:
        return await update.message.reply_text("❌ Invalid format.", parse_mode="Markdown", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO custom_teams (name, stadium, emoji) VALUES ($1, $2, $3)
                ON CONFLICT (name) DO UPDATE SET stadium = EXCLUDED.stadium, emoji = EXCLUDED.emoji
            """, team_name, stadium_name, emoji)
        except Exception as e:
            return await update.message.reply_text(f"❌ Error adding team: {e}", reply_to_message_id=msg_id)

    global TEAMS
    existing = next((t for t in TEAMS if t['name'].lower() == team_name.lower()), None)
    if existing:
        existing['stadium'] = stadium_name
        existing['emoji'] = emoji
    else:
        TEAMS.append({"name": team_name, "stadium": stadium_name, "emoji": emoji})

    await update.message.reply_text(
        f"✅ Team added successfully!\n\n⚽ Name: <b>{team_name}</b>\n🏟 Stadium: {stadium_name}\n🎨 Emoji: {emoji}",
        parse_mode="HTML",
        reply_to_message_id=msg_id
    )

# /delteam Command
@restricted_command
async def delteam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    user = update.effective_user

    async with db_pool.acquire() as conn:
        u_info = await conn.fetchrow("SELECT is_card_admin FROM users WHERE user_id = $1", user.id)
        is_card_admin = u_info['is_card_admin'] if u_info else False

    if user.id != ADMIN_ID and not is_card_admin:
        return

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/delteam [team_name]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    arg = " ".join(context.args).strip()
    deleted_name = None

    global TEAMS
    async with db_pool.acquire() as conn:
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(TEAMS):
                team_to_remove = TEAMS[idx]
                deleted_name = team_to_remove['name']
                TEAMS.pop(idx)
                await conn.execute("DELETE FROM custom_teams WHERE LOWER(name) = LOWER($1)", deleted_name)
            else:
                return await update.message.reply_text("❌ Invalid team number.", reply_to_message_id=msg_id)
        else:
            found = next((t for t in TEAMS if t['name'].lower() == arg.lower()), None)
            if found:
                deleted_name = found['name']
                TEAMS = [t for t in TEAMS if t['name'].lower() != arg.lower()]
                await conn.execute("DELETE FROM custom_teams WHERE LOWER(name) = LOWER($1)", arg)
            else:
                return await update.message.reply_text(f"❌ Team '<b>{arg}</b>' not found.", parse_mode="HTML", reply_to_message_id=msg_id)

    await update.message.reply_text(f"✅ Team <b>{deleted_name}</b> deleted successfully!", parse_mode="HTML", reply_to_message_id=msg_id)

# /admin Command
@restricted_command
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    text = """⚡ <b>Admin Commands</b>

👑 <b>List:</b>
1. /game - Generate 5 game previews in Bot DM (Use /play [id] to broadcast)
2. /aa - Create trivia quiz
3. /send - Broadcast quiz to groups (reply to /aa)
4. /c [gpid] [count] - Set threshold for a specific group
5. /crest - Reset all thresholds & message counts
6. /cbox [amount] - Send Coin Box
7. /k [user_id] [amount] - Add/remove coins
8. /addadmin [user_id] - Add Card Admin
9. /addteam [name.emoji] - Add custom team
10. /delteam [name] - Delete team
11. /add - Add new card (reply to media)
12. /del [card_id] - Delete card
13. /cardlist - View all cards
14. /glist - View groups list
15. /g or /r - Set Game/Result media
16. /stats - View stats
17. /broadcast - Broadcast message
18. /check [user_id] - Check user profile info
19. /mute [id] [time] [reason] - Mute user from bot usage
20. /ban [id] [reason] - Ban user from bot usage
21. /umute [id] - Unmute user from bot usage
22. /unban [id] - Unban user from bot usage"""

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
        return await msg.reply_text("❌ Usage: `/mute [user_id] [time] [reason]`\nဥပမာ: `/mute 817378 2m spamလုပ်လို့`", parse_mode="Markdown", reply_to_message_id=msg.message_id)

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
            await conn.execute("INSERT INTO users (user_id, name, muted_until, mute_reason) VALUES ($1, 'User', $2, $3)", target_id, until_timestamp, reason)
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
            await conn.execute("INSERT INTO users (user_id, name, banned, ban_reason) VALUES ($1, 'User', TRUE, $2)", target_id, reason)
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

# /check [user_id] Command (Admin Only)
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
        user_row = await conn.fetchrow("SELECT coins, selected_card_id, name, vote_tickets FROM users WHERE user_id = $1", target_id)
        if not user_row:
            return await msg.reply_text(f"❌ User ID <code>{target_id}</code> not found in database.", parse_mode="HTML", reply_to_message_id=msg.message_id)

        coins = user_row['coins'] or 0
        tickets = user_row['vote_tickets'] or 0
        selected_card_id = user_row['selected_card_id']
        db_name = user_row['name'] or "User"

        rank_row = await conn.fetchrow("SELECT COUNT(*) + 1 AS rank FROM users WHERE coins > $1", coins)
        rank = rank_row['rank']

        gem_row = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", target_id)
        gem_count = gem_row['amount'] if gem_row else 0

        user_card_rows = await conn.fetch("""
            SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, uc.amount 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1 AND uc.amount > 0 AND c.card_id != 'gemstone'
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
🏷 Username - {username_str}
⬤ ID - <code>{target_id}</code>
🩸 Kachi Coin - <b>{coins}</b>
💎 GemStone - <b>{gem_count}</b>
🎟 Vote Tickets - <b>{tickets}</b>

❀ Global Rank - #{rank}"""

    cards_info_list = []
    for c in user_card_rows[:5]:
        count_str = f" <b>({c['amount']}x)</b>" if c['amount'] > 1 else ""
        rarity_emoji = "🪞" if c.get('rarity') == 'Kiwami' else ("✨" if c.get('rarity') == 'Kami' else ("⚜️" if c.get('rarity') == 'Hoshi' else "💮"))
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

# /crest Command
@restricted_command
async def crest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    global group_threshold, global_default_threshold
    group_threshold.clear()
    global_default_threshold = 60  # Reset to 60

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE groups SET threshold = 60, msg_count = 0")
        await conn.execute("DELETE FROM settings WHERE key = 'default_threshold'")

    await update.message.reply_text("✅ All group thresholds and message counts have been reset to default (60). Card drops will only trigger when new message thresholds are met.", parse_mode="HTML", reply_to_message_id=msg_id)

# /ktop Command
@restricted_command
async def ktop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    msg_id = update.message.message_id
    async with db_pool.acquire() as conn:
        top_users = await conn.fetch("""
            SELECT u.user_id, u.name, COALESCE(SUM(uc.amount), 0) AS total_cards
            FROM users u
            LEFT JOIN user_cards uc ON u.user_id = uc.user_id AND uc.card_id != 'gemstone'
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

# /kgtop Command
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
            LEFT JOIN user_cards uc ON u.user_id = uc.user_id AND uc.card_id != 'gemstone'
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

# /popular Command
@restricted_command
async def popular_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    async with db_pool.acquire() as conn:
        popular_users = await conn.fetch("SELECT user_id FROM users WHERE is_popular = TRUE")

    if not popular_users:
        return await update.message.reply_text("❌ No popular members found yet. Use /vote to register.", reply_to_message_id=msg_id)

    target_uid = popular_users[0]['user_id']
    text, keyboard = await get_popular_profile_data(target_uid, 0, len(popular_users))
    card = await get_user_card_media(target_uid)

    if card:
        try:
            if card['type'] == 'photo':
                return await update.message.reply_photo(photo=card['file_id'], caption=text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
            else:
                return await update.message.reply_video(video=card['file_id'], caption=text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        except Exception:
            pass

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

# Admin DM /game and /play Commands (Updated to generate 5 match pairs with IDs and /play [id])
@restricted_command
async def game_cmd_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if user.id != ADMIN_ID or update.effective_chat.type != "private":
        return await msg.reply_text("❌ This command can only be used by the Bot Admin in DM.", reply_to_message_id=msg.message_id)

    # Sample 10 unique teams (5 pairs) from TEAMS
    if len(TEAMS) < 10:
        sampled = random.choices(TEAMS, k=10)
    else:
        sampled = random.sample(TEAMS, 10)

    preview_lines = ["⚽ <b>Game Previews (5 Matches):</b>\n"]
    
    for i in range(5):
        home_team = sampled[i * 2]
        away_team = sampled[i * 2 + 1]
        game_id = str(uuid.uuid4())[:6]
        
        dm_game_previews[game_id] = {
            "home": home_team,
            "away": away_team
        }
        
        preview_lines.append(
            f"<b>{i+1}.</b> {home_team['emoji']} <b>{home_team['name']}</b> vs {away_team['emoji']} <b>{away_team['name']}</b>\n"
            f"   🏟️ Stadium: {home_team['stadium']}\n"
            f"   🆔 ID: <code>{game_id}</code>\n"
        )

    preview_lines.append("\n<i>Reply to or use command with ID: <code>/play [id]</code> (e.g. /play ab12cd) to broadcast that match to all groups.</i>")
    
    await msg.reply_text("\n".join(preview_lines), parse_mode="HTML", reply_to_message_id=msg.message_id)

@restricted_command
async def play_cmd_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    if user.id != ADMIN_ID or update.effective_chat.type != "private":
        return

    if not context.args:
        return await msg.reply_text("❌ Usage: `/play [game_id]` (e.g. `/play ab12cd`)", parse_mode="Markdown", reply_to_message_id=msg.message_id)

    game_id = context.args[0].strip()
    if game_id not in dm_game_previews:
        return await msg.reply_text(f"❌ Game ID <code>{game_id}</code> not found or expired.", parse_mode="HTML", reply_to_message_id=msg.message_id)

    game_info = dm_game_previews.pop(game_id)
    unique_game_id = str(uuid.uuid4())[:8]

    game_state = {
        "game_id": unique_game_id,
        "home": game_info["home"],
        "away": game_info["away"],
        "bets": {},
        "user_names": {},
        "time_left": 60,
        "group_messages": {}, # chat_id -> message_id
        "ended": False
    }
    active_games[unique_game_id] = game_state

    async with db_pool.acquire() as conn:
        groups = await conn.fetch("SELECT chat_id FROM groups")

    success_count = 0
    for g in groups:
        chat_id = g['chat_id']
        try:
            caption = build_game_ui(game_state)
            markup = build_game_buttons(game_state, unique_game_id)
            if game_media:
                if game_media["type"] == "photo":
                    sent_msg = await context.bot.send_photo(chat_id, game_media["file_id"], caption=caption, parse_mode="HTML", reply_markup=markup)
                else:
                    sent_msg = await context.bot.send_video(chat_id, game_media["file_id"], caption=caption, parse_mode="HTML", reply_markup=markup)
            else:
                sent_msg = await context.bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=markup)
            game_state["group_messages"][chat_id] = sent_msg.message_id
            success_count += 1
        except Exception:
            pass

    await msg.reply_text(f"✅ Game (ID: <code>{game_id}</code>) broadcasted to {success_count} groups successfully!", parse_mode="HTML", reply_to_message_id=msg.message_id)
    asyncio.create_task(run_group_game_loop(context, unique_game_id))

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
        member_lines.append(f"⇋ {get_mention(m['user_id'], m['name'])} — 🩸 {m['coins']} (Games: {m['total_games']} | Winrate: {wr}%)")

    members_str = "\n".join(member_lines)

    text = f"""TEAM - <b>{t_info['team_name']}</b>
Code: <code>{t_info['team_code']}</code>
🌐 Global Rank ▷ {global_rank}

 ▱ <i>Leader</i> : {get_mention(t_info['leader_id'], leader_name)}

<i>Members</i> ⊞ ({len(members)}/{t_info['member_limit']})

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

# /team Command
@restricted_command
async def team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    async with db_pool.acquire() as conn:
        user_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)

    if user_team:
        await update.message.reply_text("❌ You are already in a team. Use `/myteam` to view info.", parse_mode="Markdown", reply_to_message_id=msg_id)
    else:
        text = "Create a new team and aim for Top 1 to win GemStone 💎. (Cost: 800 Coins)"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Create Team", callback_data=f"create_team_{user.id}")
        ]])
        await update.message.reply_text(text, reply_markup=keyboard, reply_to_message_id=msg_id)

# /myteam Command
@restricted_command
async def myteam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    async with db_pool.acquire() as conn:
        user_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)

    if user_team:
        await show_user_team(update, chat.id, user_team['team_code'], reply_to_msg_id=msg_id)
    else:
        await update.message.reply_text("❌ You are not in any team. Use /team to start.", reply_to_message_id=msg_id)

# /dele
@restricted_command
async def delete_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    async with db_pool.acquire() as conn:
        team = await conn.fetchrow("SELECT team_code, team_name FROM user_teams WHERE leader_id = $1", user.id)
        if not team:
            return await update.message.reply_text("❌ You are not the leader of any team.", reply_to_message_id=msg_id)

        team_code = team['team_code']
        team_name = team['team_name']

        await conn.execute("DELETE FROM team_members WHERE team_code = $1", team_code)
        await conn.execute("DELETE FROM user_teams WHERE team_code = $1", team_code)

    await update.message.reply_text(f"✅ Team <b>{team_name}</b> deleted successfully.", parse_mode="HTML", reply_to_message_id=msg_id)

# /join [CODE] Command
@restricted_command
async def join_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/join [TEAM_CODE]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_code = context.args[0].strip().upper()

    async with db_pool.acquire() as conn:
        already_in = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)
        if already_in:
            return await update.message.reply_text("❌ You are already in a team. Leave first (/out).", reply_to_message_id=msg_id)

        team = await conn.fetchrow("SELECT * FROM user_teams WHERE team_code = $1", target_code)
        if not team:
            return await update.message.reply_text("❌ Invalid team code.", reply_to_message_id=msg_id)

        current_count = await conn.fetchval("SELECT COUNT(*) FROM team_members WHERE team_code = $1", target_code)
        if current_count >= team['member_limit']:
            return await update.message.reply_text("❌ Team is full.", reply_to_message_id=msg_id)

    leader_id = team['leader_id']
    req_text = f"""📩 <b>Team Join Request!</b>

{get_mention(user.id, user.first_name)} requested to join your team <b>{team['team_name']}</b> (Code: <code>{target_code}</code>).

Accept request?"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Decline ❌", callback_data=f"joinapp_no_{user.id}_{target_code}"),
        InlineKeyboardButton("Accept ✅", callback_data=f"joinapp_yes_{user.id}_{target_code}")
    ]])

    try:
        sent = await context.bot.send_message(leader_id, req_text, parse_mode="HTML", reply_markup=keyboard)
        pending_joins[sent.message_id] = {
            "applicant_id": user.id,
            "applicant_name": user.first_name,
            "team_code": target_code
        }
        await update.message.reply_text("✅ Join request sent to team leader.", reply_to_message_id=msg_id)
    except Exception:
        await update.message.reply_text("❌ Could not send message to team leader. Leader must start the bot first.", reply_to_message_id=msg_id)

# /out Command
@restricted_command
async def out_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    async with db_pool.acquire() as conn:
        in_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)
        if not in_team:
            return await update.message.reply_text("❌ You are not in any team.", reply_to_message_id=msg_id)

        team_code = in_team['team_code']
        team = await conn.fetchrow("SELECT leader_id, team_name FROM user_teams WHERE team_code = $1", team_code)

        if context.args and user.id == team['leader_id']:
            try:
                target_kick_id = int(context.args[0])
                if target_kick_id == user.id:
                    return await update.message.reply_text("❌ Leader cannot kick themselves. Use `/dele` to delete team.", parse_mode="Markdown", reply_to_message_id=msg_id)

                is_member = await conn.fetchrow("SELECT user_id FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, target_kick_id)
                if not is_member:
                    return await update.message.reply_text("❌ User is not in your team.", reply_to_message_id=msg_id)

                await conn.execute("DELETE FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, target_kick_id)
                return await update.message.reply_text(f"✅ User ID <code>{target_kick_id}</code> kicked from team.", parse_mode="HTML", reply_to_message_id=msg_id)
            except ValueError:
                return await update.message.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

        if user.id == team['leader_id']:
            return await update.message.reply_text("❌ Team leader cannot leave. Use `/dele` to delete team.", reply_to_message_id=msg_id)

        await conn.execute("DELETE FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, user.id)

    await update.message.reply_text(f"✅ You left <b>{team['team_name']}</b> team.", parse_mode="HTML", reply_to_message_id=msg_id)

# /c [gpid] [count] Command
@restricted_command
async def set_count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 2:
        return await update.message.reply_text(
            "❌ Usage: `/c [gpid] [count]`",
            parse_mode="Markdown",
            reply_to_message_id=msg_id
        )

    try:
        target_chat_id = int(context.args[0])
        count = int(context.args[1])

        group_threshold[target_chat_id] = count

        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO groups (chat_id, threshold) VALUES ($1, $2)
                ON CONFLICT(chat_id) DO UPDATE SET threshold = EXCLUDED.threshold
            """, target_chat_id, count)

        await update.message.reply_text(
            f"✅ Group ID <code>{target_chat_id}</code> threshold set to **{count}**.",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid number format. Usage: `/c [gpid] [count]`",
            parse_mode="Markdown",
            reply_to_message_id=msg_id
        )

# Admin Coin Command
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
                await conn.execute("INSERT INTO users (user_id, name, coins) VALUES ($1, $2, 0)", target_id, "User")
            
            await conn.execute("UPDATE users SET coins = GREATEST(0, coins + $1) WHERE user_id = $2", amount, target_id)
            new_row = await conn.fetchrow("SELECT coins, name FROM users WHERE user_id = $1", target_id)

        action_text = "added" if amount >= 0 else "deducted"
        await update.message.reply_text(
            f"✅ {abs(amount)} Kachi Coins {action_text} to {get_mention(target_id, new_row['name'])}.\n"
            f"💰 Current Coins: <b>{new_row['coins']}</b>",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/k [user_id] [amount]`", parse_mode="Markdown", reply_to_message_id=msg_id)

# /add Command
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

# /del Command
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

# /ksell [amount] Command
@restricted_command
async def ksell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/ksell [amount]` (e.g. `/ksell 1`)", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        sell_amount = int(context.args[0])
        if sell_amount <= 0:
            return await update.message.reply_text("❌ Amount must be greater than 0.", reply_to_message_id=msg_id)
    except ValueError:
        return await update.message.reply_text("❌ Please enter a valid number.", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        gem_row = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
        curr_gems = gem_row['amount'] if gem_row else 0

        if curr_gems < sell_amount:
            return await update.message.reply_text(f"❌ Insufficient GemStones 💎. (Current: {curr_gems})", reply_to_message_id=msg_id)

        coins_earned = sell_amount * 200

        if curr_gems == sell_amount:
            await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
        else:
            await conn.execute("UPDATE user_cards SET amount = amount - $1 WHERE user_id = $2 AND card_id = 'gemstone'", sell_amount, user.id)

        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", coins_earned, user.id)
        rem_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)

    await update.message.reply_text(
        f"✅ Sold <b>{sell_amount}</b> GemStone(s) 💎 successfully!\n\n"
        f"💰 Earned: <b>+{coins_earned}</b> 🩸 Kachi Coins\n"
        f"💳 Total Coins: <b>{rem_coins}</b> 🩸",
        parse_mode="HTML",
        reply_to_message_id=msg_id
    )

async def get_popular_profile_data(target_uid: int, current_idx: int = 0, total_pop: int = 1):
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
    team_str = u_info['team_name'] or "None"
    card_id_str = u_info['selected_card_id'] or "Not set"
    earned_coins = (u_info['popular_votes'] or 0) * 20

    text = f"""📯 <b>POPULAR MEMBER</b>        
             <b>PROFILE</b> ◁ (<b>{current_idx + 1}</b>/<b>{total_pop}</b>)

🧸 <b>POPULAR VOTE</b> - <b>{u_info['popular_votes']}</b>
🎐  <b>VOTE TOTAL EARNED COINS</b> - <b>{earned_coins}</b>

🍀 <b>Name</b> - {get_mention(u_info['user_id'], u_info['name'])}
🍀   <b>USER ID</b> - <code>{u_info['user_id']}</code>
🩸 <b>Kachi Coin</b> - <b>{u_info['coins']}</b>
  💎  <b>GemStone</b> - <b>{gems}</b>
🍀 <b>Selected Card ID</b> - <code>{card_id_str}</code>
   🎖 <b>Global Rank</b> - #{u_info['global_rank']}
〇 <b>Team</b> - <b>{team_str}</b>"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ Back", callback_data=f"pop_view_{current_idx - 1}"),
            InlineKeyboardButton("🗳️ Vote (5 Tickets)", callback_data=f"pop_vote_{target_uid}_{current_idx}"),
            InlineKeyboardButton("Next ▶️", callback_data=f"pop_view_{current_idx + 1}")
        ],
        [InlineKeyboardButton("💎 Gem Gift (1 Gem)", callback_data=f"pop_gemgift_{target_uid}_{current_idx}")]
    ])
    return text, keyboard

# /vote Command
@restricted_command
async def vote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT is_popular FROM users WHERE user_id = $1", user.id)
        popular_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_popular = TRUE") or 1

    if user_row and user_row['is_popular']:
        text, keyboard = await get_popular_profile_data(user.id, 0, popular_count)
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

    text = f"""👋 Hello {get_mention(user.id, user.first_name)} !

🌟 <b>Want to join Popular Members?</b>

Register for the popular list and collect votes from others.

<i>(Registration fee: <b>2000 Kachi Coins</b> 🩸)</i>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔥 Register Popular", callback_data=f"reg_popular_{user.id}")
    ]])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

# /set Command
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

# /kbox Command
@restricted_command
async def kbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat, context)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
        coins = row['coins'] if row else 0

    if coins < 650:
        insufficient_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("View Cards 🎴", url="https://t.me/beyondpoe")
        ]])
        return await update.message.reply_text(
            f"❌ Hello {get_mention(user.id, user.first_name)}, opening a Card Box requires 650 Kachi Coins. You currently have {coins} Coins.",
            parse_mode="HTML",
            reply_markup=insufficient_keyboard,
            reply_to_message_id=msg_id
        )

    text = f"{get_mention(user.id, user.first_name)} is opening Card Box, good luck..."
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎰 Spin Now", callback_data=f"spin_{user.id}"),
        InlineKeyboardButton("View Cards 🎴", url="https://t.me/beyondpoe")
    ]])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=msg_id
    )

# /kgift Command
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
        return await update.message.reply_text("❌ Usage:\n• Send card: Reply with `/kgift [card_id]`\n• Send coins: Reply with `/kgift c[amount]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    arg = context.args[0].strip()

    if arg.lower().startswith("c") and arg[1:].isdigit():
        amount = int(arg[1:])
        if amount <= 0:
            return await update.message.reply_text("❌ Amount must be greater than 0.", reply_to_message_id=msg_id)

        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", sender.id)
            sender_coins = user_row['coins'] if user_row else 0

        if sender_coins < amount:
            return await update.message.reply_text(f"❌ Insufficient Coins ({amount}). (Current: {sender_coins} 🩸)", reply_to_message_id=msg_id)

        text = f"""🎁 <b>Kachi Coin Gift Transfer</b>

👤 <b>Sender:</b> {get_mention(sender.id, sender.first_name)}
👤 <b>Receiver:</b> {get_mention(receiver.id, receiver.first_name)}
💰 <b>Amount:</b> <b>{amount}</b> 🩸 Kachi Coins

<i>Click button below to confirm.</i>"""

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Cancel ❌", callback_data=f"gift_cancel_{sender.id}"),
            InlineKeyboardButton("Confirm Gift 🎁", callback_data=f"gift_confirm_{sender.id}")
        ]])

        sent_msg = await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)
        pending_gifts[sent_msg.message_id] = {
            "type": "coin",
            "sender_id": sender.id,
            "receiver_id": receiver.id,
            "receiver_name": receiver.first_name,
            "amount": amount
        }

    else:
        card_id = arg
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

𝗛𝗮𝗿𝗲𝗺 𝗣𝗮𝗴𝗲{page_str}"""

    if not user_card_rows:
        full_text = f"{text_header}\n\n<i>No cards yet.</i>"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"Harem❄ ({total_owned_sum})", switch_inline_query_current_chat=f"harem.{target_id}"),
                InlineKeyboardButton("INFO 🐙", callback_data=f"kcinfo_{target_id}")
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
        rarity_emoji = "🪞" if c.get('rarity') == 'Kiwami' else ("✨" if c.get('rarity') == 'Kami' else ("⚜️" if c.get('rarity') == 'Hoshi' else "💮"))
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
        InlineKeyboardButton(f"Harem❄ ({total_owned_sum})", switch_inline_query_current_chat=f"harem.{target_id}"),
        InlineKeyboardButton("INFO 🐙", callback_data=f"kcinfo_{target_id}")
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

# /kc Command Handler
@restricted_command
async def check_kc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    await register_user_group(user, chat, context)
    await render_kc_view(update, context, page=0, owner_id=user.id)

# Inline Query Handler for Harem View
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
            WHERE uc.user_id = $1 AND uc.amount > 0 AND c.card_id != 'gemstone'
            ORDER BY c.card_id ASC
        """, target_id)

    results = []
    for c in user_cards:
        r = c.get('rarity', 'Ten')
        r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))
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

# /cardlist Command
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
        r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))
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

# /card [card_id] Command
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
    r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))

    if r == 'Hoshi':
        coin_value = "500-950"
    elif r == 'Ten':
        coin_value = "450-650"
    elif r == 'Kiwami':
        coin_value = "2000-6800"
    elif r == 'Kami':
        coin_value = "1200-4000"
    else:
        coin_value = "450-650"

    caption_text = f"""🎗 Card Information ♡

▰▰▱▱▰▰▱▱
🍀 Name - {card['name']}
    🍀  ID - <code>{card['card_id']}</code>
🎬 Type - {card['type'].upper()}
🌟 Rarity - {r_emoji} {r}
🩸 Kachi Coin Value ( {coin_value} )
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

# /glist Command
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

# Media Commands (/g, /r)
@restricted_command
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

        return await update.message.reply_text(f"🗑 {'Game' if target == 'g' else 'Result'} media deleted.", reply_to_message_id=msg_id)

    reply = update.message.reply_to_message
    if not reply:
        return await update.message.reply_text("❌ Reply to a photo or video.", reply_to_message_id=msg_id)

    media_obj = None
    if reply.photo:
        media_obj = {"type": "photo", "file_id": reply.photo[-1].file_id}
    elif reply.video:
        media_obj = {"type": "video", "file_id": reply.video.file_id}
    else:
        return await update.message.reply_text("❌ Reply with photo or video only.", reply_to_message_id=msg_id)

    if target == "g":
        game_media = media_obj
    else:
        result_media = media_obj

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
        """, key, json.dumps(media_obj))

    await update.message.reply_text(f"✅ {'Game' if target == 'g' else 'Result'} media updated successfully.", reply_to_message_id=msg_id)

# /stats Command
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

# /broadcast Command
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

# Message Handler (with Anti-Spam & Ignore logic)
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.message
    if not chat or not msg or not user or user.is_bot:
        return

    await register_user_group(user, chat, context)

    if chat.type == "private":
        if user and user.id in team_creation_state:
            state = team_creation_state[user.id]
            step = state.get("step")

            if step == "name":
                t_name = msg.text.strip() if msg.text else ""
                if not t_name or len(t_name) > 30:
                    return await msg.reply_text("❌ Team name must be between 1 and 30 characters.", reply_to_message_id=msg.message_id)

                state["team_name"] = t_name
                state["step"] = "limit"

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("1/7", callback_data=f"tlimit_7_{user.id}"), InlineKeyboardButton("1/9", callback_data=f"tlimit_9_{user.id}")],
                    [InlineKeyboardButton("1/13", callback_data=f"tlimit_13_{user.id}"), InlineKeyboardButton("1/15", callback_data=f"tlimit_15_{user.id}")]
                ])
                await msg.reply_text("✅ Team name set!\n\nSelect maximum member limit:", reply_markup=keyboard, reply_to_message_id=msg.message_id)
                return

            elif step == "logo":
                if not msg.photo and not msg.video:
                    return await msg.reply_text("⚠️ Please send a photo or video for the team logo.", reply_to_message_id=msg.message_id)

                if msg.photo:
                    logo_file_id = msg.photo[-1].file_id
                    logo_type = "photo"
                else:
                    logo_file_id = msg.video.file_id
                    logo_type = "video"

                t_name = state["team_name"]
                t_limit = state["limit"]
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

                async with db_pool.acquire() as conn:
                    coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)
                    if not coins or coins < 800:
                        del team_creation_state[user.id]
                        return await msg.reply_text("❌ Insufficient coins (800 required). Creation cancelled.", reply_to_message_id=msg.message_id)

                    await conn.execute("UPDATE users SET coins = coins - 800 WHERE user_id = $1", user.id)

                    await conn.execute("""
                        INSERT INTO user_teams (team_code, team_name, leader_id, member_limit, logo_file_id, logo_type)
                        VALUES ($1, $2, $3, $4, $5, $6)
                    """, code, t_name, user.id, t_limit, logo_file_id, logo_type)

                    await conn.execute("""
                        INSERT INTO team_members (team_code, user_id) VALUES ($1, $2)
                    """, code, user.id)

                del team_creation_state[user.id]

                await msg.reply_text("✅ Team created successfully! (-800 Coins)", reply_to_message_id=msg.message_id)
                await show_user_team(update, chat.id, code, reply_to_msg_id=msg.message_id)
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
                
                # Group အားလုံးအတွက် စာကြောင်းရေ ၆၀ ကို အသေအမြဲ သတ်မှတ်ထားသည်
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

# UI & Buttons with Comma-separated participant lists (No Pagination)
def build_game_ui(game):
    home_list = [game["user_names"][uid] for uid, choice in game["bets"].items() if choice == "home"]
    away_list = [game["user_names"][uid] for uid, choice in game["bets"].items() if choice == "away"]
    draw_list = [game["user_names"][uid] for uid, choice in game["bets"].items() if choice == "draw"]

    home_str = ", ".join(home_list) if home_list else "—"
    away_str = ", ".join(away_list) if away_list else "—"
    draw_str = ", ".join(draw_list) if draw_list else "—"

    return f"""⚽  <b>Choose For Win</b> 🍀

🏖️ <b>{game['home']['emoji']} {game['home']['name']}</b> vs <b>{game['away']['emoji']} {game['away']['name']}</b> ⛵

⛲ <i>Stadium</i> - {game['home']['stadium']}
⏲ <i>Time Left</i> - {game['time_left']} sec

🧩 <b>Live Betting List</b> 

♠ <b>{game['home']['name']}:</b>
{home_str}

♥ <b>{game['away']['name']}:</b>
{away_str}

♦️ <b>Draw:</b>
{draw_str}

GoodLuck G_Y ☘️"""

def build_game_buttons(game, game_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{game['home']['emoji']} {game['home']['name']}", callback_data=f"bet_{game_id}_home"),
            InlineKeyboardButton(f"{game['away']['emoji']} {game['away']['name']}", callback_data=f"bet_{game_id}_away"),
        ],
        [InlineKeyboardButton("🤝 Draw", callback_data=f"bet_{game_id}_draw")],
    ])

def get_leaderboard_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏆 Group Top", callback_data="lb_gp"),
            InlineKeyboardButton("🌍 Global Top", callback_data="lb_global"),
        ],
        [
            InlineKeyboardButton("💎 Top Cards", callback_data="lb_cards"),
            InlineKeyboardButton("🌐 GLOBAL TEAMS", callback_data="lb_teams_page_0")
        ],
        [
            InlineKeyboardButton("🔥 Popular", callback_data="pop_view_0")
        ]
    ])

async def render_popular_view(query, context: ContextTypes.DEFAULT_TYPE, current_idx: int = 0):
    async with db_pool.acquire() as conn:
        popular_users = await conn.fetch("SELECT user_id FROM users WHERE is_popular = TRUE")

    if not popular_users:
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="lb_back")]])
        try:
            if query.message.caption:
                await query.edit_message_caption(caption="📯 <b>POPULAR MEMBERS</b>\n\n<i>No popular members yet. Use /vote to register.</i>", parse_mode="HTML", reply_markup=back_markup)
            else:
                await query.edit_message_text(text="📯 <b>POPULAR MEMBERS</b>\n\n<i>No popular members yet. Use /vote to register.</i>", parse_mode="HTML", reply_markup=back_markup)
        except Exception:
            pass
        return

    pop_uids = [r['user_id'] for r in popular_users]
    total_pop = len(pop_uids)
    current_idx = current_idx % total_pop
    target_uid = pop_uids[current_idx]

    text, keyboard = await get_popular_profile_data(target_uid, current_idx, total_pop)
    card = await get_user_card_media(target_uid)

    try:
        if card:
            if card['type'] == 'photo':
                media = InputMediaPhoto(media=card['file_id'], caption=text, parse_mode="HTML")
            else:
                media = InputMediaVideo(media=card['file_id'], caption=text, parse_mode="HTML")
            await query.edit_message_media(media=media, reply_markup=keyboard)
        else:
            if query.message.caption:
                try:
                    await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
                except Exception:
                    await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass

async def render_top_teams_view(query, page: int = 0):
    async with db_pool.acquire() as conn:
        teams = await conn.fetch("""
            SELECT ut.team_code, ut.team_name, ut.leader_id, ut.member_limit, ut.logo_file_id, ut.logo_type,
                   u.name AS leader_name,
                   COALESCE(SUM(u_all.coins), 0) AS total_coins,
                   COALESCE(SUM(u_all.wins), 0) AS total_wins,
                   COALESCE(SUM(u_all.total_games), 0) AS total_games,
                   CASE WHEN SUM(u_all.total_games) > 0 
                        THEN ROUND((SUM(u_all.wins)::NUMERIC / SUM(u_all.total_games)::NUMERIC) * 100, 1)
                        ELSE 0.0 END AS winrate
            FROM user_teams ut
            JOIN users u ON ut.leader_id = u.user_id
            JOIN team_members tm ON ut.team_code = tm.team_code
            JOIN users u_all ON tm.user_id = u_all.user_id
            GROUP BY ut.team_code, ut.team_name, ut.leader_id, ut.member_limit, ut.logo_file_id, ut.logo_type, u.name
            ORDER BY winrate DESC, total_coins DESC
            LIMIT 5
        """)

    if not teams:
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="lb_back")]])
        try:
            if query.message.caption:
                await query.edit_message_caption(caption="🌐 <b>GLOBAL TOP TEAMS (TOP 5)</b>\n\n<i>No teams found.</i>", parse_mode="HTML", reply_markup=back_markup)
            else:
                await query.edit_message_text(text="🌐 <b>GLOBAL TOP TEAMS (TOP 5)</b>\n\n<i>No teams found.</i>", parse_mode="HTML", reply_markup=back_markup)
        except Exception:
            pass
        return

    total_teams = len(teams)
    page = max(0, min(page, total_teams - 1))
    t = teams[page]

    async with db_pool.acquire() as conn:
        members = await conn.fetch("""
            SELECT u.user_id, u.name, u.coins, u.wins, u.total_games
            FROM team_members tm
            JOIN users u ON tm.user_id = u.user_id
            WHERE tm.team_code = $1
            ORDER BY u.user_id ASC
        """, t['team_code'])

    wr = t['winrate']
    member_lines = []
    for m in members:
        m_wr = round((m['wins'] / m['total_games']) * 100, 1) if m['total_games'] > 0 else 0.0
        member_lines.append(f"⇋ {get_mention(m['user_id'], m['name'])} — 🩸 {m['coins']} (Games: {m['total_games']} | Winrate: {m_wr}%)")

    members_str = "\n".join(member_lines)

    text = f"""🌐 <b>GLOBAL TOP TEAM (Rank #{page + 1}/{total_teams})</b>

TEAM - <b>{t['team_name']}</b>
Code: <code>{t['team_code']}</code>

 ▱ <i>Leader</i> : {get_mention(t['leader_id'], t['leader_name'])}
 🩸 Total Coins: <b>{t['total_coins']}</b> | 🎯 Winrate: <b>{wr}%</b>

<i>Members</i> ⊞ ({len(members)}/{t['member_limit']})

{members_str}"""

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Back", callback_data=f"lb_teams_page_{page - 1}"))
    if page < total_teams - 1:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"lb_teams_page_{page + 1}"))

    buttons = []
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="lb_back")])

    markup = InlineKeyboardMarkup(buttons)

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

async def trigger_card_drop(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    anim_msg = await context.bot.send_message(chat_id, "🐌")
    await asyncio.sleep(4)
    try:
        await context.bot.delete_message(chat_id, anim_msg.message_id)
    except Exception:
        pass

    async with db_pool.acquire() as conn:
        drop_card = await get_weighted_random_card(conn)
    if not drop_card:
        return

    r = drop_card.get('rarity', 'Ten')
    r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))

    joined_names = [f"• {get_mention(uid, name)}" for uid, name in {}.items()]
    joined_str = "\n".join(joined_names) if joined_names else "<i>No one joined yet.</i>"

    drop_text = f"""{r_emoji} A Character Card Spawned In The Chat ❄

[ 𝗝𝗢𝗜𝗡 ] Fast For The Claim
 Card ❀

{joined_str}

GoodLuck 🍀 Time (50sec)"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("𝗝𝗢𝗜𝗡(0/5)", callback_data="join_card_drop")
    ]])

    if drop_card['type'] == 'photo':
        msg = await context.bot.send_photo(chat_id, drop_card['file_id'], caption=drop_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        msg = await context.bot.send_video(chat_id, drop_card['file_id'], caption=drop_text, parse_mode="HTML", reply_markup=keyboard)

    active_card_drops[msg.message_id] = {
        "chat_id": chat_id,
        "card": drop_card,
        "joined_users": {},
        "timer": 50,
        "ended": False
    }

    asyncio.create_task(run_card_drop_timer(context, msg.message_id))

async def run_card_drop_timer(context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    while msg_id in active_card_drops:
        drop = active_card_drops[msg_id]
        if drop["ended"]:
            break

        if drop["timer"] <= 0 or len(drop["joined_users"]) >= 5:
            await finalize_card_drop(context, msg_id)
            break

        await asyncio.sleep(5)
        drop["timer"] -= 5
        if drop["ended"]:
            break

        current_count = len(drop["joined_users"])
        r = drop["card"].get('rarity', 'Ten')
        r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))

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
            await context.bot.edit_message_caption(chat_id=drop["chat_id"], message_id=msg_id, caption=drop_text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass

async def finalize_card_drop(context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    drop = active_card_drops.get(msg_id)
    if not drop or drop["ended"]:
        return
    drop["ended"] = True

    chat_id = drop["chat_id"]
    card = drop["card"]
    joined = drop["joined_users"]

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass

    anim_msg = await context.bot.send_message(chat_id, "🐸")
    await asyncio.sleep(4)
    try:
        await context.bot.delete_message(chat_id, anim_msg.message_id)
    except Exception:
        pass

    if joined:
        winner_id, winner_name = random.choice(list(joined.items()))
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, winner_id, card['card_id'])

        r = card.get('rarity', 'Ten')
        r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))
        win_msg = f"⛩ Congratulations , {get_mention(winner_id, winner_name)} Now you got A new Card {card['name']} ID: {card['card_id']} Rarity: {r_emoji} {r}❄ Check /kc 🎗"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Harem❄", switch_inline_query_current_chat=f"harem.{winner_id}")]
        ])

        try:
            if card['type'] == 'photo':
                await context.bot.send_photo(chat_id, photo=card['file_id'], caption=win_msg, parse_mode="HTML", reply_markup=keyboard)
            else:
                await context.bot.send_video(chat_id, video=card['file_id'], caption=win_msg, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await context.bot.send_message(chat_id, text=win_msg, parse_mode="HTML", reply_markup=keyboard)
    else:
        win_msg = f"❌ Card drop for <b>{card['name']}</b> cancelled as no one joined."
        try:
            await context.bot.send_message(chat_id, text=win_msg, parse_mode="HTML")
        except Exception:
            pass

    if msg_id in active_card_drops:
        del active_card_drops[msg_id]

# Group Game Loop & Broadcast Runner (Optimized with asyncio.gather for smooth performance)
async def run_group_game_loop(context: ContextTypes.DEFAULT_TYPE, game_id: str):
    game_state = active_games.get(game_id)
    if not game_state:
        return

    while game_state["time_left"] > 0:
        await asyncio.sleep(5)
        game_state["time_left"] -= 5
        
        caption = build_game_ui(game_state)
        markup = build_game_buttons(game_state, game_id)

        async def update_group(chat_id, msg_id):
            try:
                if game_media:
                    await context.bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=caption, parse_mode="HTML", reply_markup=markup)
                else:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=caption, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass

        tasks = [update_group(cid, mid) for cid, mid in list(game_state["group_messages"].items())]
        if tasks:
            await asyncio.gather(*tasks)

    game_state["ended"] = True

    for chat_id, msg_id in list(game_state["group_messages"].items()):
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

    anim_msg_tasks = []
    for chat_id in game_state["group_messages"].keys():
        async def send_anim(cid):
            try:
                m = await context.bot.send_message(cid, "⚡")
                await asyncio.sleep(3)
                await context.bot.delete_message(cid, m.message_id)
            except Exception:
                pass
        anim_msg_tasks.append(send_anim(chat_id))
    await asyncio.gather(*anim_msg_tasks)

    home_team = game_state["home"]
    away_team = game_state["away"]
    home_g, away_g = random.randint(0, 3), random.randint(0, 3)
    if home_g > away_g:
        win_choice, win_name = "home", home_team["name"]
    elif away_g > home_g:
        win_choice, win_name = "away", away_team["name"]
    else:
        win_choice, win_name = "draw", "Draw"

    winners, losers = [], []
    all_participants = list(game_state["bets"].keys())

    async with db_pool.acquire() as conn:
        for uid, choice in game_state["bets"].items():
            uname = game_state["user_names"][uid]
            await conn.execute("UPDATE users SET total_games = total_games + 1 WHERE user_id = $1", uid)

            if choice == win_choice:
                reward = 1300 if win_choice == "draw" else 1000
                await add_coins(uid, reward)
                await conn.execute("UPDATE users SET wins = wins + 1, vote_tickets = vote_tickets + 30 WHERE user_id = $1", uid)
                await conn.execute("""
                    INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, 'gemstone', 5)
                    ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 5
                """, uid)
                winners.append(f"{uname} (+{reward} 🩸 | +30 🎟️ | +5 💎)")
            else:
                losers.append(uname)

    win_str = "\n".join(winners) if winners else "—"
    loss_str = "\n".join(losers) if losers else "—"

    res_text = f"""🎗️  Match Result   🧶

🏖️ <b>{home_team['name']}</b> {home_g} - {away_g} <b>{away_team['name']}</b> 🪂

⚡ <b>Winner</b> - {win_name}

✨ <b>Winners</b> -
{win_str}

🐸 <b>Losers</b> -
{loss_str}"""

    leader_markup = get_leaderboard_buttons()

    for chat_id in game_state["group_messages"].keys():
        try:
            if result_media:
                if result_media["type"] == "photo":
                    sent_res = await context.bot.send_photo(chat_id, result_media["file_id"], caption=res_text, parse_mode="HTML", reply_markup=leader_markup)
                else:
                    sent_res = await context.bot.send_video(chat_id, result_media["file_id"], caption=res_text, parse_mode="HTML", reply_markup=leader_markup)
            else:
                sent_res = await context.bot.send_message(chat_id, res_text, parse_mode="HTML", reply_markup=leader_markup)
            last_results[sent_res.message_id] = res_text
        except Exception:
            pass

    if game_id in active_games:
        del active_games[game_id]

async def run_spin_animation(bot, chat_id, user, query_message):
    try:
        frames = ["🔄 [▰▱▱▱▱▱▱▱▱▱] Loading 10%...", "🔄 [▰▰▰▰▱▱▱▱▱▱] Loading 40%...", "🔄 [▰▰▰▰▰▰▰▱▱▱] Loading 70%...", "🔄 [▰▰▰▰▰▰▰▰▰▰] Complete!"]
        for frame in frames:
            try:
                await query_message.edit_text(f"🎁 Hello {get_mention(user.id, user.first_name)}!\n\n{frame}", parse_mode="HTML")
            except Exception:
                pass
            await asyncio.sleep(1)

        async with db_pool.acquire() as conn:
            won_card = await get_weighted_random_card(conn)
            if not won_card:
                return

            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, user.id, won_card['card_id'])

            rem_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)

        try:
            await query_message.delete()
        except Exception:
            pass

        r = won_card.get('rarity', 'Ten')
        r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))

        win_text = f"""🎉 𝘾𝙤𝙣𝙜𝙧𝙖𝙩𝙪𝙡𝙖𝙩𝙞𝙤𝙣𝙨 {user.first_name}

USER ID {user.id}
🩸 {rem_coins} 

{won_card['name']} 
🧶 {r_emoji} {r}
 {won_card['card_id']} 🎩"""

        if won_card['type'] == 'photo':
            await bot.send_photo(chat_id=chat_id, photo=won_card['file_id'], caption=win_text, parse_mode="HTML")
        else:
            await bot.send_video(chat_id=chat_id, video=won_card['file_id'], caption=win_text, parse_mode="HTML")
    except Exception as e:
        print(f"Spin error: {e}")

# Callback Query Handler
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    data = query.data

    await register_user_group(user, query.message.chat, context)

    if data.startswith("kcinfo_"):
        target_id = int(data.split("_")[1])
        if user.id != target_id:
            return await query.answer("❌ This info button is only for the profile owner.", show_alert=True)
            
        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT coins, name, vote_tickets FROM users WHERE user_id = $1", target_id)
            coins = user_row['coins'] if user_row else 0
            tickets = user_row['vote_tickets'] if user_row else 0
            display_name = user_row['name'] if user_row else user.first_name

            rank_row = await conn.fetchrow("SELECT COUNT(*) + 1 AS rank FROM users WHERE coins > $1", coins)
            rank = rank_row['rank']

            gem_row = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", target_id)
            gem_count = gem_row['amount'] if gem_row else 0

        info_text = f"""❀ Name - {get_mention(target_id, display_name)}
⬤ ID - <code>{target_id}</code>
🩸 Kachi Coin - <b>{coins}</b>
💎 GemStone - <b>{gem_count}</b>
🎟 Vote Tickets - <b>{tickets}</b>

❀ Global Rank - #{rank}"""

        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Back ◀️", callback_data=f"kcpage_0_{target_id}")]])
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=info_text, parse_mode="HTML", reply_markup=markup)
            else:
                await query.edit_message_text(text=info_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        await query.answer()
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
💰 <b>ရရှိသော Kachi Coin:</b> +{coins_won} 🩸

CHECK /kc Use Coin /kbox"""

            try:
                await query.edit_message_text(result_text, parse_mode="HTML", reply_markup=None)
            except Exception:
                pass
            await query.answer(f"🎉 မှန်ကန်ပါသည်။ +{coins_won} Coins ရရှိပါသည်!", show_alert=True)
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

    if data.startswith("quiz_preview_"):
        return await query.answer("ℹ️ This is a preview. Use /send to broadcast to groups.", show_alert=True)

    if data == "menu_help":
        help_text = """📖 <b>အကူအညီနှင့် လမ်းညွှန်ချက်များ (Help & Guidelines)</b>

- Bot ကို Group ထဲသို့ထည့်ပြီး စာပေးပို့ပါက သတ်မှတ်ထားသော စာအရေအတွက်ပြည့်သည်နှင့် ကတ်များ အလိုအလျောက်ကျလာမည်ဖြစ်ပါသည်။
- Admin များအနေဖြင့် Bot DM တွင် /game ဖြင့် Game Previews ၅ ခုထုတ်၍ /play [id] ဖြင့် Group အားလုံးသို့ ပို့ဆောင်နိုင်ပါသည်။
- ၁ မိနစ်အတွင်း Home, Away သို့မဟုတ် Draw ကို ရွေးချယ်ပါ။
- အနိုင်ရပါက Kachi Coins နှင့် Vote Tickets များ ရရှိမည်ဖြစ်ပါသည်။
- /kbox ဖြင့် ကတ်ပေါက်ရန် လှည့်ပါ၊ /kc ဖြင့် မိမိ၏ Harem ကို ကြည့်ပါ။
- /ktop - Global Leaderboard ကို ကြည့်ရန်။
- /kgtop - Group Leaderboard ကို ကြည့်ရန်。
- /popular - Popular အဖွဲ့ဝင်များ၏ ပရိုဖိုင်ကို ကြည့်ရန်။
- /ksell [amount] - GemStones များကို Kachi Coins ဖြင့် ရောင်းချရန်။
- /vote - Popular ပရိုဖိုင်တွင် စာရင်းသွင်းရန်နှင့် မဲပေးရန်။
- /card [card_id] - ကတ်အသေးစိတ်နှင့် ပိုင်ရှင်များကို ကြည့်ရန်။
- /set [card_id] - /kc တွင်ပြသရန် ပရိုဖိုင်ကတ်အဖြစ် သတ်မှတ်ရန်။"""
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="menu_back")]])
        await query.edit_message_text(help_text, parse_mode="HTML", reply_markup=markup)
        await query.answer()
        return

    if data == "menu_team":
        team_text = """🛡️ <b>အဖွဲ့ (Team) လမ်းညွှန်ချက်များ</b>

- /team - Team အသစ်ဖန်တီးရန် (ကုန်ကျငွေ: 800 Coins)
- /myteam - မိမိအဖွဲ့၏ အချက်အလက်နှင့် အဖွဲ့ဝင်များကို ကြည့်ရန်
- /join [CODE] - Code ဖြင့် Team ထဲသို့ ဝင်ရောက်ရန်
- /out - Team မှ ထွက်ရန် (Leader ဆိုပါက အဖွဲ့ဝင်များကို kick နိုင်သည်)
- /dele - Team ကို ဖျက်သိမ်းရန် (Leader သာလျှင်)"""
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="menu_back")]])
        await query.edit_message_text(team_text, parse_mode="HTML", reply_markup=markup)
        await query.answer()
        return

    if data == "menu_kgift":
        kgift_text = """🎁 <b>လက်ဆောင်ပေးခြင်း (Gift) လမ်းညွှန်ချက်များ</b>

user တစ်ဦး၏ စာကို reply လုပ်၍ အောက်ပါအတိုင်း ပေးပို့ပါ -
- /kgift c[amount] - Kachi Coins များ ပေးပို့ရန် (ဥပမာ - /kgift c100)
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
- ဦးဆောင်သူစာရင်းများကို ကြည့်ရန် /ktop နှင့် /popular ကို အသုံးပြုပါ။"""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Help 📖", callback_data="menu_help"),
                InlineKeyboardButton("Team 🛡️", callback_data="menu_team"),
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

            added_reward_coins = 50 if rarity in ["Hoshi", "Ten"] else 80

            if is_card_admin and user.id != ADMIN_ID:
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", added_reward_coins, user.id)

        del pending_card_adds[user.id]

        r_emoji = "🪞" if rarity == 'Kiwami' else ("✨" if rarity == 'Kami' else ("⚜️" if rarity == 'Hoshi' else "💮"))
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

        reward_notice = f"\n🎉 Received <b>+{added_reward_coins} Kachi Coins</b> for adding card!" if (is_card_admin and user.id != ADMIN_ID) else ""
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

    if data == "join_card_drop":
        drop = active_card_drops.get(msg_id)
        if not drop or drop["ended"]:
            return await query.answer("❌ This card drop has ended.", show_alert=True)

        if user.id in drop["joined_users"]:
            return await query.answer("❌ You have already joined.", show_alert=True)

        if len(drop["joined_users"]) >= 5:
            return await query.answer("❌ Drop is full (5/5)!", show_alert=True)

        drop["joined_users"][user.id] = user.first_name
        await query.answer("✅ Successfully joined card drop!", show_alert=True)

        if len(drop["joined_users"]) >= 5:
            await finalize_card_drop(context, msg_id)
        else:
            current_count = len(drop["joined_users"])
            r = drop["card"].get('rarity', 'Ten')
            r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))

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

    if data.startswith("reg_popular_"):
        allowed_uid = int(data.split("_")[2])
        if user.id != allowed_uid:
            return await query.answer("❌ Not for you.", show_alert=True)

        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT coins, is_popular FROM users WHERE user_id = $1", user.id)
            if user_row and user_row['is_popular']:
                return await query.answer("❌ You are already on the popular list.", show_alert=True)

            if not user_row or user_row['coins'] < 2000:
                return await query.answer("❌ 2000 Kachi Coins required.", show_alert=True)

            await conn.execute("UPDATE users SET coins = coins - 2000, is_popular = TRUE WHERE user_id = $1", user.id)

        await query.answer("🎉 Successfully joined popular list!", show_alert=True)
        await query.edit_message_text(f"🎉 Congratulations {get_mention(user.id, user.first_name)}!\n\nYou have successfully joined the popular list.", parse_mode="HTML")
        return

    if data.startswith("pop_view_"):
        idx = int(data.split("_")[2])
        await render_popular_view(query, context, current_idx=idx)
        await query.answer()
        return

    if data.startswith("pop_gemgift_"):
        parts = data.split("_")
        target_uid = int(parts[2])
        c_idx = int(parts[3])

        if user.id == target_uid:
            return await query.answer("❌ Cannot gift gem to yourself.", show_alert=True)

        async with db_pool.acquire() as conn:
            sender_gem = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
            gems = sender_gem['amount'] if sender_gem else 0

            if gems < 1:
                return await query.answer("❌ Insufficient GemStones 💎.", show_alert=True)

            if gems == 1:
                await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
            else:
                await conn.execute("UPDATE user_cards SET amount = amount - 1 WHERE user_id = $1 AND card_id = 'gemstone'", user.id)

            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, 'gemstone', 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, target_uid)

        await query.answer("💎 GemStone sent successfully!", show_alert=True)

        async with db_pool.acquire() as conn:
            popular_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_popular = TRUE") or 1
        text, keyboard = await get_popular_profile_data(target_uid, c_idx, popular_count)
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
        return

    if data.startswith("pop_vote_"):
        parts = data.split("_")
        target_uid = int(parts[2])
        c_idx = int(parts[3])

        if user.id == target_uid:
            return await query.answer("❌ Cannot vote for yourself.", show_alert=True)

        async with db_pool.acquire() as conn:
            voter_row = await conn.fetchrow("SELECT vote_tickets FROM users WHERE user_id = $1", user.id)
            tickets = voter_row['vote_tickets'] if voter_row else 0

            if tickets < 5:
                return await query.answer("❌ 5 Vote Tickets required. (Play games to earn tickets)", show_alert=True)

            await conn.execute("UPDATE users SET vote_tickets = vote_tickets - 5 WHERE user_id = $1", user.id)
            await conn.execute("UPDATE users SET popular_votes = popular_votes + 1, coins = coins + 20 WHERE user_id = $1", target_uid)

        await query.answer("🗳️ Voted successfully! (-5 Tickets)", show_alert=True)

        async with db_pool.acquire() as conn:
            popular_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_popular = TRUE") or 1
        text, keyboard = await get_popular_profile_data(target_uid, c_idx, popular_count)
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass
        return

    if data.startswith("create_team_"):
        allowed_user_id = int(data.split("_")[2])
        if user.id != allowed_user_id:
            return await query.answer("❌ Not for you.", show_alert=True)

        async with db_pool.acquire() as conn:
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)
            if not coins or coins < 800:
                return await query.answer("❌ 800 Kachi Coins required to create a team.", show_alert=True)

            already_in = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)
            if already_in:
                return await query.answer("❌ You are already in a team.", show_alert=True)

        team_creation_state[user.id] = {"step": "name"}

        try:
            await context.bot.send_message(
                user.id,
                f"👋 Hello {get_mention(user.id, user.first_name)}!\n\n"
                "🏆 <b>Team Creation Started!</b>\n"
                "Please enter your desired <b>Team Name</b>:",
                parse_mode="HTML"
            )
            await query.answer()
            await query.edit_message_text(f"✅ {get_mention(user.id, user.first_name)}, please check Bot DM to finish team setup.", parse_mode="HTML")
        except Exception:
            if user.id in team_creation_state:
                del team_creation_state[user.id]
            await query.answer("❌ Cannot send DM. Please start the bot first.", show_alert=True)

        return

    if data.startswith("tlimit_"):
        parts = data.split("_")
        limit_val = int(parts[1])
        allowed_id = int(parts[2])

        if user.id != allowed_id:
            return await query.answer("❌ Unauthorized.", show_alert=True)

        if user.id in team_creation_state:
            team_creation_state[user.id]["limit"] = limit_val
            team_creation_state[user.id]["step"] = "logo"

            await query.answer()
            await query.edit_message_text(f"✅ Member limit set to <b>1/{limit_val}</b>!\n\nNow send your <b>Team Logo (photo or video)</b>:", parse_mode="HTML")
        return

    if data.startswith("joinapp_"):
        parts = data.split("_")
        action = parts[1]
        applicant_id = int(parts[2])
        team_code = parts[3]

        async with db_pool.acquire() as conn:
            team = await conn.fetchrow("SELECT leader_id, team_name, member_limit FROM user_teams WHERE team_code = $1", team_code)
            if not team or user.id != team['leader_id']:
                return await query.answer("❌ You are not the leader of this team.", show_alert=True)

            if action == "no":
                if msg_id in pending_joins:
                    del pending_joins[msg_id]
                await query.edit_message_text("❌ <b>Join request declined.</b>", parse_mode="HTML")
                try:
                    await context.bot.send_message(applicant_id, f"❌ Your join request for <b>{team['team_name']}</b> was declined.", parse_mode="HTML")
                except Exception:
                    pass
                return await query.answer()

            elif action == "yes":
                curr_cnt = await conn.fetchval("SELECT COUNT(*) FROM team_members WHERE team_code = $1", team_code)
                if curr_cnt >= team['member_limit']:
                    return await query.answer("❌ Team is full.", show_alert=True)

                app_in_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", applicant_id)
                if app_in_team:
                    return await query.answer("❌ User joined another team already.", show_alert=True)

                await conn.execute("INSERT INTO team_members (team_code, user_id) VALUES ($1, $2)", team_code, applicant_id)
                if msg_id in pending_joins:
                    del pending_joins[msg_id]

                await query.edit_message_text(f"✅ <b>New member accepted!</b>", parse_mode="HTML")
                try:
                    await context.bot.send_message(applicant_id, f"🎉 <b>Congratulations!</b> You successfully joined <b>{team['team_name']}</b>.", parse_mode="HTML")
                except Exception:
                    pass
                return await query.answer()

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
                if gift_info["type"] == "coin":
                    amount = gift_info["amount"]
                    s_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", sender_id)
                    if not s_row or s_row['coins'] < amount:
                        return await query.answer("❌ Insufficient coins.", show_alert=True)

                    await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", amount, sender_id)
                    await conn.execute("""
                        INSERT INTO users (user_id, name, coins) VALUES ($1, $2, $3)
                        ON CONFLICT(user_id) DO UPDATE SET coins = users.coins + EXCLUDED.coins
                    """, receiver_id, receiver_name, amount)

                    success_text = f"✅ {get_mention(sender_id, user.first_name)} sent <b>{amount}</b> Kachi Coins to {get_mention(receiver_id, receiver_name)}!"

                elif gift_info["type"] == "card":
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

    if data == "claim_cbox":
        box = active_cboxes.get(msg_id)
        if not box:
            return await query.answer("❌ Coin box expired or removed.", show_alert=True)

        if user.id in box["claimed_users"]:
            return await query.answer("❌ You have already claimed from this box.", show_alert=True)

        if box["remaining"] <= 0:
            return await query.answer("❌ Coin box is empty!", show_alert=True)

        max_steal = max(1, min(box["remaining"], int(box["total_amount"] * 0.4)))
        stolen_amount = random.randint(1, max_steal) if box["remaining"] > 1 else box["remaining"]

        box["remaining"] -= stolen_amount
        box["claimed_users"][user.id] = {
            "name": user.first_name,
            "got": stolen_amount
        }

        await add_coins(user.id, stolen_amount)
        await query.answer(f"🎉 Claimed 🩸 {stolen_amount} Kachi Coins!", show_alert=True)

        claimed_list = []
        for uid, udata in box["claimed_users"].items():
            claimed_list.append(f"• {get_mention(uid, udata['name'])} — <b>{udata['got']}</b> 🩸")
        
        list_str = "\n".join(claimed_list)

        if box["remaining"] > 0:
            status_str = f"💰 <b>Remaining Amount:</b> <code>{box['remaining']}</code> 🩸"
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏴‍☠ Claim", callback_data="claim_cbox")]])
        else:
            status_str = "🎁 <b>Coin Box is empty!</b>"
            markup = None

        text = f"""🎁 <b>Kachi Coin Box!</b> 🩸

{status_str}
👤 <b>Creator:</b> {box['creator']}

📋 <b>Claimed List:</b>
{list_str}"""

        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        return

    if data.startswith("spin_"):
        owner_id = int(data.split("_")[1])
        if user.id != owner_id:
            return await query.answer("❌ Not for you. Use /kbox yourself.", show_alert=True)

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
            coins = row['coins'] if row else 0

            if coins < 650:
                return await query.answer("❌ Insufficient Kachi Coins (650 required).", show_alert=True)

            cards = await conn.fetch("SELECT card_id FROM cards WHERE card_id != 'gemstone'")
            if not cards:
                return await query.answer("❌ No cards available yet.", show_alert=True)

            await conn.execute("UPDATE users SET coins = coins - 650 WHERE user_id = $1", user.id)

        await query.answer("🎰 Spinning card box...")
        asyncio.create_task(run_spin_animation(context.bot, chat_id, user, query.message))
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

    if data.startswith("bet_"):
        parts = data.split("_")
        game_id = parts[1]
        choice = parts[2]
        game = active_games.get(game_id)
        if not game or game["ended"]:
            return await query.answer("❌ This game has ended.", show_alert=True)

        game["bets"][user.id] = choice
        game["user_names"][user.id] = get_mention(user.id, user.first_name)
        await query.answer("✅ Bet placed!")

        caption = build_game_ui(game)
        markup = build_game_buttons(game, game_id)

        async def update_group(cid, mid):
            try:
                if game_media:
                    await context.bot.edit_message_caption(chat_id=cid, message_id=mid, caption=caption, parse_mode="HTML", reply_markup=markup)
                else:
                    await context.bot.edit_message_text(chat_id=cid, message_id=mid, text=caption, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass

        tasks = [update_group(cid, mid) for cid, mid in list(game["group_messages"].items())]
        if tasks:
            await asyncio.gather(*tasks)
        return

    if data == "lb_back":
        original_text = last_results.get(msg_id, "🎗️ Match Result")
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

    if data.startswith("lb_teams_page_"):
        page_num = int(data.replace("lb_teams_page_", ""))
        await render_top_teams_view(query, page=page_num)
        await query.answer()
        return

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
                title = "🏆 <b>Group Top Users</b>"
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
                    WHERE uc.amount > 0 AND uc.card_id != 'gemstone'
                    GROUP BY u.user_id, u.name
                    ORDER BY card_count DESC
                    LIMIT 10
                """)
                title = "💎 <b>Top Card Owners (Top 10)</b>"

        if not rows:
            text = f"{title}\n\n<i>No data available.</i>"
        else:
            if lb_type == "gp":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — {r['coins']} 🩸 Kachi Coin ({r['total_cards']} Cards)" for i, r in enumerate(rows)])
            elif lb_type == "global":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — {r['coins']} 🩸 Kachi Coin" for i, r in enumerate(rows)])
            elif lb_type == "cards":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — <b>{r['card_count']}</b> Cards" for i, r in enumerate(rows)])

        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="lb_back")]])
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
    asyncio.create_task(team_reset_checker(app))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # Public User Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("kc", check_kc_cmd))
    app.add_handler(CommandHandler("set", set_card_cmd))
    app.add_handler(CommandHandler("kbox", kbox_cmd))
    app.add_handler(CommandHandler("ksell", ksell_cmd))
    app.add_handler(CommandHandler("kgift", kgift_cmd))
    app.add_handler(CommandHandler("card", card_detail_cmd))
    app.add_handler(CommandHandler("team", team_cmd))
    app.add_handler(CommandHandler("myteam", myteam_cmd))
    app.add_handler(CommandHandler("dele", delete_team_cmd))
    app.add_handler(CommandHandler("join", join_team_cmd))
    app.add_handler(CommandHandler("out", out_team_cmd))
    app.add_handler(CommandHandler("vote", vote_cmd))
    app.add_handler(CommandHandler("ktop", ktop_cmd))
    app.add_handler(CommandHandler("kgtop", kgtop_cmd))
    app.add_handler(CommandHandler("popular", popular_cmd))

    # Admin & Card Admin Commands (Game triggered via DM /game and /play [id])
    app.add_handler(CommandHandler("game", game_cmd_dm))
    app.add_handler(CommandHandler("play", play_cmd_dm))
    app.add_handler(CommandHandler("aa", aa_cmd))
    app.add_handler(CommandHandler("send", send_quiz_cmd))
    app.add_handler(CommandHandler("cardlist", cardlist_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("c", set_count_cmd))
    app.add_handler(CommandHandler("crest", crest_cmd))
    app.add_handler(CommandHandler("cbox", cbox_cmd))
    app.add_handler(CommandHandler("glist", glist_cmd))
    app.add_handler(CommandHandler(["g", "r"], media_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("k", admin_coin_cmd))
    app.add_handler(CommandHandler("addadmin", addadmin_cmd))
    app.add_handler(CommandHandler("addteam", addteam_cmd))
    app.add_handler(CommandHandler("delteam", delteam_cmd))
    app.add_handler(CommandHandler("add", add_card_cmd))
    app.add_handler(CommandHandler("del", del_card_cmd))
    app.add_handler(CommandHandler("check", check_user_cmd))

    # Bot-level Moderation Commands (/mute, /ban, /umute, /unban)
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
