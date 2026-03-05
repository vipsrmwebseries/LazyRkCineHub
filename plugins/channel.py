import re
import hashlib
import asyncio
import aiohttp
from datetime import datetime, timedelta
from collections import defaultdict
from info import *
from utils import *
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.ia_filterdb import save_file, unpack_new_file_id

# ---------- CONFIGURATION ----------
POST_DELAY = 15  # 15 सेकंड इंतज़ार करेगा ताकि सारे एपिसोड्स एक साथ ग्रुप हो सकें
DEFAULT_POSTER = "https://graph.org/file/919c052667ea70e534958-68202ea1b8cf2155ee.jpg"
CAPTION_LANGUAGES = ["Hindi", "English", "Tamil", "Telugu", "Kannada", "Malayalam", "Bengali", "Bhojpuri"]

# Global Storage for Grouping
movie_queue = defaultdict(list)
processing_titles = set()
notified_ids = set()

media_filter = filters.document | filters.video | filters.audio

# ---------- MEDIA HANDLER ----------
@Client.on_message(filters.chat(CHANNELS) & media_filter)
async def media(bot, message):
    media_obj = getattr(message, message.media.value, None)
    if not media_obj: return

    # Save to Database
    try:
        await save_file(media_obj)
    except:
        pass

    # Grouping Logic
    file_name = media_obj.file_name
    clean_title, is_series = await get_clean_title_advanced(file_name)
    
    # Unique Key for Grouping (Title + Year/Season)
    group_key = f"{clean_title}_{is_series}"
    
    file_id, _ = unpack_new_file_id(media_obj.file_id)
    quality = await get_qualities(file_name + " " + (message.caption or ""))
    size = format_file_size(media_obj.file_size)
    
    movie_queue[group_key].append({
        "file_id": file_id,
        "quality": quality,
        "size": size,
        "file_name": file_name,
        "caption": message.caption or ""
    })

    if group_key in processing_titles:
        return

    processing_titles.add(group_key)
    await asyncio.sleep(POST_DELAY) # इंतज़ार करें ताकि एक ही सीरीज के सारे फाइल्स जमा हो जाएं
    
    if group_key in movie_queue:
        await send_professional_update(bot, clean_title, is_series, movie_queue[group_key])
        del movie_queue[group_key]
    
    processing_titles.remove(group_key)

# ---------- SEND UPDATE ----------
async def send_professional_update(bot, clean_title, is_series, files):
    try:
        # Dual Metadata Fetch (TMDB + IMDb)
        meta = await fetch_dual_metadata(clean_title)
        
        title = meta.get("title", clean_title)
        rating = meta.get("rating", "7.5")
        genres = meta.get("genres", "Action, Adventure")
        year = meta.get("year", "2024")
        overview = meta.get("overview", "")
        image = meta.get("backdrop") or meta.get("poster") or DEFAULT_POSTER
        
        kind = "SERIES" if is_series else "MOVIE"
        
        # Language detection from first file
        language = await get_formatted_lang(files[0]['file_name'], files[0]['caption'])

        # Generate Link Text (Grouping Episodes/Qualities)
        link_text = ""
        if is_series:
            # Series के लिए Episode wise links
            ep_dict = defaultdict(list)
            for f in files:
                ep_match = re.search(r'S(\d+)E(\d+)', f['file_name'], re.I)
                ep_label = f"S{ep_match.group(1)}E{ep_match.group(2)}" if ep_match else "Batch"
                ep_dict[ep_label].append(f)
            
            for ep, f_list in sorted(ep_dict.items()):
                links = [f"<a href='https://t.me/{temp.U_NAME}?start=file_0_{f['file_id']}'>{f['quality']}</a>" for f in f_list]
                link_text += f"📦 <b>{ep}</b> : {' | '.join(links)}\n"
        else:
            # Movie के लिए Quality wise links
            for f in files:
                link_text += f"📦 <b>{f['quality']}</b> : <a href='https://t.me/{temp.U_NAME}?start=file_0_{f['file_id']}'>{f['size']}</a>\n"

        # Caption Formatting
        full_caption = (
            f"<blockquote><b>NEW {kind} ADDED ✅</b></blockquote>\n\n"
            f"<b>📝 Tɪᴛʟᴇ :</b> <code>{title}</code>\n"
            f"<b>⭐ Rᴀᴛɪɴɢ :</b> <code>{rating}/10</code>\n"
            f"<b>🎭 Gᴇɴʀᴇ :</b> <code>{genres}</code>\n"
            f"<b>📟 Yᴇᴀʀ :</b> <code>{year}</code>\n"
            f"<b>🎥 Aᴜᴅɪᴏ :</b> <code>{language}</code>\n\n"
            f"{link_text}\n"
            f"<blockquote><b>⚡ Powered by @RkCineHub</b></blockquote>"
        )

        buttons = [[InlineKeyboardButton("🔎 Tap to Search", url="https://t.me/Rk2x_Request")]]

        await bot.send_photo(
            MOVIE_UPDATE_CHANNEL,
            photo=image,
            caption=full_caption,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
            has_spoiler=True
        )

    except Exception as e:
        print(f"Update Error: {e}")

# ---------- DATA ENGINES ----------
async def fetch_dual_metadata(query):
    meta = {}
    # TMDB Search (Priority for Images)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API}&query={query}") as res:
                data = await res.json()
                if data.get("results"):
                    res = data["results"][0]
                    m_type = res['media_type']
                    async with session.get(f"https://api.themoviedb.org/3/{m_type}/{res['id']}?api_key={TMDB_API}") as det:
                        d = await det.json()
                        meta = {
                            "title": d.get("title") or d.get("name"),
                            "rating": str(round(d.get("vote_average", 0), 1)),
                            "genres": ", ".join([g["name"] for g in d.get("genres", [])[:2]]),
                            "year": (d.get("release_date") or d.get("first_air_date") or "2024")[:4],
                            "overview": d.get("overview", ""),
                            "poster": f"https://image.tmdb.org/t/p/w500{d.get('poster_path')}" if d.get('poster_path') else None,
                            "backdrop": f"https://image.tmdb.org/t/p/w1280{d.get('backdrop_path')}" if d.get('backdrop_path') else None
                        }
    except: pass

    # IMDb Fallback (OMDb) if rating is 0 or title not found
    if not meta.get("title") or meta.get("rating") == "0.0":
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={query}") as res:
                    d = await res.json()
                    if d.get("Response") == "True":
                        meta["title"] = d.get("Title")
                        meta["rating"] = d.get("imdbRating")
                        meta["genres"] = d.get("Genre")
                        meta["year"] = d.get("Year")
                        if not meta.get("poster"): meta["poster"] = d.get("Poster")
        except: pass
    return meta

# ---------- HELPERS ----------
async def get_clean_title_advanced(name):
    name = re.sub(r'http\S+|@\w+|#\w+', '', name).lower()
    is_series = bool(re.search(r's\d+|season|ep\s*\d+', name, re.I))
    # Junk Cleaning
    name = re.sub(r'\d{3,4}p|bluray|web-?dl|hdrip|hevc|x264|x265|dual|hindi|english|esub|sub|\.', ' ', name)
    name = re.sub(r'[._\-\(\)\[\]]', ' ', name)
    # Extract Title before Year
    match = re.search(r'\b(19|20)\d{2}\b', name)
    if match: name = name[:match.start()]
    return " ".join(name.split()).title(), is_series

async def get_formatted_lang(filename, caption):
    text = (filename + " " + caption).lower()
    langs = [l for l in CAPTION_LANGUAGES if l.lower() in text]
    return " | ".join(langs) if langs else "Hindi"

async def get_qualities(text):
    for q in ["2160p", "1080p", "720p", "480p", "HDCAM"]:
        if q.lower() in text.lower(): return q
    return "HDRip"

def format_file_size(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024: return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"
