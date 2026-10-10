import asyncio
import json
import os
import random
import string
import time
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
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "@beyondpoe")

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
active_cboxes = {}
pending_gifts = {}
team_creation_state = {}
pending_joins = {}
active_card_drops = {}
pending_card_adds = {}
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
                popular_votes BIGINT DEFAULT 0,
                is_card_admin BOOLEAN DEFAULT FALSE
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
        """)

        try:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS selected_card_id TEXT;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS wins BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_games BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vote_tickets BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_popular BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS popular_votes BIGINT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_card_admin BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_id BIGINT;")
            await conn.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS added_by_name TEXT;")
            await conn.execute("ALTER TABLE user_cards ADD COLUMN IF NOT EXISTS amount INT DEFAULT 1;")
            await conn.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS rarity TEXT;")
        except Exception:
            pass

        # Auto assign rarities to existing cards without rarity
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

# Weighted random card selector for Kbox and Card Drop (Kiwami & Kami are rarer)
async def get_weighted_random_card(conn):
    cards = await conn.fetch("SELECT card_id, name, type, file_id, rarity FROM cards WHERE card_id != 'gemstone'")
    if not cards:
        return None
    
    weights = []
    for c in cards:
        r = c.get('rarity', 'Ten')
        if r == 'Kiwami':
            weights.append(1)
        elif r == 'Kami':
            weights.append(3)
        elif r == 'Hoshi':
            weights.append(15)
        elif r == 'Ten':
            weights.append(30)
        else:
            weights.append(15)
            
    return random.choices(cards, weights=weights, k=1)[0]

# Force Join Check Helper
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
        text = f"🐠 Hello {get_mention(user.id, user.first_name)} Please Join For Using The Command \nကဒ်အလှတွေနဲ့ Game Updates လေးတွေသိရအောင် Joinပေးပါနော် 🩸"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Channel 📢", url="https://t.me/beyondpoe")],
            [InlineKeyboardButton("Now Using ✅", callback_data=f"check_join_{user.id}")]
        ])
        if update.message:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=update.message.message_id)
        elif update.callback_query:
            await update.callback_query.answer("❌ Please join the channel first!", show_alert=True)
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
                                    f"🎉 <b>Congratulations!</b> Your Team <b>{team['team_name']}</b> reached Top 5! You earned <b>1 GemStone💎</b>.",
                                    parse_mode="HTML"
                                )
                            except Exception:
                                pass

                    await conn.execute("UPDATE users SET wins = 0, total_games = 0")
                    await conn.execute("UPDATE settings SET value = $1 WHERE key = 'last_team_reset'", str(now))
        except Exception:
            pass

# Coin Box Command
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
        return await update.message.reply_text("❌ Usage: `/cbox [amount]` (e.g., `/cbox 2000`)", parse_mode="Markdown", reply_to_message_id=msg_id)

    try:
        total_amount = int(context.args[0])
        if total_amount <= 0:
            return await update.message.reply_text("❌ Amount must be greater than 0.", reply_to_message_id=msg_id)
    except ValueError:
        return await update.message.reply_text("❌ Please enter a valid number for amount.", reply_to_message_id=msg_id)

    text = f"""🎁 <b>Kachi Coin Box Dropped!</b> 🩸

💰 <b>Live Remaining Amount:</b> <code>{total_amount}</code> 🩸
👤 <b>Created By:</b> {get_mention(user.id, user.first_name)}

📋 <b>Live Claim List:</b>
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
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    bot_info = await context.bot.get_me()
    text = f"""👋 Hello {get_mention(user.id, user.first_name)} !

🌺 Welcome to 𝙂𝘼𝙈𝙀 𝘽𝙊𝙏!

📌 <b>How to play:</b>
- Add the bot to your Group.
- Talk in group to trigger the game when message limit is reached.
- Choose your team or Draw within 1 minute.

Rewards / 𝙋𝙧𝙞𝙘𝙚
- Team Win: 70 🩸Kachi Coin + 10 🎟️ Vote Tickets
- Draw Win: 100 🩸Kachi Coin + 10 🎟️ Vote Tickets

📜 <b>Available Commands:</b>
• /kc - Check your coins and cards
• /kbox - Spin Card Box (650 Coins)
• /ksell [amount] - Sell 1 GemStone 💎 for 200 Coins
• /card [card_id] - Check Card details and Top Owners
• /set [card_id] - Change profile card for /kc
• /vote - Register/View Popular profile (2000 Coins)

🛡️ <b>Team Commands:</b>
• <b>/team</b> - Create a Team (800 Coins)
• <b>/myteam</b> - Check your Team Status
• <b>/join [CODE]</b> - Apply to join a team
• <b>/out</b> - Leave your current Team
• <b>/out [user_id]</b> - Kick a member (Leader only)
• <b>/dele</b> - Delete your Team (Leader only)

🎁 <b>/kgift Instructions (Reply to a message):</b>
• <b>Send Coins:</b> Reply message with <code>/kgift c100</code>
• <b>Send Card:</b> Reply message with <code>/kgift 1201</code>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("➕ Add To Group", url=f"https://t.me/{bot_info.username}?startgroup=true")
    ]])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

# /addadmin Command (Admin Only)
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

        await update.message.reply_text(f"✅ User <code>{target_id}</code> is now a Card Admin! (Can add cards with /add)", parse_mode="HTML", reply_to_message_id=msg_id)
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID.", reply_to_message_id=msg_id)

# /admin Command
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return

    text = """⚡ <b>Admin Command List</b>

👑 <b>Commands:</b>

1. <b>/game</b> - Trigger game manually
2. <b>/c [count]</b> - Set group message threshold (DM Only)
3. <b>/cbox [amount]</b> - Drop Coin Box in group
4. <b>/k [user_id] [amount]</b> - Add/Remove Coins
5. <b>/addadmin [user_id]</b> - Grant Card Admin permission
6. <b>/add [name]</b> or <b>/add [id].[name]</b> - Add new Card (Reply to photo/video)
7. <b>/del [card_id]</b> - Delete a Card
8. <b>/cardlist</b> - View all Cards
9. <b>/glist</b> - View active group list
10. <b>/g</b> or <b>/r</b> - Set Game/Result Media
11. <b>/stats</b> - View Bot Statistics
12. <b>/broadcast</b> - Broadcast message (Forward reply)"""

    await update.message.reply_text(text, parse_mode="HTML", reply_to_message_id=msg_id)

# /game Command
async def manual_game_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return
    chat_id = update.effective_chat.id
    if chat_id in active_games:
        return await update.message.reply_text("❌ A game is currently active in this group.", reply_to_message_id=msg_id)
    
    asyncio.create_task(start_game(context, chat_id, is_admin_triggered=True))

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

# /team Command
async def team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        user_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)

    if user_team:
        await update.message.reply_text("❌ You are already in a team. Use `/myteam` to check info.", parse_mode="Markdown", reply_to_message_id=msg_id)
    else:
        text = "Create a legendary team and aim for Top 1 to win 𝗚𝗲𝗺𝗦𝘁𝗼𝗻𝗲🗽! (Cost: 800 Coins)"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Create Team", callback_data=f"create_team_{user.id}")
        ]])
        await update.message.reply_text(text, reply_markup=keyboard, reply_to_message_id=msg_id)

# /myteam Command
async def myteam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        user_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)

    if user_team:
        await show_user_team(update, chat.id, user_team['team_code'], reply_to_msg_id=msg_id)
    else:
        await update.message.reply_text("❌ You are not in any team. (Use /team to create one)", reply_to_message_id=msg_id)

# /dele Command
async def delete_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        team = await conn.fetchrow("SELECT team_code, team_name FROM user_teams WHERE leader_id = $1", user.id)
        if not team:
            return await update.message.reply_text("❌ You are not the leader of any team.", reply_to_message_id=msg_id)

        team_code = team['team_code']
        team_name = team['team_name']

        await conn.execute("DELETE FROM team_members WHERE team_code = $1", team_code)
        await conn.execute("DELETE FROM user_teams WHERE team_code = $1", team_code)

    await update.message.reply_text(f"✅ Your team <b>{team_name}</b> has been deleted successfully.", parse_mode="HTML", reply_to_message_id=msg_id)

# /join [CODE] Command
async def join_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/join [TEAM_CODE]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    target_code = context.args[0].strip().upper()

    async with db_pool.acquire() as conn:
        already_in = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", user.id)
        if already_in:
            return await update.message.reply_text("❌ You are already in a team. Leave your team (/out) first.", reply_to_message_id=msg_id)

        team = await conn.fetchrow("SELECT * FROM user_teams WHERE team_code = $1", target_code)
        if not team:
            return await update.message.reply_text("❌ Invalid team code.", reply_to_message_id=msg_id)

        current_count = await conn.fetchval("SELECT COUNT(*) FROM team_members WHERE team_code = $1", target_code)
        if current_count >= team['member_limit']:
            return await update.message.reply_text("❌ This team is already full.", reply_to_message_id=msg_id)

    leader_id = team['leader_id']
    req_text = f"""📩 <b>Team Join Request!</b>

{get_mention(user.id, user.first_name)} requested to join your team <b>{team['team_name']}</b> (Code: <code>{target_code}</code>).

Accept request?"""

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
        await update.message.reply_text("✅ Join request sent to the Team Leader! Please wait for approval.", reply_to_message_id=msg_id)
    except Exception:
        await update.message.reply_text("❌ Failed to send request to Team Leader's DM. The leader must /start the bot.", reply_to_message_id=msg_id)

# /out Command
async def out_team_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

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
                    return await update.message.reply_text("❌ You cannot kick yourself. Use `/dele` to delete the team.", parse_mode="Markdown", reply_to_message_id=msg_id)

                is_member = await conn.fetchrow("SELECT user_id FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, target_kick_id)
                if not is_member:
                    return await update.message.reply_text("❌ This user is not in your team.", reply_to_message_id=msg_id)

                await conn.execute("DELETE FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, target_kick_id)
                return await update.message.reply_text(f"✅ User ID <code>{target_kick_id}</code> has been kicked from the team.", parse_mode="HTML", reply_to_message_id=msg_id)
            except ValueError:
                return await update.message.reply_text("❌ Please enter a valid User ID to kick.", reply_to_message_id=msg_id)

        if user.id == team['leader_id']:
            return await update.message.reply_text("❌ Team Leader cannot leave. Use `/dele` to delete the team.", reply_to_message_id=msg_id)

        await conn.execute("DELETE FROM team_members WHERE team_code = $1 AND user_id = $2", team_code, user.id)

    await update.message.reply_text(f"✅ You have left <b>{team['team_name']}</b> team.", parse_mode="HTML", reply_to_message_id=msg_id)

# /c Command
async def set_count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global global_default_threshold
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return
    if update.effective_chat.type != "private":
        return await update.message.reply_text("❌ This command can only be used in Bot DM.", reply_to_message_id=msg_id)

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
            f"✅ Default group message threshold set to **{count}** messages.",
            parse_mode="Markdown",
            reply_to_message_id=msg_id
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/c 6`", parse_mode="Markdown", reply_to_message_id=msg_id)

# Admin Coin Command
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

        action_text = "added to" if amount >= 0 else "removed from"
        await update.message.reply_text(
            f"✅ <b>{abs(amount)}</b> Kachi Coins {action_text} {get_mention(target_id, new_row['name'])}.\n"
            f"💰 Current Coins: <b>{new_row['coins']}</b>",
            parse_mode="HTML",
            reply_to_message_id=msg_id
        )
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: `/k 1928382 200` or `/k 1928382 -200`", parse_mode="Markdown", reply_to_message_id=msg_id)

# /add Command - Supports /add name (auto random unused id) or /add id.name, then prompts for Rarity via inline buttons
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
        return await update.message.reply_text("❌ Usage: Reply with `/add [name]` or `/add [id].[name]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    card_id = None
    card_name = None

    if "." in raw_args:
        part1, _, part2 = raw_args.partition(".")
        part1 = part1.strip()
        part2 = part2.strip()
        card_id = part1
        card_name = part2
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
            return await update.message.reply_text(f"⚠️ <b>Warning:</b> Card ID (<code>{card_id}</code>) or Media already exists in database.", parse_mode="HTML", reply_to_message_id=msg_id)

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
        f"🎴 <b>Card Info Prepared:</b>\n"
        f"🆔 ID: <code>{card_id}</code>\n"
        f"🏷 Name: {card_name}\n\n"
        f"Please select the <b>Rarity</b> for this card:",
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=msg_id
    )

# /del Command
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

    await update.message.reply_text(f"✅ Card ID <code>{target_card_id}</code> (<b>{card['name']}</b>) permanently deleted.", parse_mode="HTML", reply_to_message_id=msg_id)

# /ksell [amount] Command
async def ksell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/ksell [amount]` (e.g., `/ksell 1`)", parse_mode="Markdown", reply_to_message_id=msg_id)

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
            return await update.message.reply_text(f"❌ You do not have enough GemStone💎. (Current: {curr_gems})", reply_to_message_id=msg_id)

        coins_earned = sell_amount * 200

        if curr_gems == sell_amount:
            await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
        else:
            await conn.execute("UPDATE user_cards SET amount = amount - $1 WHERE user_id = $2 AND card_id = 'gemstone'", sell_amount, user.id)

        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", coins_earned, user.id)
        rem_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)

    await update.message.reply_text(
        f"✅ Successfully sold <b>{sell_amount}</b> GemStone💎!\n\n"
        f"💰 Earned: <b>+{coins_earned}</b> 🩸 Kachi Coins\n"
        f"💳 Total Coins: <b>{rem_coins}</b> 🩸",
        parse_mode="HTML",
        reply_to_message_id=msg_id
    )

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
    team_str = u_info['team_name'] or "None"
    card_id_str = u_info['selected_card_id'] or "Not Set"
    earned_coins = (u_info['popular_votes'] or 0) * 20

    text = f"""📯 <b>𝗣𝗢𝗣𝗨𝗟𝗔𝗥 𝗠𝗘𝗠𝗕𝗘𝗥</b>        
             <b>𝗣𝗥𝗢𝗙𝗜𝗟𝗘</b> ◁

🧸 <b>𝙿𝙾𝙿𝚄𝙻𝙰𝚁 𝚅𝙾𝚃𝙴</b> - <b>{u_info['popular_votes']}</b>
🎐  <b>𝚅𝙾𝚃𝙴 𝚃𝙾𝚃𝙰𝙻 𝙴𝙰𝚁𝙴𝙳 𝙲𝙾𝙸𝙽𝚂</b> - <b>{earned_coins}</b>

🍀 <b>𝑁𝑎𝑚𝑒</b> - {get_mention(u_info['user_id'], u_info['name'])}
🍀   <b>𝑈𝑆𝐸𝑅 𝐼𝐷</b> - <code>{u_info['user_id']}</code>
🩸 <b>𝐾𝑎𝑐ℎ𝑖 𝐶𝑜𝑖𝑛</b> - <b>{u_info['coins']}</b>
  💎  <b>𝐺𝑒𝑚𝑆𝑡𝑜𝑛𝑒</b> - <b>{gems}</b>
🍀 <b>𝑆𝑒𝑙𝑒𝑐𝑡𝑒𝑑 𝐶𝑎𝑟𝑑 𝐼𝐷</b> - <code>{card_id_str}</code>
   🎖 <b>𝐺𝑙𝑜𝑏𝘢𝑙 𝑅𝑎𝑛𝑘</b> - #{u_info['global_rank']}
〇 <b>𝑇𝑒𝑎𝑚</b> - <b>{team_str}</b>"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗳️ Vote Him (5 Tickets)", callback_data=f"pop_vote_{target_uid}_0"),
            InlineKeyboardButton("💎 Gem Gift (1 Gem)", callback_data=f"pop_gemgift_{target_uid}_0")
        ]
    ])
    return text, keyboard

# /vote Command
async def vote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT is_popular FROM users WHERE user_id = $1", user.id)

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

    text = f"""👋 Hello {get_mention(user.id, user.first_name)} !

🌟 <b>Ready to join Popular Members?</b>

Apply for Popular list and collect votes from other users!

<i>(Registration Cost: <b>2000 Kachi Coins</b> 🩸)</i>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔥 Become Popular", callback_data=f"reg_popular_{user.id}")
    ]])

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, reply_to_message_id=msg_id)

# /set Command
async def set_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

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
            return await update.message.reply_text(f"❌ You do not possess Card ID <code>{target_card_id}</code>.", parse_mode="HTML", reply_to_message_id=msg_id)

        await conn.execute("UPDATE users SET selected_card_id = $1 WHERE user_id = $2", target_card_id, user.id)

    await update.message.reply_text(f"✅ Selected card for /kc changed to <b>{has_card['name']}</b>.", parse_mode="HTML", reply_to_message_id=msg_id)

# /kbox Command
async def kbox_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
        coins = row['coins'] if row else 0

    if coins < 650:
        insufficient_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎴 View Cards", url="https://t.me/beyondpoe")
        ]])
        return await update.message.reply_text(
            f"❌ Hello {get_mention(user.id, user.first_name)}, you need 650 Kachi Coins to spin the box.\nYou currently have {coins} Coins.",
            parse_mode="HTML",
            reply_markup=insufficient_keyboard,
            reply_to_message_id=msg_id
        )

    text = f"{get_mention(user.id, user.first_name)} is opening the Card Box, let's see your luck..."
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎰 Spin Now", callback_data=f"spin_{user.id}"),
        InlineKeyboardButton("🎴 View Cards", url="https://t.me/beyondpoe")
    ]])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=msg_id
    )

# /kgift Command
async def kgift_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    sender = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    reply_msg = update.message.reply_to_message

    if not reply_msg or not reply_msg.from_user or reply_msg.from_user.is_bot:
        return await update.message.reply_text("❌ Reply to a message of the user you want to send a gift to.", reply_to_message_id=msg_id)

    receiver = reply_msg.from_user
    if sender.id == receiver.id:
        return await update.message.reply_text("❌ You cannot send a gift to yourself.", reply_to_message_id=msg_id)

    await register_user_group(sender, chat)
    await register_user_group(receiver, chat)

    if not context.args:
        return await update.message.reply_text("❌ Usage:\n• Send Card: Reply with `/kgift [card_id]`\n• Send Coins: Reply with `/kgift c[amount]`", parse_mode="Markdown", reply_to_message_id=msg_id)

    arg = context.args[0].strip()

    if arg.lower().startswith("c") and arg[1:].isdigit():
        amount = int(arg[1:])
        if amount <= 0:
            return await update.message.reply_text("❌ Amount must be greater than 0.", reply_to_message_id=msg_id)

        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", sender.id)
            sender_coins = user_row['coins'] if user_row else 0

        if sender_coins < amount:
            return await update.message.reply_text(f"❌ You do not have enough Coins ({amount}). (Current: {sender_coins} 🩸)", reply_to_message_id=msg_id)

        text = f"""🎁 <b>Kachi Coin Gift Transfer</b>

👤 <b>Sender:</b> {get_mention(sender.id, sender.first_name)}
👤 <b>Receiver:</b> {get_mention(receiver.id, receiver.first_name)}
💰 <b>Gift Amount:</b> <b>{amount}</b> 🩸 Kachi Coins

<i>Click Gift button below to confirm transfer.</i>"""

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

    else:
        card_id = arg
        async with db_pool.acquire() as conn:
            card = await conn.fetchrow("SELECT card_id, name, type, file_id FROM cards WHERE card_id = $1", card_id)
            if not card:
                return await update.message.reply_text(f"❌ Card ID <code>{card_id}</code> not found.", parse_mode="HTML", reply_to_message_id=msg_id)

            user_card = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", sender.id, card_id)
            if not user_card or user_card['amount'] <= 0:
                return await update.message.reply_text(f"❌ You do not possess Card ID <code>{card_id}</code> (<b>{card['name']}</b>).", parse_mode="HTML", reply_to_message_id=msg_id)

        text = f"""🎁 <b>Kachi Card Gift Transfer</b>

👤 <b>Sender:</b> {get_mention(sender.id, sender.first_name)}
👤 <b>Receiver:</b> {get_mention(receiver.id, receiver.first_name)}

🎴 <b>Card Info:</b>
🏷️ <b>Name:</b> {card['name']}
🆔 <b>Card ID:</b> <code>{card['card_id']}</code>

<i>Click Gift button below to confirm transfer.</i>"""

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
            SELECT c.card_id, c.name, c.type, c.file_id, c.rarity, uc.amount 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.card_id 
            WHERE uc.user_id = $1 AND uc.amount > 0
            ORDER BY c.card_id ASC
        """, target_id)

    text_header = f"""❀ 𝙉𝘼𝙈𝙀 - {get_mention(target_id, display_name)}
        ⬤ 𝐼𝐷 - <code>{target_id}</code>
🩸 𝙆𝙖𝙘𝙝𝙞 𝘾𝙤𝙞𝙣 - <b>{coins}</b>
      💎 𝐺𝑒𝑚𝑆𝑡𝑜𝑛𝑒 - <b>{gem_count}</b>
🎟𝙑𝙤𝙩𝙚 𝙏𝙞𝙘𝙠𝙚𝙩𝙨 - <b>{tickets}</b>
        
❀ ɢʟᴏʙ𝙖ʟ ɴᴏ - #{rank}"""

    if not user_card_rows:
        full_text = f"{text_header}\n\n❄ <b>Owned Cards</b>\n<i>No cards owned yet.</i>"
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
        rarity_emoji = "🪞" if c.get('rarity') == 'Kiwami' else ("✨" if c.get('rarity') == 'Kami' else ("⚜️" if c.get('rarity') == 'Hoshi' else "💮"))
        cards_info_list.append(f"{rarity_emoji} {c['name']} ( <code>{c['card_id']}</code> ){count_str}")

    cards_info = "\n".join(cards_info_list)
    page_str = f" (Page {page + 1}/{total_pages})" if total_pages > 1 else ""
    full_text = f"{text_header}\n\n❄ <b>Owned Cards{page_str}</b>\n\n{cards_info}"

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
async def check_kc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    await register_user_group(user, chat)
    await render_kc_view(update, context, page=0, owner_id=user.id)

# /cardlist Command
async def cardlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_cardlist_page(update, context, page=0, owner_id=update.effective_user.id)

async def render_cardlist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0, owner_id: int = None):
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None
    async with db_pool.acquire() as conn:
        cards = await conn.fetch("SELECT card_id, name, type, rarity FROM cards ORDER BY card_id ASC")

    if not cards:
        text = "🎴 <b>Card List is empty.</b>"
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
📌 <i>Use <code>/card [card_id]</code> to view details.</i>

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
    if not await check_force_join(update, context):
        return
    user = update.effective_user
    chat = update.effective_chat
    msg_id = update.message.message_id
    await register_user_group(user, chat)

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

    caption_text = f"""🎗𝘾𝘼𝙍𝘿 𝙄𝙉𝙁𝙊𝙍𝙈𝘼𝙏𝙄𝙊𝙉 ♡

▰▰▱▱▰▰▱▱▰▰▱▱
🍀 𝘕𝘈𝘔𝘌 - {card['name']}
    🍀  𝘐𝘋 - <code>{card['card_id']}</code>
🎬 𝘛𝘠𝘗𝘌 - {card['type'].upper()}
🌟 𝘙𝘈𝘙𝘐𝘛𝘠 - {r_emoji} {r}
   🐠𝘎𝘓𝘖𝘉𝘈𝘓 𝘋𝘙𝘖𝘗 𝘊𝘖𝘜𝘕𝘛 - <b>{global_drop_count}</b>

▱▱▰▰▱▱▰▰▱▱▰▰
𝘛𝘖𝘗 𝘖𝘞𝘕𝘌𝘙𝘛 🐾
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
async def glist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await render_glist_page(update, context, page=0)

async def render_glist_page(update_or_query, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    msg_id = update_or_query.message.message_id if isinstance(update_or_query, Update) and update_or_query.message else None
    async with db_pool.acquire() as conn:
        groups = await conn.fetch("SELECT chat_id, title, added_by_id, added_by_name FROM groups")

    if not groups:
        text = "🏰 **Group list is empty.**"
        if isinstance(update_or_query, Update):
            return await update_or_query.message.reply_text(text, parse_mode="Markdown", reply_to_message_id=msg_id)
        else:
            return await update_or_query.edit_message_text(text, parse_mode="Markdown")

    total_groups = len(groups)
    g = groups[page]
    chat_id = g['chat_id']

    member_count = "N/A"
    invite_link = "Not available"
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

        return await update.message.reply_text(f"🗑 {'Game' if target == 'g' else 'Result'} Media deleted.", reply_to_message_id=msg_id)

    reply = update.message.reply_to_message
    if not reply:
        return await update.message.reply_text("❌ Reply to a photo or video with command.", reply_to_message_id=msg_id)

    media_obj = None
    if reply.photo:
        media_obj = {"type": "photo", "file_id": reply.photo[-1].file_id}
    elif reply.video:
        media_obj = {"type": "video", "file_id": reply.video.file_id}
    else:
        return await update.message.reply_text("❌ Please reply with Photo or Video.", reply_to_message_id=msg_id)

    if target == "g":
        game_media = media_obj
    else:
        result_media = media_obj

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
        """, key, json.dumps(media_obj))

    await update.message.reply_text(f"✅ {'Game' if target == 'g' else 'Result'} Media updated.", reply_to_message_id=msg_id)

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
        await bot.send_message(chat_id, f"✅ Broadcast finished! (Success: {success}/{len(targets)})")
    except Exception:
        pass

# /broadcast Command
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = update.message.message_id
    if update.effective_user.id != ADMIN_ID:
        return
    reply = update.message.reply_to_message
    if not reply:
        return await update.message.reply_text("❌ Reply to a message you want to broadcast with /broadcast.", reply_to_message_id=msg_id)

    async with db_pool.acquire() as conn:
        users = [r['user_id'] for r in await conn.fetch("SELECT user_id FROM users")]
        groups = [r['chat_id'] for r in await conn.fetch("SELECT chat_id FROM groups")]

    targets = list(set(users + groups))
    status_msg = await update.message.reply_text(f"🚀 Broadcast started in background... (Targets: {len(targets)})", reply_to_message_id=msg_id)

    asyncio.create_task(run_async_broadcast(
        context.bot,
        update.effective_chat.id,
        reply.message_id,
        targets,
        status_msg.message_id
    ))

# Message Handler
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.message
    if not chat or not msg:
        return

    await register_user_group(user, chat)

    if chat.type == "private":
        if user.id in team_creation_state:
            state = team_creation_state[user.id]
            step = state.get("step")

            if step == "name":
                t_name = msg.text.strip() if msg.text else ""
                if not t_name or len(t_name) > 30:
                    return await msg.reply_text("❌ Team Name must be between 1 and 30 characters.", reply_to_message_id=msg.message_id)

                state["team_name"] = t_name
                state["step"] = "limit"

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("1/7", callback_data=f"tlimit_7_{user.id}"), InlineKeyboardButton("1/9", callback_data=f"tlimit_9_{user.id}")],
                    [InlineKeyboardButton("1/13", callback_data=f"tlimit_13_{user.id}"), InlineKeyboardButton("1/15", callback_data=f"tlimit_15_{user.id}")]
                ])
                await msg.reply_text("✅ Team Name set!\n\nSelect Team Member Limit:", reply_markup=keyboard, reply_to_message_id=msg.message_id)
                return

            elif step == "logo":
                if not msg.photo and not msg.video:
                    return await msg.reply_text("⚠️ Please send Photo or Video for Team Logo.", reply_to_message_id=msg.message_id)

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
                    coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)
                    if not coins or coins < 800:
                        del team_creation_state[user.id]
                        return await msg.reply_text("❌ You don't have enough Coins (800 required). Creation cancelled.", reply_to_message_id=msg.message_id)

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
        
        if chat_id not in active_games:
            group_msg_count[chat_id] = group_msg_count.get(chat_id, 0) + 1
            threshold = group_threshold.get(chat_id, global_default_threshold)

            if group_msg_count[chat_id] >= threshold:
                group_msg_count[chat_id] = 0
                asyncio.create_task(start_game(context, chat_id, is_admin_triggered=False))

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
            InlineKeyboardButton("🔥 Popular", callback_data="pop_view_0")
        ]
    ])

async def render_popular_view(query, context: ContextTypes.DEFAULT_TYPE, current_idx: int = 0):
    async with db_pool.acquire() as conn:
        popular_users = await conn.fetch("SELECT user_id FROM users WHERE is_popular = TRUE")

    if not popular_users:
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="lb_back")]])
        try:
            if query.message.caption:
                await query.edit_message_caption(caption="📯 <b>𝗣𝗢𝗣𝗨𝗟𝗔𝗥 𝗠𝗘𝗠𝗕𝗘𝗥𝗦</b>\n\n<i>No popular members registered yet. Use /vote to apply.</i>", parse_mode="HTML", reply_markup=back_markup)
            else:
                await query.edit_message_text(text="📯 <b>𝗣𝗢𝗣𝗨𝗟𝗔𝗥 𝗠𝗘𝗠𝗕𝗘𝗥𝗦</b>\n\n<i>No popular members registered yet. Use /vote to apply.</i>", parse_mode="HTML", reply_markup=back_markup)
        except Exception:
            pass
        return

    pop_uids = [r['user_id'] for r in popular_users]
    random.seed(int(time.time() // 10) + current_idx)
    random.shuffle(pop_uids)

    total_pop = len(pop_uids)
    current_idx = current_idx % total_pop
    target_uid = pop_uids[current_idx]

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
    card_id_str = u_info['selected_card_id'] or "Not Set"
    earned_coins = (u_info['popular_votes'] or 0) * 20

    text = f"""📯 <b>𝗣𝗢𝗣𝗨𝗟𝗔𝗥 𝗠𝗘𝗠𝗕𝗘𝗥</b>        
             <b>𝗣𝗥𝗢𝗙𝗜𝗟𝗘</b> ◁ (<b>{current_idx + 1}</b>/<b>{total_pop}</b>)

🧸 <b>𝙿𝙾𝙿𝚄𝙻𝙰𝚁 𝚅𝙾𝚃𝙴</b> - <b>{u_info['popular_votes']}</b>
🎐  <b>𝚅𝙾𝚃𝙴 𝚃𝙾𝚃𝙰𝙻 𝙴𝙰𝚁𝙴𝙳 𝙲𝙾𝙸𝙽𝚂</b> - <b>{earned_coins}</b>

🍀 <b>𝑁𝑎𝑚𝑒</b> - {get_mention(u_info['user_id'], u_info['name'])}
🍀   <b>𝑈𝑆𝐸𝑅 𝐼𝐷</b> - <code>{u_info['user_id']}</code>
🩸 <b>𝐾𝑎𝑐ℎ𝑖 𝐶𝑜𝑖𝑛</b> - <b>{u_info['coins']}</b>
  💎  <b>𝐺𝑒𝑚𝑆𝑡𝑜𝑛𝑒</b> - <b>{gems}</b>
🍀 <b>𝑆𝑒𝑙𝑒𝑐𝑡𝑒𝑑 𝐶𝑎𝑟𝑑 𝐼𝐷</b> - <code>{card_id_str}</code>
   🎖 <b>𝐺𝑙𝑜𝑏𝑎𝑙 𝑅𝑎𝑛𝑘</b> - #{u_info['global_rank']}
〇 <b>𝑇𝑒𝑎𝑚</b> - <b>{team_str}</b>"""

    buttons = [
        [
            InlineKeyboardButton("◀️ Back", callback_data=f"pop_view_{current_idx - 1}"),
            InlineKeyboardButton("🗳️ Vote (5 Tickets)", callback_data=f"pop_vote_{target_uid}_{current_idx}"),
            InlineKeyboardButton("Next ▶️", callback_data=f"pop_view_{current_idx + 1}")
        ],
        [InlineKeyboardButton("💎 Gem Gift (1 Gem)", callback_data=f"pop_gemgift_{target_uid}_{current_idx}")],
        [InlineKeyboardButton("🔙 Menu", callback_data="lb_back")]
    ]
    markup = InlineKeyboardMarkup(buttons)

    card = await get_user_card_media(target_uid)
    media_sent = False

    if card:
        try:
            if card['type'] == 'photo':
                media = InputMediaPhoto(media=card['file_id'], caption=text, parse_mode="HTML")
            else:
                media = InputMediaVideo(media=card['file_id'], caption=text, parse_mode="HTML")
            await query.edit_message_media(media=media, reply_markup=markup)
            media_sent = True
        except Exception:
            pass

    if not media_sent:
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=markup)
            else:
                await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=markup)
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
        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="lb_back")]])
        try:
            if query.message.caption:
                await query.edit_message_caption(caption="🌐 <b>GLOBAL TOP TEAMS (TOP 5)</b>\n\n<i>No teams created yet.</i>", parse_mode="HTML", reply_markup=back_markup)
            else:
                await query.edit_message_text(text="🌐 <b>GLOBAL TOP TEAMS (TOP 5)</b>\n\n<i>No teams created yet.</i>", parse_mode="HTML", reply_markup=back_markup)
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
        member_lines.append(f"⇋ {get_mention(m['user_id'], m['name'])} — 🩸{m['coins']} (Played: {m['total_games']} | WR: {m_wr}%)")

    members_str = "\n".join(member_lines)

    text = f"""🌐 <b>GLOBAL TOP TEAM (RANK #{page + 1}/{total_teams})</b>

TEAM - <b>{t['team_name']}</b>
Code: <code>{t['team_code']}</code>

 ▱ <i>Leader</i> : {get_mention(t['leader_id'], t['leader_name'])}
 🩸 Total Coins: <b>{t['total_coins']}</b> | 🎯 Winrate: <b>{wr}%</b>

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

# Helper to trigger Card Drop session with weighted random card
async def trigger_card_drop(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    async with db_pool.acquire() as conn:
        drop_card = await get_weighted_random_card(conn)
    if not drop_card:
        return

    drop_text = f"""❀ 𝙃𝙚𝙮𝙮𝙮𝙮 𝙒𝙖𝙞𝙩 𝘼 𝙈𝙞𝙣𝙪𝙩𝙚 ❀

4 or more winners or 4+ goals scored in Game❄! 

A Card will drop now!

⏱️ 𝙏𝙞𝙢𝙚 : 00:30

📋 <b>Live List:</b>
<i>No one joined yet.</i>"""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Join (1/5)", callback_data="join_card_drop")
    ]])

    if drop_card['type'] == 'photo':
        msg = await context.bot.send_photo(chat_id, drop_card['file_id'], caption=drop_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        msg = await context.bot.send_video(chat_id, drop_card['file_id'], caption=drop_text, parse_mode="HTML", reply_markup=keyboard)

    active_card_drops[msg.message_id] = {
        "chat_id": chat_id,
        "card": drop_card,
        "joined_users": {},
        "timer": 30,
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

        joined_lines = []
        for uid, uname in drop["joined_users"].items():
            joined_lines.append(f"• {get_mention(uid, uname)}")
        list_str = "\n".join(joined_lines) if joined_lines else "<i>No one joined yet.</i>"

        current_count = len(drop["joined_users"])
        timer_str = f"00:{drop['timer']:02d}"
        
        drop_text = f"""❀ 𝙃𝙚𝙮𝙮𝙮𝙮 𝙒𝙖𝙞𝙩 𝘼 𝙈𝙞𝙣𝙪𝙩𝙚 ❀

4 or more winners or 4+ goals scored in Game❄! 

A Card will drop now!

⏱️ 𝙏𝙞𝙢𝙚 : {timer_str}

📋 <b>Live List:</b>
{list_str}"""

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"Join ({current_count}/5)", callback_data="join_card_drop")
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

    if joined:
        winner_id, winner_name = random.choice(list(joined.items()))
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, winner_id, card['card_id'])

        r = card.get('rarity', 'Ten')
        r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))
        win_msg = f"🍭{get_mention(winner_id, winner_name)} Congratulations, You Got A New 𝘾𝘼𝙍𝘿 𝙉𝘼𝙈𝙀 - <b>{card['name']}</b> ({r_emoji} {r})\n\n𝙄𝘿 ( <code>{card['card_id']}</code> )"
        
        try:
            if card['type'] == 'photo':
                await context.bot.send_photo(chat_id, photo=card['file_id'], caption=win_msg, parse_mode="HTML")
            else:
                await context.bot.send_video(chat_id, video=card['file_id'], caption=win_msg, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(chat_id, text=win_msg, parse_mode="HTML")
    else:
        win_msg = f"❌ No one joined, Card Drop for <b>{card['name']}</b> cancelled."
        try:
            await context.bot.send_message(chat_id, text=win_msg, parse_mode="HTML")
        except Exception:
            pass

    if msg_id in active_card_drops:
        del active_card_drops[msg_id]

# Game Flow
async def start_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int, is_admin_triggered: bool = False):
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
    all_participants = list(game_state["bets"].keys())

    async with db_pool.acquire() as conn:
        for uid, choice in game_state["bets"].items():
            uname = game_state["user_names"][uid]
            await conn.execute("UPDATE users SET total_games = total_games + 1 WHERE user_id = $1", uid)

            if choice == win_choice:
                reward = 100 if win_choice == "draw" else 70
                await add_coins(uid, reward)
                await conn.execute("UPDATE users SET wins = wins + 1, vote_tickets = vote_tickets + 10 WHERE user_id = $1", uid)
                winners.append(f"{uname} (+{reward} 🩸 | +10 🎟️)")
            else:
                losers.append(uname)

        gemstone_winner_str = ""
        if len(all_participants) >= 4:
            random_gem_user = random.choice(all_participants)
            gem_uname = game_state["user_names"][random_gem_user]
            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, 'gemstone', 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, random_gem_user)
            gemstone_winner_str = f"\n\n💎 <b>Random GemStone Winner:</b> {gem_uname} (+1 GemStone 💎)"

    win_str = "\n".join(winners) if winners else "—"
    loss_str = "\n".join(losers) if losers else "—"

    res_text = f"""🎗️  𝗠𝗮𝘁𝗰𝗵 𝗥𝗲𝘀𝘂𝗹𝘁   🧶

🏖️ <b>{home_team['name']}</b> {home_g} - {away_g} <b>{away_team['name']}</b> 🪂

⚡ <b>Win</b> - {win_name}

✨ <b>𝐖𝐢𝐧𝐧𝐞𝐫𝐬</b> -
{win_str}

🐸 <b>𝐋𝐨𝐬𝐬𝐞𝐫𝐬</b> -
{loss_str}{gemstone_winner_str}"""

    leader_markup = get_leaderboard_buttons()

    if result_media:
        if result_media["type"] == "photo":
            sent_res = await context.bot.send_photo(chat_id, result_media["file_id"], caption=res_text, parse_mode="HTML", reply_markup=leader_markup)
        else:
            sent_res = await context.bot.send_video(chat_id, result_media["file_id"], caption=res_text, parse_mode="HTML", reply_markup=leader_markup)
    else:
        sent_res = await context.bot.send_message(chat_id, res_text, parse_mode="HTML", reply_markup=leader_markup)

    last_results[sent_res.message_id] = res_text
    
    total_goals = home_g + away_g
    if len(winners) >= 4 or total_goals >= 4 or is_admin_triggered:
        await asyncio.sleep(7)
        snail_msg = await context.bot.send_message(chat_id, "🐌")
        await asyncio.sleep(4)
        try:
            await context.bot.delete_message(chat_id, snail_msg.message_id)
        except Exception:
            pass
        asyncio.create_task(trigger_card_drop(context, chat_id))

    if chat_id in active_games:
        del active_games[chat_id]

# Background task for spinning box with weighted random card
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
            new_amount = await conn.fetchval("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", user.id, won_card['card_id'])

        try:
            await query_message.delete()
        except Exception:
            pass

        amount_notice = f"\n📦 <b>Total Owned:</b> {new_amount}x" if new_amount > 1 else ""
        r = won_card.get('rarity', 'Ten')
        r_emoji = "🪞" if r == 'Kiwami' else ("✨" if r == 'Kami' else ("⚜️" if r == 'Hoshi' else "💮"))

        win_text = f"""🎉 <b>Congratulations {get_mention(user.id, user.first_name)}!</b>

🆔 <b>User ID:</b> <code>{user.id}</code>
💰 <b>Remaining Coins:</b> {rem_coins} 🩸

🎴 <b>Card Won:</b>
🏷 <b>Name:</b> {won_card['name']}
🌟 <b>Rarity:</b> {r_emoji} {r}
🔢 <b>Card ID:</b> <code>{won_card['card_id']}</code>{amount_notice}"""

        if won_card['type'] == 'photo':
            await bot.send_photo(chat_id=chat_id, photo=won_card['file_id'], caption=win_text, parse_mode="HTML")
        else:
            await bot.send_video(chat_id=chat_id, video=won_card['file_id'], caption=win_text, parse_mode="HTML")
    except Exception as e:
        print(f"Spin Error: {e}")

# Callback Query Handler
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    user = query.from_user
    data = query.data

    await register_user_group(user, query.message.chat)

    if data.startswith("addrarity_"):
        parts = data.split("_")
        allowed_uid = int(parts[1])
        rarity = parts[2]

        if user.id != allowed_uid:
            return await query.answer("❌ Not meant for you.", show_alert=True)

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

            if is_card_admin and user.id != ADMIN_ID:
                await conn.execute("UPDATE users SET coins = coins + 20 WHERE user_id = $1", user.id)

        del pending_card_adds[user.id]

        r_emoji = "🪞" if rarity == 'Kiwami' else ("✨" if rarity == 'Kami' else ("⚜️" if rarity == 'Hoshi' else "💮"))
        log_text = f"""𝙉𝙚𝙬 𝘾𝙖𝙧𝙙 𝘼𝙙𝙙𝙚𝙙

❀𝘊𝘢𝘳𝘥 𝘕𝘢𝘮𝘦 : {card_name}
     ❝  𝙸𝙳 : {card_id}
❀ 𝘛𝘺𝘱𝘦 : {c_type.capitalize()}
🌟 𝘙𝘢𝘳𝘪𝘵𝘺 : {r_emoji} {rarity}
👤 𝘼𝙙𝙙𝙚𝙙 𝘽𝙮 : {get_mention(user.id, user.first_name)}"""

        try:
            if c_type == "photo":
                await context.bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=file_id, caption=log_text, parse_mode="HTML")
            else:
                await context.bot.send_video(chat_id=LOG_CHANNEL_ID, video=file_id, caption=log_text, parse_mode="HTML")
        except Exception:
            pass

        reward_notice = "\n🎉 You received <b>+20 Kachi Coins</b> for adding a card!" if (is_card_admin and user.id != ADMIN_ID) else ""
        await query.message.edit_text(
            f"✅ Card added successfully!\n\n🆔 Card ID: <code>{card_id}</code>\n🎴 Card Name: {card_name}\n🌟 Rarity: {r_emoji} {rarity}{reward_notice}",
            parse_mode="HTML"
        )
        await query.answer("✅ Card added successfully!")
        return

    if data.startswith("check_join_"):
        target_uid = int(data.split("_")[2])
        if user.id != target_uid:
            return await query.answer("❌ Not meant for you.", show_alert=True)
        try:
            member = await context.bot.get_chat_member(chat_id="@beyondpoe", user_id=user.id)
            if member.status in ['left', 'kicked']:
                return await query.answer("❌ You have not joined the channel yet! Please join first.", show_alert=True)
            else:
                await query.answer("✅ Thank you for joining! You can now use commands.", show_alert=True)
                try:
                    await query.message.edit_text("✅ Verified! You can now use all commands.", parse_mode="HTML")
                except Exception:
                    pass
        except Exception:
            await query.answer("✅ Verified! You can now use commands.", show_alert=True)
            try:
                await query.message.edit_text("✅ Verified! You can now use all commands.", parse_mode="HTML")
            except Exception:
                pass
        return

    if data == "join_card_drop":
        drop = active_card_drops.get(msg_id)
        if not drop or drop["ended"]:
            return await query.answer("❌ This Card Drop session has ended.", show_alert=True)

        if user.id in drop["joined_users"]:
            return await query.answer("❌ You have already joined!", show_alert=True)

        if len(drop["joined_users"]) >= 5:
            return await query.answer("❌ Session is full (5/5)!", show_alert=True)

        drop["joined_users"][user.id] = user.first_name
        await query.answer("✅ Successfully joined Card Drop!", show_alert=True)

        if len(drop["joined_users"]) >= 5:
            await finalize_card_drop(context, msg_id)
        else:
            joined_lines = []
            for uid, uname in drop["joined_users"].items():
                joined_lines.append(f"• {get_mention(uid, uname)}")
            list_str = "\n".join(joined_lines)

            current_count = len(drop["joined_users"])
            timer_str = f"00:{drop['timer']:02d}"

            drop_text = f"""❀ 𝙃𝙚𝙮𝙮𝙮𝙮 𝙒𝙖𝙞𝙩 𝘼 𝙈𝙞𝙣𝙪𝙩𝙚 ❀

4 or more winners or 4+ goals scored in Game❄! 

A Card will drop now!

⏱️ 𝙏𝙞𝙢𝙚 : {timer_str}

📋 <b>Live List:</b>
{list_str}"""

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"Join ({current_count}/5)", callback_data="join_card_drop")
            ]])

            try:
                await query.edit_message_caption(caption=drop_text, parse_mode="HTML", reply_markup=keyboard)
            except Exception:
                pass
        return

    if data.startswith("reg_popular_"):
        allowed_uid = int(data.split("_")[2])
        if user.id != allowed_uid:
            return await query.answer("❌ Not meant for you.", show_alert=True)

        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT coins, is_popular FROM users WHERE user_id = $1", user.id)
            if user_row and user_row['is_popular']:
                return await query.answer("❌ You are already registered in Popular list!", show_alert=True)

            if not user_row or user_row['coins'] < 2000:
                return await query.answer("❌ You need at least 2000 Kachi Coins!", show_alert=True)

            await conn.execute("UPDATE users SET coins = coins - 2000, is_popular = TRUE WHERE user_id = $1", user.id)

        await query.answer("🎉 Successfully registered to Popular list!", show_alert=True)
        await query.edit_message_text(f"🎉 Congratulations {get_mention(user.id, user.first_name)}!\n\nYou have been added to the Popular list.", parse_mode="HTML")
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
            return await query.answer("❌ You cannot send a Gem Gift to yourself!", show_alert=True)

        async with db_pool.acquire() as conn:
            sender_gem = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
            gems = sender_gem['amount'] if sender_gem else 0

            if gems < 1:
                return await query.answer("❌ You don't have enough GemStone💎!", show_alert=True)

            if gems == 1:
                await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = 'gemstone'", user.id)
            else:
                await conn.execute("UPDATE user_cards SET amount = amount - 1 WHERE user_id = $1 AND card_id = 'gemstone'", user.id)

            await conn.execute("""
                INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, 'gemstone', 1)
                ON CONFLICT (user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
            """, target_uid)

        await query.answer("💎 Sent 1 GemStone successfully!", show_alert=True)

        if query.message.reply_markup and any("Next" in b.text or "Back" in b.text for row in query.message.reply_markup.inline_keyboard for b in row):
            await render_popular_view(query, context, current_idx=c_idx)
        else:
            text, keyboard = await get_popular_profile_data(target_uid)
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
            return await query.answer("❌ You cannot vote for yourself!", show_alert=True)

        async with db_pool.acquire() as conn:
            voter_row = await conn.fetchrow("SELECT vote_tickets FROM users WHERE user_id = $1", user.id)
            tickets = voter_row['vote_tickets'] if voter_row else 0

            if tickets < 5:
                return await query.answer("❌ You need at least 5 Vote Tickets! (Earn tickets by winning games)", show_alert=True)

            await conn.execute("UPDATE users SET vote_tickets = vote_tickets - 5 WHERE user_id = $1", user.id)
            await conn.execute("UPDATE users SET popular_votes = popular_votes + 1, coins = coins + 20 WHERE user_id = $1", target_uid)

        await query.answer("🗳️ Vote submitted! (-5 Tickets)", show_alert=True)

        if query.message.reply_markup and any("Next" in b.text or "Back" in b.text for row in query.message.reply_markup.inline_keyboard for b in row):
            await render_popular_view(query, context, current_idx=c_idx)
        else:
            text, keyboard = await get_popular_profile_data(target_uid)
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
            return await query.answer("❌ Not meant for you.", show_alert=True)

        async with db_pool.acquire() as conn:
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)
            if not coins or coins < 800:
                return await query.answer("❌ You need 800 Kachi Coins to create a Team!", show_alert=True)

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
            await query.edit_message_text(f"✅ {get_mention(user.id, user.first_name)}, check Bot DM to complete team setup!", parse_mode="HTML")
        except Exception:
            if user.id in team_creation_state:
                del team_creation_state[user.id]
            await query.answer("❌ Failed to message you in DM. Please /start the bot in DM first.", show_alert=True)

        return

    if data.startswith("tlimit_"):
        parts = data.split("_")
        limit_val = int(parts[1])
        allowed_id = int(parts[2])

        if user.id != allowed_id:
            return await query.answer("❌ Unauthorized action.", show_alert=True)

        if user.id in team_creation_state:
            team_creation_state[user.id]["limit"] = limit_val
            team_creation_state[user.id]["step"] = "logo"

            await query.answer()
            await query.edit_message_text(f"✅ Member Limit set to <b>1/{limit_val}</b>!\n\nNext, please send your <b>Team Logo</b> (Photo or Video):", parse_mode="HTML")
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
                await query.edit_message_text("❌ <b>Team join request rejected.</b>", parse_mode="HTML")
                try:
                    await context.bot.send_message(applicant_id, f"❌ Your request to join <b>{team['team_name']}</b> was rejected by the leader.", parse_mode="HTML")
                except Exception:
                    pass
                return await query.answer()

            elif action == "yes":
                curr_cnt = await conn.fetchval("SELECT COUNT(*) FROM team_members WHERE team_code = $1", team_code)
                if curr_cnt >= team['member_limit']:
                    return await query.answer("❌ Your team is full.", show_alert=True)

                app_in_team = await conn.fetchrow("SELECT team_code FROM team_members WHERE user_id = $1", applicant_id)
                if app_in_team:
                    return await query.answer("❌ This user has joined another team.", show_alert=True)

                await conn.execute("INSERT INTO team_members (team_code, user_id) VALUES ($1, $2)", team_code, applicant_id)
                if msg_id in pending_joins:
                    del pending_joins[msg_id]

                await query.edit_message_text(f"✅ <b>New member accepted!</b>", parse_mode="HTML")
                try:
                    await context.bot.send_message(applicant_id, f"🎉 <b>Congratulations!</b> You have been accepted into <b>{team['team_name']}</b> team.", parse_mode="HTML")
                except Exception:
                    pass
                return await query.answer()

    if data.startswith("gift_"):
        parts = data.split("_")
        action = parts[1]
        allowed_sender_id = int(parts[2])

        if user.id != allowed_sender_id:
            return await query.answer("❌ Only the sender can interact with this.", show_alert=True)

        gift_info = pending_gifts.get(msg_id)
        if not gift_info:
            return await query.answer("❌ Gift transfer expired.", show_alert=True)

        if action == "cancel":
            del pending_gifts[msg_id]
            cancel_text = "❌ <b>Gift Transfer cancelled by sender.</b>"
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
                        return await query.answer("❌ You don't have enough coins.", show_alert=True)

                    await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", amount, sender_id)
                    await conn.execute("""
                        INSERT INTO users (user_id, name, coins) VALUES ($1, $2, $3)
                        ON CONFLICT(user_id) DO UPDATE SET coins = users.coins + EXCLUDED.coins
                    """, receiver_id, receiver_name, amount)

                    success_text = f"✅ {get_mention(sender_id, user.first_name)} sent <b>{amount}</b> 🩸 Kachi Coins to {get_mention(receiver_id, receiver_name)}!"

                elif gift_info["type"] == "card":
                    card_id = gift_info["card_id"]
                    card_name = gift_info["card_name"]

                    s_card = await conn.fetchrow("SELECT amount FROM user_cards WHERE user_id = $1 AND card_id = $2", sender_id, card_id)
                    if not s_card or s_card['amount'] <= 0:
                        return await query.answer(f"❌ You no longer possess Card ID {card_id}.", show_alert=True)

                    if s_card['amount'] == 1:
                        await conn.execute("DELETE FROM user_cards WHERE user_id = $1 AND card_id = $2", sender_id, card_id)
                    else:
                        await conn.execute("UPDATE user_cards SET amount = amount - 1 WHERE user_id = $1 AND card_id = $2", sender_id, card_id)

                    await conn.execute("""
                        INSERT INTO user_cards (user_id, card_id, amount) VALUES ($1, $2, 1)
                        ON CONFLICT(user_id, card_id) DO UPDATE SET amount = user_cards.amount + 1
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
            return await query.answer("❌ Not your /kc view!", show_alert=True)

        await render_kc_view(query, context, page=page, owner_id=target_id)
        await query.answer()
        return

    if data == "claim_cbox":
        box = active_cboxes.get(msg_id)
        if not box:
            return await query.answer("❌ Coin Box expired or removed.", show_alert=True)

        if user.id in box["claimed_users"]:
            return await query.answer("❌ You already claimed from this Box!", show_alert=True)

        if box["remaining"] <= 0:
            return await query.answer("❌ Coin Box is empty!", show_alert=True)

        max_steal = max(1, min(box["remaining"], int(box["total_amount"] * 0.4)))
        stolen_amount = random.randint(1, max_steal) if box["remaining"] > 1 else box["remaining"]

        box["remaining"] -= stolen_amount
        box["claimed_users"][user.id] = {
            "name": user.first_name,
            "got": stolen_amount
        }

        await add_coins(user.id, stolen_amount)
        await query.answer(f"🎉 You claimed {stolen_amount} 🩸 Kachi Coins!", show_alert=True)

        claimed_list = []
        for uid, udata in box["claimed_users"].items():
            claimed_list.append(f"• {get_mention(uid, udata['name'])} — <b>{udata['got']}</b> 🩸")
        
        list_str = "\n".join(claimed_list)

        if box["remaining"] > 0:
            status_str = f"💰 <b>Live Remaining Amount:</b> <code>{box['remaining']}</code> 🩸"
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏴‍☠ Claim", callback_data="claim_cbox")]])
        else:
            status_str = "🎁 <b>Coin Box is empty!</b>"
            markup = None

        text = f"""🎁 <b>Kachi Coin Box!</b> 🩸

{status_str}
👤 <b>Created By:</b> {box['creator']}

📋 <b>Live Claim List:</b>
{list_str}"""

        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
        return

    if data.startswith("spin_"):
        owner_id = int(data.split("_")[1])
        if user.id != owner_id:
            return await query.answer("❌ Not meant for you. Use /kbox yourself.", show_alert=True)

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1", user.id)
            coins = row['coins'] if row else 0

            if coins < 650:
                return await query.answer("❌ Not enough Kachi Coins (650 required).", show_alert=True)

            cards = await conn.fetch("SELECT card_id FROM cards WHERE card_id != 'gemstone'")
            if not cards:
                return await query.answer("❌ No cards in box yet, please wait.", show_alert=True)

            await conn.execute("UPDATE users SET coins = coins - 650 WHERE user_id = $1", user.id)

        await query.answer("🎰 Spinning Card Box...")
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
            return await query.answer("❌ Not your Card List view!", show_alert=True)

        await render_cardlist_page(query, context, page=page, owner_id=owner_id)
        await query.answer()
        return

    if data.startswith("bet_"):
        game = active_games.get(chat_id)
        if not game:
            return await query.answer("❌ This game has finished.", show_alert=True)

        choice = data.replace("bet_", "")
        game["bets"][user.id] = choice
        game["user_names"][user.id] = get_mention(user.id, user.first_name)

        await query.answer("✅ Bet placed!")
        return

    if data == "lb_back":
        original_text = last_results.get(msg_id, "🎗️ 𝗠𝒂𝘁𝗰𝗵 𝗥𝗲𝘀𝘂𝗹𝘁")
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
                    WHERE uc.amount > 0 AND uc.card_id != 'gemstone'
                    GROUP BY u.user_id, u.name
                    ORDER BY card_count DESC
                    LIMIT 10
                """)
                title = "💎 <b>Richest Card Owners (Top 10)</b>"

        if not rows:
            text = f"{title}\n\n<i>No data available yet.</i>"
        else:
            if lb_type == "gp":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — {r['coins']} 🩸Kachi Coin ({r['total_cards']} Cards)" for i, r in enumerate(rows)])
            elif lb_type == "global":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — {r['coins']} 🩸Kachi Coin" for i, r in enumerate(rows)])
            elif lb_type == "cards":
                text = f"{title}\n\n" + "\n".join([f"{i+1}. {get_mention(r['user_id'], r['name'])} — <b>{r['card_count']}</b> Cards" for i, r in enumerate(rows)])

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

    # Admin & Card Admin Commands
    app.add_handler(CommandHandler("game", manual_game_cmd))
    app.add_handler(CommandHandler("cardlist", cardlist_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("c", set_count_cmd))
    app.add_handler(CommandHandler("cbox", cbox_cmd))
    app.add_handler(CommandHandler("glist", glist_cmd))
    app.add_handler(CommandHandler(["g", "r"], media_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("k", admin_coin_cmd))
    app.add_handler(CommandHandler("addadmin", addadmin_cmd))
    app.add_handler(CommandHandler("add", add_card_cmd))
    app.add_handler(CommandHandler("del", del_card_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), message_handler))

    print("🤖 Python Game Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
