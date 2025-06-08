import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from langdetect import detect
import base64
import os
import json
import time

# Cargar variables de entorno
load_dotenv()
CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SCOPE = "playlist-modify-public ugc-image-upload"

TOKEN_INFO_KEY = "token_info"

# --- Autenticación manual con ventana modal ---
def authenticate_user():
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=".cache"
    )

    token_info = st.session_state.get(TOKEN_INFO_KEY)
    if token_info:
        if auth_manager.is_token_expired(token_info):
            token_info = auth_manager.refresh_access_token(token_info["refresh_token"])
            st.session_state[TOKEN_INFO_KEY] = token_info
        return spotipy.Spotify(auth=token_info["access_token"])

    with st.expander("🔐 Autorizar acceso a Spotify", expanded=True):
        auth_url = auth_manager.get_authorize_url()
        st.markdown(
            f"""
            <div style="background-color:#f9f9f9;padding:10px;border-radius:8px">
            <strong>1. Haz clic en el botón para autorizar:</strong><br>
            <a href="{auth_url}" target="_blank">
            <button style="background-color:#1DB954;color:white;border:none;padding:8px 16px;border-radius:5px;">
                Autorizar en Spotify
            </button></a><br><br>
            <strong>2. Después, pega aquí la URL a la que fuiste redirigido:</strong>
            </div>
            """, unsafe_allow_html=True
        )
        redirect_input = st.text_input("🔗 Pega aquí la URL después de autorizar")

        if redirect_input:
            code = auth_manager.parse_response_code(redirect_input)
            if code:
                token_info = auth_manager.get_access_token(code)
                st.session_state[TOKEN_INFO_KEY] = token_info
                st.success("✅ Autenticado con éxito, puedes continuar")
                return spotipy.Spotify(auth=token_info["access_token"])
            else:
                st.error("⚠️ No se pudo extraer el código de la URL. Revisa que esté completa.")
    return None

# --- Spotify Helpers ---
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
                st.error(f"⚠️ Spotify rate limit reached. Wait {retry_after} seconds.")
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
    encoded = base64.b64encode(image_file.read())
    sp.playlist_upload_cover_image(playlist_id, encoded)

# --- Streamlit UI ---
st.set_page_config(page_title="🎧 Genrer", page_icon="🎵")
st.title("🎧 Genrer: Spotify Genre Classifier")

sp = authenticate_user()
if not sp:
    st.stop()

try:
    user_id = sp.current_user()["id"]
except spotipy.exceptions.SpotifyException as e:
    st.error(f"Autenticación fallida: {e}")
    st.stop()

with st.form("playlist_form"):
    playlist_url = st.text_input("🎼 URL de la playlist de Spotify")
    artist_filter = st.text_input("🎤 Filtrar por artista (opcional)")
    lang_filter = st.text_input("🌍 Filtrar idioma ISO (opcional, ej: 'en', 'es')")
    submitted = st.form_submit_button("Analizar géneros")

if submitted and playlist_url:
    with st.spinner("🔍 Obteniendo canciones de Spotify..."):
        try:
            playlist_id = get_playlist_id_from_url(playlist_url)
            tracks = get_playlist_tracks(sp, playlist_id, max_tracks=50)
            if not tracks:
                st.warning("No se encontraron canciones.")
            else:
                genres = get_genres_from_tracks(sp, tracks, artist_filter, lang_filter)
                st.session_state["genres"] = genres
                st.success(f"Géneros encontrados: {len(genres)}")
        except Exception as e:
            st.error(f"Error: {e}")

if "genres" in st.session_state:
    genres = st.session_state["genres"]
    selected = st.multiselect("🎧 Selecciona géneros para nueva playlist", sorted(genres.keys()))
    if selected:
        name = st.text_input("📛 Nombre de la nueva playlist", " + ".join(selected)[:100])
        cover = st.file_uploader("📷 Imagen de portada (opcional, JPG)", type=["jpg", "jpeg"])
        if st.button("🎵 Crear playlist"):
            uris = list(set(uri for g in selected for uri in genres[g]))
            with st.spinner("🎁 Creando playlist..."):
                pl_id, url = create_playlist(sp, user_id, name, uris)
                if cover:
                    upload_cover_image(sp, pl_id, cover)
                st.success("✅ Playlist creada")
                st.markdown(f"[🔗 Abrir en Spotify]({url})")
