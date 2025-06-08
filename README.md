# 🎧 Genrer

This web application allows you to analyze the musical genres of a Spotify playlist and create new playlists organized by genre.

## 🚀 How to Use

1. Clone the repository:
   ```bash
   git clone https://github.com/DiRoGa/genrer.git
   cd genrer
   ```

2. Create a `.env` file with your Spotify credentials.

3. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the app:
   ```bash
   streamlit run main.py
   ```

## 🌐 Deploy

You can easily deploy this app to [Streamlit Cloud](https://streamlit.io/cloud) or Render.

## 🔐 Required Environment Variables

Include a `.env` file with the following:

```env
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=http://localhost:8501
```

## 📸 Screenshots (optional)

![Example Image](https://github.com/DiRoGa/Genrer/blob/main/assets/example.png?raw=true)

## 📄 License

MIT License. Free to use and modify.

---

Made with ❤️ using Streamlit and the Spotify API.
