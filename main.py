import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from langdetect import detect
import os
import json
import time
import pandas as pd
import altair as alt

# --- Configuración inicial ---
st.set_page_config(page_title="🎧 Genrer", page_icon="🎵")
st.title("🎧 Genrer: Spotify Genre Classifier")

# --- Cargar credenciales ---
load_dotenv()
CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI")
SCOPE = "playlist-read-private playlist-modify-public ugc-image-upload user-read-private"

# --- Mapeo de macro-géneros y colores ---
MACRO_GENRES = {
    "rap": "Hip-Hop", "hip hop": "Hip-Hop", "trap": "Hip-Hop",
    "house": "Electronic", "techno": "Electronic", "electro": "Electronic",
    "pop": "Pop", "rock": "Rock", "indie": "Rock",
    "classical": "Classical", "jazz": "Jazz"
}
MACRO_GENRES_ES = {
    "Hip-Hop": "Hip-Hop", "Electronic": "Electrónica", "Pop": "Pop",
    "Rock": "Rock", "Classical": "Clásica", "Jazz": "Jazz"
}
COLOR_PALETTE = {
    "Hip-Hop": "#1f77b4", "Electronic": "#ff7f0e", "Pop": "#2ca02c",
    "Rock": "#d62728", "Classical": "#9467bd", "Jazz": "#8c564b"
}

# --- Autenticación mejorada ---
def get_spotify_client():
    cache_path = ".cache"

    # Crear gestor de autenticación
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=cache_path,
        show_dialog=True
    )

    # Revisar si hay token válido en caché
    token_info = auth_manager.get_cached_token()

    if not token_info:
        try:
            # Forzar login
            auth_url = auth_manager.get_authorize_url()
            st.sidebar.markdown("### 🔐 Autenticación con Spotify")
            st.sidebar.markdown(f"[🔗 Haz clic aquí para iniciar sesión con Spotify]({auth_url})")
            code = st.query_params().get("code")
            if code:
                token_info = auth_manager.get_access_token(code[0])
        except Exception as e:
            st.error(f"Error durante la autenticación: {e}")
            st.stop()

    if not token_info:
        st.warning("Esperando autenticación. Asegúrate de iniciar sesión con el enlace de arriba.")
        st.stop()

    try:
        sp = spotipy.Spotify(auth_manager=auth_manager)
        user = sp.current_user()
        st.sidebar.success(f"✅ Autenticado como: {user['display_name']}")
        return sp
    except Exception as e:
        st.error(f"Error al crear cliente de Spotify: {e}")
        if os.path.exists(cache_path):
            os.remove(cache_path)
        st.stop()


# --- Helpers Spotify ---
def get_playlist_id_from_url(url):
    return url.split("playlist/")[1].split("?")[0] if "playlist/" in url else url

def get_playlist_tracks(sp, playlist_id):
    tracks = []
    results = sp.playlist_tracks(playlist_id, limit=100)
    tracks.extend(results['items'])
    while results['next']:
        results = sp.next(results)
        tracks.extend(results['items'])
    return tracks

def safe_get_artist(sp, artist_id):
    try:
        return sp.artist(artist_id)
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status == 429:
            retry = int(e.headers.get('Retry-After', 1))
            st.warning(f"⏳ Rate limit de Spotify: esperando {retry} segundos")
            time.sleep(retry)
            return safe_get_artist(sp, artist_id)
        elif e.http_status == 404:
            return {"genres": []}
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

def group_genre(genre):
    for key in MACRO_GENRES:
        if key in genre.lower():
            return MACRO_GENRES[key]
    return "Desconocido"

# --- Interfaz principal ---
sp = get_spotify_client()
if not sp:
    st.stop()

# --- Formulario análisis ---
with st.form("playlist_form"):
    playlist_url = st.text_input("🎼 URL de la playlist de Spotify")
    artist_filter = st.text_input("🎤 Filtrar por artista (opcional)")
    lang_filter = st.text_input("🌍 Filtrar por idioma del artista (ISO, ej: es, en)")
    submitted = st.form_submit_button("Analizar géneros")

if submitted and playlist_url:
    with st.spinner("🔍 Obteniendo canciones..."):
        try:
            playlist_id = get_playlist_id_from_url(playlist_url)
            tracks = get_playlist_tracks(sp, playlist_id)

            if not tracks:
                st.warning("La playlist está vacía.")
                st.stop()

            artist_cache = load_cache()
            stats = []
            progress = st.progress(0)

            for i, t in enumerate(tracks):
                info = t.get("track")
                if not info: continue

                name = info["name"]
                popularity = info.get("popularity", 0)
                duration = int(info["duration_ms"] / 1000)
                artists = info["artists"]
                artist_name = artists[0]["name"]
                artist_id = artists[0]["id"]

                if artist_filter and artist_filter.lower() not in artist_name.lower():
                    continue
                if lang_filter:
                    try:
                        if detect(artist_name) != lang_filter:
                            continue
                    except:
                        pass

                if artist_id in artist_cache:
                    genres = artist_cache[artist_id]
                else:
                    art = safe_get_artist(sp, artist_id)
                    genres = art.get("genres", []) or ["Unknown"]
                    artist_cache[artist_id] = genres

                macro = next((group_genre(g) for g in genres if group_genre(g) != "Desconocido"), "Desconocido")
                stats.append({
                    "Canción": name,
                    "Artista": artist_name,
                    "Popularidad": popularity,
                    "Duración (s)": duration,
                    "Macro-género": MACRO_GENRES_ES.get(macro, macro)
                })

                progress.progress((i + 1) / len(tracks))

            save_cache(artist_cache)

            df = pd.DataFrame(stats)
            if df.empty:
                st.warning("No se encontraron canciones tras aplicar los filtros.")
            else:
                with st.expander("📊 Estadísticas por macro-género", expanded=True):
                    st.dataframe(df)

                    count_df = df.groupby("Macro-género").size().reset_index(name="Cantidad")
                    mean_pop_df = df.groupby("Macro-género")["Popularidad"].mean().reset_index()
                    mean_dur_df = df.groupby("Macro-género")["Duración (s)"].mean().reset_index()

                    for chart_title, chart_df, y, y_title in [
                        ("🎶 Número de canciones", count_df, "Cantidad", "Cantidad"),
                        ("🔥 Popularidad media", mean_pop_df, "Popularidad", "Popularidad media"),
                        ("⏱️ Duración media", mean_dur_df, "Duración (s)", "Duración media (s)")
                    ]:
                        chart = alt.Chart(chart_df).mark_bar().encode(
                            x=alt.X("Macro-género", sort="-y"),
                            y=alt.Y(y, title=y_title),
                            color=alt.Color("Macro-género", scale=alt.Scale(
                                domain=list(COLOR_PALETTE.keys()),
                                range=list(COLOR_PALETTE.values())
                            )),
                            tooltip=["Macro-género", alt.Tooltip(y, format=".2f")]
                        ).properties(title=chart_title)
                        st.altair_chart(chart, use_container_width=True)

        except Exception as e:
            st.error(f"Error: {e}")
