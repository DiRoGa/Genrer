import numpy as np
import pandas as pd
import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from langdetect import detect
import base64
import os
import json
import time
import altair as alt

# --- Cargar credenciales ---
load_dotenv()
CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SCOPE = "playlist-modify-public ugc-image-upload"
TOKEN_INFO_KEY = "token_info"

# --- Autenticación Spotify ---
def get_spotify_client():
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=".cache"
    )

    token_info = st.session_state.get(TOKEN_INFO_KEY)

    if token_info and not auth_manager.is_token_expired(token_info):
        return spotipy.Spotify(auth=token_info['access_token'])

    if not token_info:
        token_info = auth_manager.get_cached_token()
        if token_info:
            st.session_state[TOKEN_INFO_KEY] = token_info
            return spotipy.Spotify(auth=token_info['access_token'])

    # Solicitar autenticación manual
    auth_url = auth_manager.get_authorize_url()
    with st.expander("🔐 Autorizar acceso a Spotify", expanded=True):
        st.markdown(
            f"""
            <div style="background-color:transparent;padding:10px;border-radius:8px;color:white">
                <b>1. Haz clic en el botón para autorizar:</b><br>
                <a href="{auth_url}" target="_blank">
                    <button style="background-color:#1DB954;color:white;padding:8px 16px;border:none;border-radius:4px">
                        Autorizar en Spotify
                    </button>
                </a><br><br>
                <b>2. Luego, pega aquí la URL completa de redirección:</b>
            </div>
            """, unsafe_allow_html=True
        )
        redirect_response = st.text_input("🔗 Pega aquí la URL después de autorizar")

        if redirect_response:
            code = auth_manager.parse_response_code(redirect_response)
            if code:
                token_info = auth_manager.get_access_token(code, as_dict=True)
                st.session_state[TOKEN_INFO_KEY] = token_info
                st.success("✅ Autenticación completada, ya puedes continuar")
                return spotipy.Spotify(auth=token_info['access_token'])
            else:
                st.error("⚠️ No se pudo obtener el código de autorización")

    return None

# --- Helpers Spotify ---
def get_playlist_id_from_url(url):
    return url.split("playlist/")[1].split("?")[0] if "playlist/" in url else url

def get_playlist_tracks(sp, playlist_id):
    tracks = []
    results = sp.playlist_tracks(playlist_id, limit=100)  # Spotify API máximo 100 por página
    tracks.extend(results['items'])
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])
    return tracks

def safe_get_artist(sp, artist_id):
    while True:
        try:
            return sp.artist(artist_id)
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                retry = int(e.headers.get('Retry-After', 1))
                st.error(f"Spotify rate limit: esperar {retry} s")
                st.stop()
            raise

def load_cache(filename="artist_genre_cache.json"):
    return json.load(open(filename, "r", encoding="utf-8")) if os.path.exists(filename) else {}

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

# --- Interfaz Streamlit ---
st.set_page_config(page_title="🎧 Genrer", page_icon="🎵")
st.title("🎧 Genrer: Spotify Genre Classifier")

sp = get_spotify_client()
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
            tracks = get_playlist_tracks(sp, playlist_id)
            if not tracks:
                st.warning("No se encontraron canciones.")
            else:
                genres = get_genres_from_tracks(sp, tracks, artist_filter, lang_filter)
                st.session_state["genres"] = genres
                st.success(f"Géneros encontrados: {len(genres)}")

                # --- Estadísticas de canciones ---
                artist_genres_cache = load_cache()
                rows = []

                for t in tracks:
                    info = t.get('track')
                    if not info:
                        continue

                    track_name = info['name']
                    popularity = info.get('popularity', np.nan)
                    duration_sec = int(info.get('duration_ms', 0) / 1000)
                    artists_names = ", ".join([a['name'] for a in info['artists']])
                    main_artist_id = info['artists'][0]['id']

                    if main_artist_id in artist_genres_cache:
                        genres_list = artist_genres_cache[main_artist_id]
                    else:
                        art = safe_get_artist(sp, main_artist_id)
                        genres_list = art.get('genres') or ['Unknown']
                        artist_genres_cache[main_artist_id] = genres_list

                    macro_genre = "Desconocido"
                    for g in genres_list:
                        simplified = g.lower()
                        if "rap" in simplified or "trap" in simplified or "hip hop" in simplified:
                            macro_genre = "Hip-Hop"
                            break
                        elif "pop" in simplified:
                            macro_genre = "Pop"
                            break
                        elif "rock" in simplified or "indie" in simplified:
                            macro_genre = "Rock"
                            break
                        elif "classical" in simplified:
                            macro_genre = "Classical"
                            break
                        elif "jazz" in simplified:
                            macro_genre = "Jazz"
                            break
                        elif "techno" in simplified or "electro" in simplified or "house" in simplified:
                            macro_genre = "Electronic"
                            break

                    rows.append({
                        "Canción": track_name,
                        "Artistas": artists_names,
                        "Popularidad": popularity,
                        "Duración (s)": duration_sec,
                        "Macro-género": macro_genre
                    })

                save_cache(artist_genres_cache)

                df = pd.DataFrame(rows)

                if not df.empty:
                    with st.expander("📊 Estadísticas y análisis por Macro-género", expanded=True):
                        st.dataframe(df)

                        color_map = {
                            "Hip-Hop": "#1f77b4", "Electronic": "#ff7f0e", "Pop": "#2ca02c",
                            "Rock": "#d62728", "Classical": "#9467bd", "Jazz": "#8c564b"
                        }

                        # Canciones por género
                        count_data = df.groupby("Macro-género").size().reset_index(name="Cantidad")
                        chart1 = alt.Chart(count_data).mark_bar().encode(
                            x=alt.X("Macro-género", sort="-y"),
                            y="Cantidad",
                            color=alt.Color("Macro-género", scale=alt.Scale(domain=list(color_map.keys()),
                                                                            range=list(color_map.values()))),
                            tooltip=["Macro-género", "Cantidad"]
                        ).properties(title="Número de canciones por Macro-género")
                        st.altair_chart(chart1, use_container_width=True)

                        # Popularidad media
                        pop_data = df.groupby("Macro-género")["Popularidad"].mean().reset_index()
                        chart2 = alt.Chart(pop_data).mark_bar().encode(
                            x=alt.X("Macro-género", sort="-y"),
                            y=alt.Y("Popularidad", title="Popularidad media"),
                            color=alt.Color("Macro-género", scale=alt.Scale(domain=list(color_map.keys()),
                                                                            range=list(color_map.values()))),
                            tooltip=["Macro-género", alt.Tooltip("Popularidad", format=".2f")]
                        ).properties(title="Popularidad media por Macro-género")
                        st.altair_chart(chart2, use_container_width=True)

                        # Duración media
                        dur_data = df.groupby("Macro-género")["Duración (s)"].mean().reset_index()
                        chart3 = alt.Chart(dur_data).mark_bar().encode(
                            x=alt.X("Macro-género", sort="-y"),
                            y=alt.Y("Duración (s)", title="Duración media (s)"),
                            color=alt.Color("Macro-género", scale=alt.Scale(domain=list(color_map.keys()),
                                                                            range=list(color_map.values()))),
                            tooltip=["Macro-género", alt.Tooltip("Duración (s)", format=".2f")]
                        ).properties(title="Duración media por Macro-género")
                        st.altair_chart(chart3, use_container_width=True)

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
