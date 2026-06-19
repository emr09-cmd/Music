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

# ===================== PASSWORD HELPERS =====================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def check_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash

# ===================== DB INIT =====================
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

# ===================== AUTH =====================
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

        if result and check_password(password, result[0]):
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
    if 'user' in session:
        return redirect(url_for('music'))
    return redirect(url_for('login'))


@app.route('/music')
def music():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session['user'])


# ===================== UTIL =====================
def clean_title(title):
    if not title:
        return "Unknown"

    title = re.sub(r'\s*\(\s*Official.*?Video.*?\)', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*\[\s*Official.*?\]', '', title, flags=re.IGNORECASE)
    title = re.sub(r'【.*?】', '', title)
    title = re.sub(r'[^a-zA-Z0-9\s\-]', '', title)

    return title.strip()[:80]


# ===================== API =====================
@app.route('/api/search')
def search_songs():
    query = request.args.get('q', '').strip()

    if not query or len(query) < 2:
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

        for entry in info.get('entries', [])[:12]:
            if entry and entry.get('duration'):
                video_id = entry.get('id')

                results.append({
                    'id': video_id,
                    'title': entry.get('title'),
                    'artist': entry.get('uploader', 'Unknown').replace('- Topic', '').strip(),
                    'duration': int(entry.get('duration', 0)),
                    'thumbnail': f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                })

        song_cache[query] = results
        return jsonify(results)

    except Exception:
        return jsonify([])


@app.route('/api/stream/<video_id>')
def stream_audio(video_id):
    ydl_opts = {'format': 'bestaudio/best', 'quiet': True}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://youtube.com/watch?v={video_id}", download=False)
            audio_url = info['url']
            ext = info.get('ext', 'mp4')

        range_header = request.headers.get('Range')
        req_headers = {'Range': range_header} if range_header else {}

        r = requests.get(audio_url, headers=req_headers, stream=True)

        status = r.status_code

        resp_headers = {
            'Content-Type': r.headers.get('Content-Type', f'audio/{ext}'),
            'Accept-Ranges': 'bytes',
        }

        if 'Content-Length' in r.headers:
            resp_headers['Content-Length'] = r.headers['Content-Length']
        if 'Content-Range' in r.headers:
            resp_headers['Content-Range'] = r.headers['Content-Range']

        def generate():
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk

        return Response(generate(), status=status, headers=resp_headers)

    except Exception as e:
        return str(e), 500


@app.route('/api/download/<video_id>')
def download_to_cache(video_id):
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
            title = info.get('title', video_id)

        after = set(os.listdir(DOWNLOAD_FOLDER))
        new_files = [f for f in (after - before) if not f.startswith('.')]

        saved = None

        if new_files:
            saved = new_files[0]
        else:
            for f in os.listdir(DOWNLOAD_FOLDER):
                if f.startswith(video_id) and not f.startswith('.'):
                    saved = f
                    break

        if not saved:
            return jsonify({
                "status": "error",
                "message": "Downloaded but file not found"
            }), 500

        return jsonify({
            "status": "success",
            "message": "Downloaded to cache",
            "filename": saved,
            "title": title,
            "video_id": video_id
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/cache/<filename>')
def serve_cache(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename)


@app.route('/api/cached-files')
def cached_files():
    if 'user' not in session:
        return jsonify({'files': [], 'error': 'not logged in'})

    try:
        entries = []

        for name in os.listdir(DOWNLOAD_FOLDER):
            if name.startswith('.'):
                continue

            full = os.path.join(DOWNLOAD_FOLDER, name)

            if os.path.isfile(full):
                entries.append({
                    'name': name,
                    'size': os.path.getsize(full)
                })

        return jsonify({'files': entries})

    except Exception as e:
        return jsonify({'files': [], 'error': str(e)})


# ===================== RUN =====================
if __name__ == '__main__':
    app.run(debug=True)
