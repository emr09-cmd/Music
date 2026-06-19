from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
import sqlite3
import bcrypt
import yt_dlp
import os
import re

app = Flask(__name__)
app.secret_key = "supersecretkey123"

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

song_cache = {}

# ===================== DB =====================
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ===================== AUTH =====================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

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
            return render_template('register.html', error="Username or email already exists.")

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

        if result and bcrypt.checkpw(password.encode('utf-8'), result[0]):
            session['user'] = username
            return redirect(url_for('music'))

        return render_template('login.html', error="Invalid username or password.")

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/')
def home():
    return redirect(url_for('music') if 'user' in session else url_for('login'))


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

            results.append({
                "id": entry.get("id"),
                "title": entry.get("title"),
                "artist": entry.get("uploader", "Unknown"),
                "duration": entry.get("duration", 0),
                "thumbnail": f"https://img.youtube.com/vi/{entry.get('id')}/hqdefault.jpg"
            })

        song_cache[query] = results
        return jsonify(results)

    except Exception as e:
        return jsonify([])


# ===================== STREAM (FIXED) =====================
@app.route('/api/stream/<video_id>')
def stream_audio(video_id):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'noplaylist': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False
            )

        audio_url = info.get('url')

        if not audio_url:
            return "No audio URL found", 500

        # 🔥 FIX: no proxying, just redirect
        return redirect(audio_url)

    except Exception as e:
        return str(e), 500


# ===================== DOWNLOAD =====================
@app.route('/api/download/<video_id>')
def download(video_id):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_FOLDER}/{video_id}.%(ext)s',
            'noplaylist': True,
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=True
            )

        return jsonify({
            "status": "success",
            "title": info.get("title"),
            "video_id": video_id
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ===================== CACHE FILES =====================
@app.route('/api/cached-files')
def cached_files():
    if 'user' not in session:
        return jsonify({'files': []})

    files = []
    for f in os.listdir(DOWNLOAD_FOLDER):
        path = os.path.join(DOWNLOAD_FOLDER, f)
        if os.path.isfile(path):
            files.append({
                "name": f,
                "size": os.path.getsize(path)
            })

    return jsonify({"files": files})


@app.route('/cache/<filename>')
def cache(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename)


# ===================== RUN =====================
if __name__ == '__main__':
    app.run(debug=True)
