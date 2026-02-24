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
        link_slug = await get_smart_link_slug(file_name)
        unique_id = generate_unique_id(link_slug)

        current_time = datetime.now()
        if unique_id in notified_movies:
            if (current_time - notified_movies[unique_id]) < timedelta(days=5):
                return

        notified_movies[unique_id] = current_time
        movie_slugs[unique_id] = link_slug

        file_title, file_year = await extract_info_from_filename(file_name)
        season_info = await get_only_season(file_name)

        search_query = await clean_search_query(file_title)
        tmdb_data = await fetch_tmdb_data(search_query, file_year)

        # ----- DATA -----
        if tmdb_data:
            title = tmdb_data.get("title")
            rating = tmdb_data.get("vote_average", 0)
            genres = tmdb_data.get("genres", "")
            poster = tmdb_data.get("poster")
            backdrop = tmdb_data.get("backdrop")
            overview = tmdb_data.get("overview", "")
            year = tmdb_data.get("release_date", "")[:4]
        else:
            title = file_title
            rating = 0
            genres = ""
            poster = None
            backdrop = None
            overview = ""
            year = file_year

        language = await get_formatted_language(file_name, caption)
        quality = await get_qualities(file_name + " " + (caption or "")) or "HDRip"

        # ----- SMALL CAPTION -----
        story = ""
        if overview:
            wrapped = textwrap.wrap(overview[:120] + "...", width=35)
            for line in wrapped:
                story += f"{line}\n"

        full_caption = f"""
🎬 <b>{title}</b>

⭐ {rating}/10 | 🎭 {genres}
📅 {year}
💎 {quality}
🔊 {language}
"""

        if season_info:
            full_caption += f"📺 {season_info}\n"

        if story:
            full_caption += f"\n📝 {story}"

        full_caption += "\n⬇️ <b>Get Files Below</b> ⬇️"

        # ----- REACTION -----
        if unique_id not in reaction_counts:
            reaction_counts[unique_id] = {"❤️": 0, "👍": 0, "👎": 0, "🔥": 0}
            user_reactions[unique_id] = {}

        buttons = [[
            InlineKeyboardButton(f"❤️ {reaction_counts[unique_id]['❤️']}", callback_data=f"r_{unique_id}_h"),
            InlineKeyboardButton(f"👍 {reaction_counts[unique_id]['👍']}", callback_data=f"r_{unique_id}_l"),
            InlineKeyboardButton(f"👎 {reaction_counts[unique_id]['👎']}", callback_data=f"r_{unique_id}_d"),
            InlineKeyboardButton(f"🔥 {reaction_counts[unique_id]['🔥']}", callback_data=f"r_{unique_id}_f")
        ],[
            InlineKeyboardButton("Movie Request group", url="https://t.me/Rk2x_Request")
        ]]

        image = backdrop if backdrop else poster

        if image:
            await bot.send_photo(
                MOVIE_UPDATE_CHANNEL,
                image,
                caption=full_caption,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await bot.send_message(
                MOVIE_UPDATE_CHANNEL,
                full_caption,
                reply_markup=InlineKeyboardMarkup(buttons)
            )

    except Exception as e:
        print("Update Error:", e)


# ---------- REACTION ----------
@Client.on_callback_query(filters.regex(r"^r_"))
async def reaction_handler(client, query):

    data = query.data.split("_")
    unique_id = data[1]
    code = data[2]
    user_id = query.from_user.id

    emoji_map = {"h": "❤️", "l": "👍", "d": "👎", "f": "🔥"}
    emoji = emoji_map[code]

    if user_id in user_reactions[unique_id]:
        old = user_reactions[unique_id][user_id]
        if old == emoji:
            return await query.answer("Already reacted")
        reaction_counts[unique_id][old] -= 1

    user_reactions[unique_id][user_id] = emoji
    reaction_counts[unique_id][emoji] += 1

    buttons = [[
        InlineKeyboardButton(f"❤️ {reaction_counts[unique_id]['❤️']}", callback_data=f"r_{unique_id}_h"),
        InlineKeyboardButton(f"👍 {reaction_counts[unique_id]['👍']}", callback_data=f"r_{unique_id}_l"),
        InlineKeyboardButton(f"👎 {reaction_counts[unique_id]['👎']}", callback_data=f"r_{unique_id}_d"),
        InlineKeyboardButton(f"🔥 {reaction_counts[unique_id]['🔥']}", callback_data=f"r_{unique_id}_f")
    ],[
        InlineKeyboardButton("Movie Request Group", url="https://t.me/Rk2x_Request")
    ]]

    await query.message.edit_reply_markup(InlineKeyboardMarkup(buttons))


# ---------- HELPERS ----------
async def extract_info_from_filename(filename):
    clean = re.sub(r'\.\w+$', '', filename)
    words = re.sub(r'[._\-]', ' ', clean).split()

    title = []
    year = "N/A"

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
    clean = re.sub(r'\.\w+$', '', filename)
    words = re.sub(r'[^a-zA-Z0-9 ]', '', clean).split()[:3]
    return "-".join(words)


async def clean_search_query(text):
    return re.sub(r'(S\d+|Season\s*\d+)', '', text, flags=re.I).strip()


async def get_formatted_language(filename, caption):
    text = (filename + " " + (caption or "")).lower()
    if "hindi" in text:
        return "Hindi"
    if "english" in text:
        return "English"
    return "Unknown"


async def get_qualities(text):
    text = text.lower()
    if "bluray" in text:
        return "BluRay"
    if "web" in text:
        return "WEBRip"
    if "hdrip" in text:
        return "HDRip"
    return None


# ---------- TMDB ----------
async def fetch_tmdb_data(query, year=None):

    try:
        params = {"api_key": TMDB_API, "query": query}
        if year != "N/A":
            params["year"] = year

        r = requests.get("https://api.themoviedb.org/3/search/movie", params=params).json()
        if not r["results"]:
            return {}

        movie = r["results"][0]
        movie_id = movie["id"]

        details = requests.get(
            f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API}"
        ).json()

        poster = details.get("poster_path")
        backdrop = details.get("backdrop_path")

        return {
            "title": details.get("title"),
            "overview": details.get("overview"),
            "vote_average": round(details.get("vote_average", 0), 1),
            "genres": ", ".join([g["name"] for g in details.get("genres", [])][:2]),
            "release_date": details.get("release_date"),
            "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
            "backdrop": f"https://image.tmdb.org/t/p/w780{backdrop}" if backdrop else None
        }

    except:
        return {}


def generate_unique_id(name):
    return hashlib.md5(name.encode()).hexdigest()[:5]
