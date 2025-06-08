import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from langdetect import detect
import base64
import os
import time
import json
from urllib.parse import urlparse, parse_qs

# Cargar variables de entorno
load_dotenv()
CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
REDIRECT_URI = f"https://{st.runtime.scriptrunner.script_run_context().user_info.username}.streamlit.app"
SCOPE = "playlist-modify-public ugc-image-upload"

TOKEN_INFO_KEY = "token_info"

def get_spotify_auth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE
    )

def authenticate_user():
    auth_manager = get_spotify_auth()
    token_info = st.session_state.get(TOKEN_INFO_KEY)

    if token_info:
        if auth_manager.is_token_expired(token_info):
            token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
            st.session_state[TOKEN_INFO_KEY] = token_info
        return spotipy.Spotify(auth=token_info['access_token'])

    auth_url = auth_manager.get_authorize_url()
    with st.expander("🔐 Autenticación requerida"):
        st.markdown(f"#### Paso 1: [Haz clic aquí para autorizar Spotify]({auth_url})")
        st.markdown("#### Paso 2: Una vez autorizado, serás redirigido. Copia la URL y pégala aquí:")
        redirect_input = st.text_input("🔗 Pega aquí la URL después de autorizar")

        if redirect_input:
            code = parse_qs(urlparse(redirect_input).query).get("code")
            if code:
                token_info = auth_manager.get_access_token(code[0])
                st.session_state[TOKEN_INFO_KEY] = token_info
                st.rerun()
            else:
                st.error("❌ No se encontró el código en la URL.")

    return None

@st.cache_resource
def get_spotify_client():
    return authenticate_user()

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
                st.error(f"⚠️ Límite de uso de la API alcanzado. Intenta de nuevo en {retry_after} segundos.")
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

# --- STREAMLIT UI ---
st.set_page_config(page_title="Genrer", layout="centered")
st.title("🎧 Genrer: Clasifica tu playlist por géneros")

sp = get_spotify_client()
if sp is None:
    st.stop()

try:
    user_id = sp.current_user()['id']
except spotipy.exceptions.SpotifyException as e:
    st.error(f"Error autenticando usuario: {e}")
    st.stop()

with st.form("playlist_form"):
    playlist_url = st.text_input("🔗 URL de tu playlist", "")
    artist_filter = st.text_input("🎤 Filtro por artista (opcional)", "")
    lang_filter = st.text_input("🌍 Filtro de idioma ISO (ej: 'en', 'es')", "")
    submitted = st.form_submit_button("Analizar géneros")

if submitted and playlist_url:
    with st.spinner("🔍 Analizando playlist..."):
        try:
            playlist_id = get_playlist_id_from_url(playlist_url)
            tracks = get_playlist_tracks(sp, playlist_id, max_tracks=50)
            if not tracks:
                st.warning("No se encontraron canciones.")
            else:
                genre_tracks = get_genres_from_tracks(sp, tracks, artist_filter, lang_filter)
                st.session_state["genre_tracks"] = genre_tracks
                st.session_state["playlist_id"] = playlist_id
                st.success(f"{len(genre_tracks)} géneros identificados.")
        except Exception as e:
            st.error(f"❌ Error: {e}")

if "genre_tracks" in st.session_state:
    genre_tracks = st.session_state["genre_tracks"]

    selected_genres = st.multiselect("🎼 Elige géneros para una nueva playlist",
                                     sorted(genre_tracks.keys()))

    if selected_genres:
        playlist_name = st.text_input("📛 Nombre de la nueva playlist", " + ".join(selected_genres)[:100])
        cover_image = st.file_uploader("📷 Imagen de portada (JPG)", type=["jpg", "jpeg"])

        if st.button("🎵 Crear playlist"):
            uris = list(set(uri for g in selected_genres for uri in genre_tracks[g]))
            with st.spinner("🎁 Creando playlist..."):
                pl_id, url = create_playlist(sp, user_id, playlist_name, uris)
                if cover_image:
                    upload_cover_image(sp, pl_id, cover_image)
                st.success("¡Playlist creada con éxito!")
                st.markdown(f"🔗 [Abrir en Spotify]({url})")
