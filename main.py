import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from langdetect import detect
import base64
import os
import time
import json

# Cargar variables de entorno
load_dotenv()
CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI') or 'http://localhost:8888/callback'
SCOPE = "playlist-modify-public ugc-image-upload"

# Autenticación con Spotify
@st.cache_resource
def authenticate_spotify():
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE
    ))

def get_playlist_id_from_url(url):
    if "playlist/" in url:
        return url.split("playlist/")[1].split("?")[0]
    return url

def get_playlist_tracks(sp, playlist_id, max_tracks=50):
    tracks = []
    results = sp.playlist_tracks(playlist_id, limit=max_tracks)
    tracks.extend(results['items'])
    while results['next'] and len(tracks) < max_tracks:
        results = sp.next(results)
        tracks.extend(results['items'])
    return tracks[:max_tracks]

def safe_get_artist(sp, artist_id):
    while True:
        try:
            return sp.artist(artist_id)
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get('Retry-After', 1))
                minutes = retry_after // 60
                st.error(f"⚠️ Spotify API rate limit reached. Please try again in {minutes} minute(s).")
                st.stop()
            else:
                raise

def load_cache(filename="artist_genre_cache.json"):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache, filename="artist_genre_cache.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(cache, f)

def get_genres_from_tracks(sp, tracks, artist_filter=None, language_filter=None):
    genre_tracks = {}
    cache = load_cache()
    progress = st.progress(0)

    for idx, track in enumerate(tracks):
        info = track.get('track')
        if not info:
            continue

        artist = info['artists'][0]
        name = artist['name']
        aid = artist['id']

        if artist_filter and artist_filter.lower() not in name.lower():
            continue
        if language_filter:
            try:
                if detect(name) != language_filter:
                    continue
            except:
                pass

        if aid in cache:
            genres = cache[aid]
        else:
            time.sleep(0.2)
            art = safe_get_artist(sp, aid)
            genres = art.get('genres') or ['Unknown']
            cache[aid] = genres

        for genre in genres:
            genre_tracks.setdefault(genre, []).append(info['uri'])

        progress.progress((idx + 1) / len(tracks))

    save_cache(cache)
    return genre_tracks

def create_playlist(sp, user_id, name, uris):
    pl = sp.user_playlist_create(user=user_id, name=name, public=True)
    sp.playlist_add_items(pl['id'], uris)
    return pl['id'], pl['external_urls']['spotify']

def upload_cover_image(sp, playlist_id, image_file):
    encoded_string = base64.b64encode(image_file.read())
    sp.playlist_upload_cover_image(playlist_id, encoded_string)

# Interfaz Streamlit
st.title("🎧 Genrer: Spotify Genre Classifier")

sp = authenticate_spotify()
user_id = sp.current_user()['id']

with st.form("playlist_form"):
    playlist_url = st.text_input("🔗 Spotify playlist URL", "")
    artist_filter = st.text_input("🎤 Artist filter (optional)", "")
    lang_filter = st.text_input("🌍 ISO Language filter (optional, e.g. 'en', 'es')", "")
    submitted = st.form_submit_button("Analyze Genres")

if submitted and playlist_url:
    with st.spinner("🔍 Getting data from Spotify (limit: 50 tracks)..."):
        try:
            playlist_id = get_playlist_id_from_url(playlist_url)
            tracks = get_playlist_tracks(sp, playlist_id, max_tracks=50)
            if not tracks:
                st.warning("No tracks found in this playlist.")
            else:
                genre_tracks = get_genres_from_tracks(sp, tracks, artist_filter, lang_filter)
                st.session_state["genre_tracks"] = genre_tracks
                st.session_state["playlist_id"] = playlist_id
                st.success(f"{len(genre_tracks)} genres found.")
        except spotipy.exceptions.SpotifyException as e:
            st.error(f"Spotify error: {e}")
        except Exception as e:
            st.error(f"Unexpected error: {e}")

# Si ya hay datos, mostrar opciones
if "genre_tracks" in st.session_state:
    genre_tracks = st.session_state["genre_tracks"]

    selected_genres = st.multiselect("🎼 Select genres to create a new playlist",
                                     sorted(genre_tracks.keys()))

    if selected_genres:
        playlist_name = st.text_input("📛 New playlist name", " + ".join(selected_genres)[:100])
        cover_image = st.file_uploader("📷 Cover image (optional, JPG)", type=["jpg", "jpeg"])

        if st.button("🎵 Create playlist"):
            combined_uris = list(set(uri for g in selected_genres for uri in genre_tracks[g]))
            with st.spinner("🎁 Creating playlist..."):
                pl_id, url = create_playlist(sp, user_id, playlist_name, combined_uris)
                if cover_image:
                    upload_cover_image(sp, pl_id, cover_image)
                st.success("Playlist created successfully!")
                st.markdown(f"🔗 [Open in Spotify]({url})")
