import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from langdetect import detect
import base64
import os
import json
import time
import pandas as pd
import altair as alt
import numpy as np

# Traducción macro géneros
MACRO_GENRES_ES = {
    "Hip-Hop": "Hip-Hop",
    "Electronic": "Electrónica",
    "Pop": "Pop",
    "Rock": "Rock",
    "Classical": "Clásica",
    "Jazz": "Jazz"
}

st.set_page_config(page_title="🎧 Genrer", page_icon="🎵")
st.title("🎧 Genrer: Spotify Genre Classifier")

load_dotenv()
CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SCOPE = "playlist-read-private user-read-private"
TOKEN_INFO_KEY = "token_info"

MACRO_GENRES = {
    "rap": "Hip-Hop", "hip hop": "Hip-Hop", "trap": "Hip-Hop",
    "house": "Electronic", "techno": "Electronic", "electro": "Electronic",
    "pop": "Pop", "rock": "Rock", "indie": "Rock",
    "classical": "Classical", "jazz": "Jazz"
}

COLOR_PALETTE = {
    "Hip-Hop": "#1f77b4",
    "Electronic": "#ff7f0e",
    "Pop": "#2ca02c",
    "Rock": "#d62728",
    "Classical": "#9467bd",
    "Jazz": "#8c564b"
}

def loading_animation(phrases, progress, wait=5):
    text_placeholder = st.empty()
    n = len(phrases)
    for i, phrase in enumerate(phrases):
        emoji = "⏳" if i % 2 == 0 else "⌛"
        text_placeholder.markdown(f"{emoji} {phrase}")
        progress.progress((i + 1) / n)
        time.sleep(wait)
    text_placeholder.empty()

def group_genre(genre):
    genre_lower = genre.lower()
    for key in MACRO_GENRES:
        if key in genre_lower:
            return MACRO_GENRES[key]
    return genre

def get_spotify_client():
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=".cache",
        show_dialog=False
    )
    token_info = st.session_state.get(TOKEN_INFO_KEY)
    if token_info:
        if auth_manager.is_token_expired(token_info):
            try:
                token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
                st.session_state[TOKEN_INFO_KEY] = token_info
            except Exception:
                st.warning("🔄 No se pudo refrescar el token, reautenticando...")
                st.session_state.pop(TOKEN_INFO_KEY, None)
                return None
        return spotipy.Spotify(auth=token_info['access_token'])
    try:
        token_info = auth_manager.get_cached_token()
        if token_info:
            st.session_state[TOKEN_INFO_KEY] = token_info
            return spotipy.Spotify(auth=token_info['access_token'])
    except Exception:
        pass
    auth_url = auth_manager.get_authorize_url()
    with st.expander("🔐 Autorizar acceso a Spotify", expanded=True):
        st.markdown(f"""
            <div style="padding:10px;border-radius:8px;color:#1DB954;">
                <b>1. Haz clic para autorizar Spotify:</b><br>
                <a href="{auth_url}" target="_blank">
                    <button style="background-color:#1DB954;color:white;padding:8px 16px;border:none;border-radius:4px;cursor:pointer;">
                        Autorizar en Spotify
                    </button>
                </a><br><br>
                <b>2. Pega la URL completa de redirección:</b>
            </div>
        """, unsafe_allow_html=True)
        redirect_response = st.text_input(
            "🔗 URL de redirección",
            help="¡Copia y pega aquí la URL completa tras autorizar en Spotify!"
        )
        if redirect_response:
            code = auth_manager.parse_response_code(redirect_response)
            if code:
                try:
                    token_info = auth_manager.get_access_token(code, as_dict=True)
                    st.session_state[TOKEN_INFO_KEY] = token_info
                    st.success("✅ Autenticación completada. Recargando...")
                    st.experimental_rerun()
                except Exception as e:
                    st.error(f"❌ Error al obtener token: {e}")
            else:
                st.error("⚠️ No se detectó un código válido en la URL")
    return None

if st.sidebar.button("Cerrar sesión", key="logout_btn", help="Cierra tu sesión y borra el token"):
    st.session_state.pop(TOKEN_INFO_KEY, None)
    if os.path.exists(".cache"):
        os.remove(".cache")
    cache_file = "artist_genre_cache.json"
    if os.path.exists(cache_file):
        os.remove(cache_file)
    st.success("🔒 Sesión cerrada")
    st.experimental_rerun()

def get_playlist_id_from_url(url):
    return url.split("playlist/")[1].split("?")[0] if "playlist/" in url else url

def get_playlist_tracks(sp, playlist_id, max_tracks=None):
    tracks = []
    results = sp.playlist_tracks(playlist_id, limit=100)
    tracks.extend(results['items'])
    while results['next'] and (max_tracks is None or len(tracks) < max_tracks):
        results = sp.next(results)
        tracks.extend(results['items'])
    return tracks if max_tracks is None else tracks[:max_tracks]

def safe_get_artist(sp, artist_id):
    while True:
        try:
            return sp.artist(artist_id)
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                retry = int(e.headers.get('Retry-After', 1))
                st.warning(f"Spotify rate limit: esperando {retry} segundos")
                time.sleep(retry)
            else:
                raise

def load_cache(filename="artist_genre_cache.json"):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_cache(cache, filename="artist_genre_cache.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(cache, f)

def get_genres_from_tracks(sp, tracks, artist_filter=None, language_filter=None, progress=None):
    genre_tracks = {}
    cache = load_cache()
    total = len(tracks)
    for idx, track in enumerate(tracks):
        info = track.get('track')
        if not info:
            continue
        name = info['artists'][0]['name']
        aid = info['artists'][0]['id']
        if artist_filter and artist_filter.lower() not in name.lower():
            continue
        if language_filter:
            try:
                if detect(name) != language_filter:
                    continue
            except:
                pass
        genres = cache.get(aid)
        if not genres:
            time.sleep(0.2)
            art = safe_get_artist(sp, aid)
            genres = art.get('genres') or ['Unknown']
            cache[aid] = genres
        for g in genres:
            genre_tracks.setdefault(g, []).append(info)
        if progress is not None and total > 0:
            progress.progress((idx + 1) / total)
    save_cache(cache)
    return genre_tracks

sp = get_spotify_client()
if not sp:
    st.stop()

try:
    user = sp.current_user()
    st.sidebar.write(f"👤 Usuario: **{user['display_name']}**")
except:
    st.error("Autenticación fallida")
    st.stop()

language_options = {
    "Todos": None, "Español": "es", "Inglés": "en", "Francés": "fr",
    "Alemán": "de", "Italiano": "it", "Portugués": "pt",
    "Japonés": "ja", "Coreano": "ko", "Chino": "zh-cn"
}

with st.form("playlist_form"):
    playlist_url = st.text_input("🎼 URL de playlist", help="Pega la URL de la playlist de Spotify")
    artist_filter = st.text_input("🎤 Filtrar artista (opcional)", help="Filtra por nombre de artista")
    sel_lang = st.selectbox("🌍 Idioma artista", list(language_options.keys()),
                            help="Idioma detectado en el nombre del artista")
    min_dur = st.slider("⏱️ Duración mínima (s)", 0, 600, 0, help="Descarta canciones más cortas")
    max_dur = st.slider("⏱️ Duración máxima (s)", 0, 600, 600, help="Descarta canciones más largas")
    min_pop = st.slider("⭐ Popularidad mínima", 0, 100, 0, help="Descarta canciones poco populares")
    all_tracks = st.checkbox("📥 Obtener todas las canciones", value=True, help="Si está marcado, no hay límite")
    submitted = st.form_submit_button("Analizar géneros")

if submitted and playlist_url:
    phrases = [
        "Porque tu playlist merece un doctorado musical...",
        "Revisando tu colección de éxitos y fracasos...",
        "Analizando cada beat con lupa de científico loco...",
        "Midiendo la calidad de tu gusto (¿valdrá la pena?)...",
        "Buscando patrones en tu ecléctica selección...",
    ]

    progress = st.progress(0)

    loading_animation(phrases, progress, wait=3)

    playlist_id = get_playlist_id_from_url(playlist_url)
    max_tracks = None if all_tracks else 50
    tracks = get_playlist_tracks(sp, playlist_id, max_tracks)

    filtered_tracks = []
    for t in tracks:
        info = t.get('track')
        if not info:
            continue
        dur_ms = info['duration_ms']
        pop = info['popularity']
        if dur_ms < min_dur * 1000 or dur_ms > max_dur * 1000 or pop < min_pop:
            continue
        filtered_tracks.append(t)

    genre_map = {}
    artist_genres_cache = load_cache()
    rows = []

    for t in filtered_tracks:
        info = t.get('track')
        if not info:
            continue
        track_name = info['name']
        popularity = info.get('popularity', np.nan)
        duration_sec = int(info.get('duration_ms', 0) / 1000)
        artists_names = ", ".join([a['name'] for a in info['artists']])
        main_artist_id = info['artists'][0]['id']

        # Obtener género principal del artista
        if main_artist_id in artist_genres_cache:
            genres = artist_genres_cache[main_artist_id]
        else:
            art = safe_get_artist(sp, main_artist_id)
            genres = art.get('genres') or ['Unknown']
            artist_genres_cache[main_artist_id] = genres

        macro_genre = "Desconocido"
        genre = "Desconocido"
        for g in genres:
            mg = group_genre(g)
            if mg in MACRO_GENRES_ES:
                macro_genre = mg
                genre = g
                break

        rows.append({
            "Canción": track_name,
            "Artistas": artists_names,
            "Popularidad": popularity,
            "Duración (s)": duration_sec,
            "Género": genre,
            "Macro-género": MACRO_GENRES_ES.get(macro_genre, macro_genre)
        })

    save_cache(artist_genres_cache)

    df = pd.DataFrame(rows)

    if df.empty:
        st.warning("No hay datos para mostrar.")
    else:
        with st.expander("📊 Detalles, estadísticas y gráficos", expanded=True):
            st.dataframe(df)

            # Gráfico 1: Número de canciones por macro-género
            count_data = df.groupby("Macro-género").size().reset_index(name="Cantidad")
            chart1 = alt.Chart(count_data).mark_bar().encode(
                x=alt.X("Macro-género", sort="-y", title="Macro-género"),
                y=alt.Y("Cantidad", title="Número de canciones"),
                color=alt.Color("Macro-género", scale=alt.Scale(domain=list(COLOR_PALETTE.keys()), range=list(COLOR_PALETTE.values()))),
                tooltip=["Macro-género", "Cantidad"]
            ).properties(title="Número de canciones por Macro-género")

            # Gráfico 2: Popularidad media por macro-género
            pop_data = df.groupby("Macro-género")["Popularidad"].mean().reset_index()
            chart2 = alt.Chart(pop_data).mark_bar().encode(
                x=alt.X("Macro-género", sort="-y", title="Macro-género"),
                y=alt.Y("Popularidad", title="Popularidad media"),
                color=alt.Color("Macro-género", scale=alt.Scale(domain=list(COLOR_PALETTE.keys()), range=list(COLOR_PALETTE.values()))),
                tooltip=["Macro-género", alt.Tooltip("Popularidad", format=".2f")]
            ).properties(title="Popularidad media por Macro-género")

            # Gráfico 3: Duración media por macro-género
            dur_data = df.groupby("Macro-género")["Duración (s)"].mean().reset_index()
            chart3 = alt.Chart(dur_data).mark_bar().encode(
                x=alt.X("Macro-género", sort="-y", title="Macro-género"),
                y=alt.Y("Duración (s)", title="Duración media (segundos)"),
                color=alt.Color("Macro-género", scale=alt.Scale(domain=list(COLOR_PALETTE.keys()), range=list(COLOR_PALETTE.values()))),
                tooltip=["Macro-género", alt.Tooltip("Duración (s)", format=".2f")]
            ).properties(title="Duración media por Macro-género")

            st.altair_chart(chart1, use_container_width=True)
            st.altair_chart(chart2, use_container_width=True)
            st.altair_chart(chart3, use_container_width=True)
