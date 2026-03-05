import re
import hashlib
import requests
import textwrap
from datetime import datetime, timedelta
from info import *
from utils import *
from pyrogram import Client, filters
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ---------- GLOBAL STORAGE ----------
notified_movies = {}
user_reactions = {}
reaction_counts = {}
movie_slugs = {}

media_filter = filters.document | filters.video | filters.audio

# ---------- MEDIA HANDLER ----------
@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    for file_type in ("document", "video", "audio"):
        media = getattr(message, file_type, None)
        if media:
            break
    else:
        return

    media.file_type = file_type
    media.caption = message.caption

    try:
        success, _ = await save_file(bot, media)
    except:
        await save_file(media)
        success = True

    if success:
        await send_movie_update(bot, media.file_name, media.caption)

# ---------- SEND UPDATE ----------
async def send_movie_update(bot, file_name, caption):
    try:
        # 1. Sabse pehle title ko clean karein (Professional Look ke liye)
        clean_title = await get_ultra_clean_title(file_name)
        
        link_slug = await get_smart_link_slug(file_name)
        unique_id = generate_unique_id(link_slug)

        current_time = datetime.now()
        if unique_id in notified_movies:
            if (current_time - notified_movies[unique_id]) < timedelta(days=5):
                return

        notified_movies[unique_id] = current_time
        movie_slugs[unique_id] = link_slug

        # Info extraction
        _, file_year = await extract_info_from_filename(file_name)
        season_info = await get_only_season(file_name)

        # TMDB Search using Clean Title
        tmdb_data = await fetch_tmdb_data(clean_title, file_year)

        if tmdb_data and tmdb_data.get("title"):
            title = tmdb_data.get("title")
            rating = tmdb_data.get("vote_average", "N/A")
            genres = tmdb_data.get("genres", "N/A")
            poster = tmdb_data.get("poster")
            backdrop = tmdb_data.get("backdrop")
            overview = tmdb_data.get("overview", "")
            year = tmdb_data.get("release_date", "")[:4] or file_year
        else:
            title = clean_title
            rating = "N/A"
            genres = "N/A"
            poster = backdrop = None
            overview = ""
            year = file_year

        language = await get_formatted_language(file_name, caption)
        quality = await get_qualities(file_name + " " + (caption or "")) or "HDRip"

        # ----- PROFESSIONAL CAPTION FORMAT -----
        full_caption = f"🎬 <b>{title}</b>\n\n"
        full_caption += f"<b>⭐ Rating:</b> {rating}/10\n"
        full_caption += f"<b>🎭 Genre:</b> {genres}\n"
        full_caption += f"<b>📅 Year:</b> {year}\n"
        full_caption += f"<b>💎 Quality:</b> {quality}\n"
        full_caption += f"<b>🔊 Audio:</b> {language}\n"

        if season_info:
            full_caption += f"<b>📺 Info:</b> {season_info}\n"

        if overview:
            full_caption += f"\n<b>📝 Story:</b> <i>{overview[:150]}...</i>\n"

        full_caption += "\n📥 <b>Click the buttons below to get files</b>"

        # ----- REACTION SYSTEM -----
        if unique_id not in reaction_counts:
            reaction_counts[unique_id] = {"❤️": 0, "👍": 0, "👎": 0, "🔥": 0}
            user_reactions[unique_id] = {}

        buttons = [[
            InlineKeyboardButton(f"❤️ {reaction_counts[unique_id]['❤️']}", callback_data=f"r_{unique_id}_h"),
            InlineKeyboardButton(f"👍 {reaction_counts[unique_id]['👍']}", callback_data=f"r_{unique_id}_l"),
            InlineKeyboardButton(f"👎 {reaction_counts[unique_id]['👎']}", callback_data=f"r_{unique_id}_d"),
            InlineKeyboardButton(f"🔥 {reaction_counts[unique_id]['🔥']}", callback_data=f"r_{unique_id}_f")
        ],[
            InlineKeyboardButton("✨ Join Movie Request Group", url="https://t.me/Rk2x_Request")
        ]]

        image = backdrop if backdrop else poster

        if image:
            await bot.send_photo(MOVIE_UPDATE_CHANNEL, image, caption=full_caption, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await bot.send_message(MOVIE_UPDATE_CHANNEL, full_caption, reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        print(f"Update Error: {e}")

# ---------- REACTION HANDLER ----------
@Client.on_callback_query(filters.regex(r"^r_"))
async def reaction_handler(client, query):
    data = query.data.split("_")
    unique_id, code = data[1], data[2]
    user_id = query.from_user.id
    emoji_map = {"h": "❤️", "l": "👍", "d": "👎", "f": "🔥"}
    emoji = emoji_map[code]

    if user_id in user_reactions.get(unique_id, {}):
        if user_reactions[unique_id][user_id] == emoji:
            return await query.answer("Already reacted!", show_alert=False)
        old_emoji = user_reactions[unique_id][user_id]
        reaction_counts[unique_id][old_emoji] -= 1

    user_reactions.setdefault(unique_id, {})[user_id] = emoji
    reaction_counts[unique_id][emoji] += 1

    buttons = [[
        InlineKeyboardButton(f"❤️ {reaction_counts[unique_id]['❤️']}", callback_data=f"r_{unique_id}_h"),
        InlineKeyboardButton(f"👍 {reaction_counts[unique_id]['👍']}", callback_data=f"r_{unique_id}_l"),
        InlineKeyboardButton(f"👎 {reaction_counts[unique_id]['👎']}", callback_data=f"r_{unique_id}_d"),
        InlineKeyboardButton(f"🔥 {reaction_counts[unique_id]['🔥']}", callback_data=f"r_{unique_id}_f")
    ],[
        InlineKeyboardButton("✨ Join Movie Request Group", url="https://t.me/Rk2x_Request")
    ]]
    await query.message.edit_reply_markup(InlineKeyboardMarkup(buttons))

# ---------- HELPERS (CLEANING LOGIC) ----------
async def get_ultra_clean_title(filename):
    """Filename se quality, year, group sab hata kar clean title deta hai"""
    name = re.sub(r'\.[a-zA-Z0-9]+$', '', filename) # Remove extension
    # Junk patterns to remove
    junk = [
        r'\d{3,4}p', r'bluray', r'web-?dl', r'webrip', r'hdrip', r'x264', r'x265', 
        r'hevc', r'10bit', r'dual[- ]audio', r'hindi', r'english', r'esub', r'sub', 
        r'clean', r'hc', r'aac', r'dts', r'dd5\.1', r'upscaled', r'confirm'
    ]
    for pattern in junk:
        name = re.sub(pattern, '', name, flags=re.I)
    
    # Symbols ko space se badlein
    name = re.sub(r'[._\-\(\)\[\]]', ' ', name)
    
    # Agar year hai toh uske aage ka sab delete
    match = re.search(r'\b(19|20)\d{2}\b', name)
    if match:
        name = name[:match.start()]
    
    return " ".join(name.split()).title()

async def extract_info_from_filename(filename):
    clean = re.sub(r'\.\w+$', '', filename)
    words = re.sub(r'[._\-]', ' ', clean).split()
    title, year = [], "N/A"
    for word in words:
        if re.match(r'^(19|20)\d{2}$', word):
            year = word
            break
        title.append(word)
    return " ".join(title), year

async def get_only_season(text):
    match = re.search(r'(?:S|Season)\s*(\d+)', text, re.I)
    return f"Season {match.group(1)}" if match else None

async def get_smart_link_slug(filename):
    clean = re.sub(r'[^a-zA-Z0-9 ]', '', filename).split()[:4]
    return "-".join(clean)

async def get_formatted_language(filename, caption):
    text = (filename + " " + (caption or "")).lower()
    langs = []
    if "hindi" in text: langs.append("Hindi")
    if "english" in text: langs.append("English")
    return " | ".join(langs) if langs else "Hindi"

async def get_qualities(text):
    text = text.lower()
    if "bluray" in text: return "BluRay"
    if "web" in text: return "WEBRip"
    if "hdrip" in text: return "HDRip"
    return "WEB-DL"

# ---------- TMDB ----------
async def fetch_tmdb_data(query, year=None):
    try:
        params = {"api_key": TMDB_API, "query": query}
        if year and year != "N/A":
            params["year"] = year
        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params).json()
        if not r.get("results"):
            return {}
        movie = r["results"][0]
        details = requests.get(f"https://api.themoviedb.org/3/movie/{movie['id']}?api_key={TMDB_API}").json()
        return {
            "title": details.get("title"),
            "overview": details.get("overview"),
            "vote_average": round(details.get("vote_average", 0), 1),
            "genres": ", ".join([g["name"] for g in details.get("genres", [])][:2]),
            "release_date": details.get("release_date"),
            "poster": f"https://image.tmdb.org/t/p/w500{details.get('poster_path')}" if details.get("poster_path") else None,
            "backdrop": f"https://image.tmdb.org/t/p/w780{details.get('backdrop_path')}" if details.get("backdrop_path") else None
        }
    except: return {}

def generate_unique_id(name):
    return hashlib.md5(name.encode()).hexdigest()[:5]
