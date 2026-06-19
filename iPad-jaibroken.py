from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response, send_from_directory
import sqlite3
import requests
import yt_dlp
import re
import os
import hashlib

app = Flask(__name__)
app.secret_key = "supersecretkey123"

song_cache = {}
DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ===================== AUTH (iPad SAFE) =====================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def check_password(password: str, stored: str) -> bool:
    return hash_password(password) == stored

# ===================== DB =====================
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE,
                    name TEXT,
                    email TEXT UNIQUE,
                    password TEXT
                 )''')
    conn.commit()
    conn.close()

init_db()

# ===================== ROUTES =====================
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('music'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        hashed = hash_password(password)

        try:
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute(
                "INSERT INTO users (username, name, email, password) VALUES (?, ?, ?, ?)",
                (username, name, email, hashed)
            )
            conn.commit()
            conn.close()
            return redirect(url_for('login'))

        except Exception:
            return render_template('register.html', error="User already exists.")

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT password FROM users WHERE username = ?", (username,))
        result = c.fetchone()
        conn.close()

        if result and check_password(password, result[0]):
            session['user'] = username
            return redirect(url_for('music'))

        return render_template('login.html', error="Invalid login")

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/music')
def music():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session['user'])


# ===================== SEARCH =====================
@app.route('/api/search')
def search_songs():
    query = request.args.get('q', '').strip()

    if len(query) < 2:
        return jsonify([])

    if query in song_cache:
        return jsonify(song_cache[query])

    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'default_search': 'ytsearch10'
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch10:{query}", download=False)

        results = []

        for entry in info.get('entries', []):
            if not entry:
                continue

            video_id = entry.get('id')
            if not video_id:
                continue

            results.append({
                'id': video_id,
                'title': entry.get('title', 'Unknown'),
                'artist': entry.get('uploader', 'Unknown'),
                'duration': entry.get('duration', 0),
                'thumbnail': f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            })

        song_cache[query] = results
        return jsonify(results)

    except Exception:
        return jsonify([])


# ===================== STREAM (FIXED) =====================
@app.route('/api/stream/<video_id>')
def stream_audio(video_id):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'noplaylist': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web']
                }
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False
            )

        # pick best audio format
        audio_url = None
        for f in reversed(info.get('formats', [])):
            if f.get('url') and f.get('acodec') != 'none':
                audio_url = f['url']
                break

        if not audio_url:
            return "No audio stream found", 500

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.youtube.com/"
        }

        r = requests.get(audio_url, headers=headers, stream=True)

        def generate():
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk

        return Response(generate(), headers={
            "Content-Type": "audio/mpeg",
            "Accept-Ranges": "bytes"
        })

    except Exception as e:
        return str(e), 500


# ===================== DOWNLOAD =====================
@app.route('/api/download/<video_id>')
def download(video_id):
    try:
        before = set(os.listdir(DOWNLOAD_FOLDER))

        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'outtmpl': f'{DOWNLOAD_FOLDER}/{video_id}.%(ext)s',
            'noplaylist': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://youtube.com/watch?v={video_id}", download=True)

        after = set(os.listdir(DOWNLOAD_FOLDER))
        new_files = list(after - before)

        saved = new_files[0] if new_files else None

        return jsonify({
            "status": "success",
            "file": saved,
            "title": info.get('title', 'unknown')
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ===================== CACHE FILES =====================
@app.route('/cache/<filename>')
def cache(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename)


@app.route('/api/cached-files')
def cached():
    if 'user' not in session:
        return jsonify({'files': []})

    files = []

    for f in os.listdir(DOWNLOAD_FOLDER):
        path = os.path.join(DOWNLOAD_FOLDER, f)
        if os.path.isfile(path):
            files.append({
                'name': f,
                'size': os.path.getsize(path)
            })

    return jsonify({'files': files})


# ===================== RUN =====================
if __name__ == '__main__':
    app.run(debug=True)
