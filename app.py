import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, redirect, request, session, url_for, render_template_string
from dotenv import load_dotenv

# --- FLASK APP AND SESSION SETUP ---
app = Flask(__name__)
# Load .env file for local development (Vercel will use its own env vars)
load_dotenv()

# This is REQUIRED for sessions to work.
# Vercel: Set this in your Environment Variables.
# Local: Put this in your .env file.
app.secret_key = os.environ.get("FLASK_SECRET_KEY")

# --- SPOTIPY AUTHENTICATION SETUP ---
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI") # Should be https://.../callback
SCOPE = "user-library-read playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public"

# --- LOGO SVG (for use in templates) ---
# A custom-made "Spotify Filter" logo
SVG_LOGO = """
<svg width="40" height="40" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M85.006 15.011C75.874 5.879 63.63 0 50 0C22.386 0 0 22.386 0 50C0 77.614 22.386 100 50 100C77.614 100 100 77.614 100 50C100 36.37 94.121 24.126 85.006 15.011ZM74.062 70.312C73.12 71.304 71.696 71.597 70.704 70.655C58.344 63.098 42.66 61.266 25.12 65.4C23.999 65.684 22.844 65.045 22.56 63.924C22.276 62.803 22.915 61.648 24.036 61.364C42.84 57.008 59.73 58.97 73.193 67.24C74.185 68.17 74.478 69.593 73.536 70.585L74.062 70.312Z" fill="#1DB954"/>
    <path d="M98 60H76C75.4477 60 75 60.4477 75 61V65C75 65.5523 75.4477 66 76 66H98C98.5523 66 99 65.5523 99 65V61C99 60.4477 98.5523 60 98 60Z" fill="white"/>
    <path d="M94 72H80C79.4477 72 79 72.4477 79 73V77C79 77.5523 79.4477 78 80 78H94C94.5523 78 95 77.5523 95 77V73C95 72.4477 94.5523 72 94 72Z" fill="white"/>
    <path d="M90 84H84C83.4477 84 83 84.4477 83 85V89C83 89.5523 83.4477 90 84 90H90C90.5523 90 91 89.5523 91 89V85C91 84.4477 90.5523 84 90 84Z" fill="white"/>
</svg>
"""


def get_oauth_manager():
    """Returns a SpotifyOAuth object that uses the user's session for caching."""
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_handler=spotipy.cache_handler.FlaskSessionCacheHandler(session)
    )

def get_spotify_client():
    """Gets a Spotipy client for the current user, or None if not authenticated."""
    oauth_manager = get_oauth_manager()
    token_info = oauth_manager.get_cached_token()

    if not token_info:
        return None
    
    if oauth_manager.is_token_expired(token_info):
        token_info = oauth_manager.refresh_access_token(token_info['refresh_token'])
        session['token_info'] = token_info

    return spotipy.Spotify(auth=token_info['access_token'])


# --- PAGE ROUTES ---

@app.route("/")
def index():
    """
    Homepage.
    Shows login button or the main app (playlist filterer).
    """
    sp = get_spotify_client()
    
    if not sp:
        # User is not logged in
        return render_template_string(HTML_LOGIN_PAGE, logo=SVG_LOGO)

    # User is logged in, show the main app
    user_info = sp.current_user()
    
    # Fetch all user playlists to display in the filter list
    print("Fetching user's playlists...")
    playlists = []
    offset = 0
    limit = 50
    while True:
        results = sp.current_user_playlists(limit=limit, offset=offset)
        if not results['items']:
            break
        
        full_playlist_items = []
        for item in results['items']:
            try:
                pl = sp.playlist(item['id'], fields="id,name,images,tracks.total")
                full_playlist_items.append(pl)
            except Exception:
                pass 
                
        playlists.extend(full_playlist_items)
        offset += limit
    
    print(f"Found {len(playlists)} playlists.")
    
    # Render the main app HTML, passing in user data
    return render_template_string(
        HTML_APP_PAGE, 
        user_name=user_info['display_name'],
        playlists=playlists,
        logo=SVG_LOGO
    )

@app.route("/login")
def login():
    """Redirects user to Spotify to log in."""
    oauth_manager = get_oauth_manager()
    auth_url = oauth_manager.get_authorize_url()
    return redirect(auth_url)

@app.route("/callback")
def callback():
    """
    Handles the redirect from Spotify after login.
    Saves the auth token in the session.
    """
    oauth_manager = get_oauth_manager()
    
    if request.args.get("error"):
        error_msg = request.args.get("error")
        return f"Error from Spotify: {error_msg}"
        
    code = request.args.get("code")
    if not code:
        return "Error: No code provided in callback."

    try:
        token_info = oauth_manager.get_access_token(code)
    except Exception as e:
        return f"Error getting token: {e}"

    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    """Logs the user out by clearing the session."""
    session.clear()
    return redirect(url_for("index"))

@app.route("/run-filter", methods=["POST"])
def run_filter():
    """
    This is the main logic. It runs when the user submits the form.
    """
    sp = get_spotify_client()
    if not sp:
        return "Error: Not authenticated. Please log in again.", 401

    try:
        # 1. Get data from the submitted form
        form_data = request.form
        target_playlist_link = form_data.get("target_playlist")
        filter_playlist_ids = form_data.getlist("filter_playlists")
        include_liked_songs = form_data.get("include_liked_songs") == "on"
        
        # 2. Get ID from the target playlist link
        target_playlist_id = get_playlist_id_from_link(target_playlist_link)
        if not target_playlist_id:
            return "Invalid Target Playlist link.", 400
        
        playlist_name = sp.playlist(target_playlist_id, fields='name')['name']

        # 3. Build the master set of all songs to remove
        print("Building filter list...")
        all_filter_song_ids = set()

        if include_liked_songs:
            print("Fetching Liked Songs...")
            offset = 0
            while True:
                results = sp.current_user_saved_tracks(limit=50, offset=offset)
                if not results['items']:
                    break
                for item in results['items']:
                    if item['track'] and item['track']['id']:
                        all_filter_song_ids.add(item['track']['id'])
                offset += 50
        
        for filter_pid in filter_playlist_ids:
            if filter_pid == "liked_songs": continue 
            
            filter_playlist_name = sp.playlist(filter_pid, fields='name')['name']
            print(f"Fetching songs from filter playlist: '{filter_playlist_name}'...")
            offset = 0
            while True:
                results = sp.playlist_items(filter_pid, limit=100, offset=offset, fields="items(track(id)), next")
                if not results['items']:
                    break
                for item in results['items']:
                    if item['track'] and item['track']['id']:
                        all_filter_song_ids.add(item['track']['id'])
                offset += 100
        
        print(f"Total unique songs in filter: {len(all_filter_song_ids)}")

        # 4. Find songs in the target playlist that are in our filter set
        print(f"Scanning target playlist: '{playlist_name}'")
        
        # We now store {'id': ..., 'name': ...}
        tracks_to_remove = [] 
        offset = 0
        while True:
            results = sp.playlist_items(target_playlist_id, limit=100, offset=offset, fields="items(track(id, name)), next")
            if not results['items']:
                break
            
            for item in results['items']:
                track = item['track']
                if not track or not track['id']:
                    continue
                
                if track['id'] in all_filter_song_ids:
                    print(f"  -> Found match: {track['name']}")
                    tracks_to_remove.append({'id': track['id'], 'name': track['name']})
            offset += 100
        
        # 5. Remove the songs in batches
        if not tracks_to_remove:
            return f"All done! No songs to remove from '{playlist_name}'."

        print(f"Removing {len(tracks_to_remove)} songs...")
        
        # Get just the IDs for the API call
        tracks_to_remove_ids = [t['id'] for t in tracks_to_remove]
        
        for i in range(0, len(tracks_to_remove_ids), 100):
            batch = tracks_to_remove_ids[i:i+100]
            sp.playlist_remove_all_occurrences_of_items(target_playlist_id, batch)
            print(f"Removed batch {i//100 + 1}...")
        
        # Build an HTML response with the list of removed songs
        song_list_html = "<ul class='removed-song-list'>"
        for track in tracks_to_remove:
            # We escape the track name to prevent HTML injection
            track_name_escaped = (
                track['name']
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
            )
            song_list_html += f"<li>{track_name_escaped}</li>"
        song_list_html += "</ul>"
        
        success_message = f"✅ Success! Removed {len(tracks_to_remove)} songs from '{playlist_name}'."
        return f"<div>{success_message}</div><br><h4>Removed Songs:</h4>{song_list_html}"

    except Exception as e:
        print(f"An error occurred: {e}")
        return f"An error occurred: {e}", 500


# --- HELPER FUNCTIONS (from our old script) ---

def get_playlist_id_from_link(link):
    """Extracts the Playlist ID from a Spotify URL or URI."""
    if not link: return None
    if "open.spotify.com/playlist/" in link:
        return link.split("playlist/")[1].split("?")[0]
    elif "spotify:playlist:" in link:
        return link.split("spotify:playlist:")[1]
    else:
        return None

# --- HTML TEMPLATES ---
# We are embedding the HTML directly in our Python file for simplicity.

HTML_LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spotify Filterer</title>
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
            display: flex; /* Changed to flex */
            flex-direction: column; /* Stack header and container */
            align-items: center; /* Center horizontally */
            justify-content: center; /* Center vertically */
            min-height: 100vh; 
            background-color: #121212; 
            color: #fff;
            margin: 0;
            padding: 2rem;
            box-sizing: border-box;
            
            /* The new animated background */
            background: linear-gradient(-45deg, #121212, #191919, #0d2a14, #191919);
            background-size: 400% 400%;
            animation: gradientBG 25s ease infinite;
        }
        
        @keyframes gradientBG {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        .header {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .header h1 {
            font-size: 2.5rem;
        }

        .container { 
            text-align: center; 
            background: #282828; 
            padding: 3rem 4rem; 
            border-radius: 1rem; 
            width: 100%;
            max-width: 450px;
        }
        .container p {
            font-size: 1.2rem;
            color: #aaa;
            margin-bottom: 2.5rem; /* Added spacing */
        }
        .login-btn { 
            background-color: #1DB954; 
            color: white; 
            padding: 1.25rem 2rem; /* Taller button */
            border: none; 
            border-radius: 500px; 
            text-decoration: none; 
            font-size: 1.2rem; 
            font-weight: bold; 
            cursor: pointer; 
            display: block; /* Make it full-width */
            width: 100%;
        }
        .login-btn:hover { background-color: #1ED760; }
    </style>
</head>
<body>
    <div class="header">
        {{ logo|safe }}
        <h1>Spotify Filterer</h1>
    </div>
    <div class="container">
        <p>Log in to get started.</p>
        <a href="{{ url_for('login') }}" class="login-btn">Login with Spotify</a>
    </div>
</body>
</html>
"""

HTML_APP_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spotify Filterer</title>
    <style>
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
            background-color: #121212; 
            color: #fff; 
            margin: 0; 
            padding: 2rem;
            
            /* The new animated background */
            background: linear-gradient(-45deg, #121212, #191919, #0d2a14, #191919);
            background-size: 400% 400%;
            animation: gradientBG 25s ease infinite;
        }

        @keyframes gradientBG {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        .header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            border-bottom: 1px solid #282828; 
            padding-bottom: 2rem; 
            margin-bottom: 2rem;
        }
        .header .title {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .header h1 { margin: 0; }
        .header span { font-size: 0.9rem; }
        .logout-btn { background: #333; color: white; text-decoration: none; padding: 0.5rem 1rem; border-radius: 500px; font-size: 0.9rem; font-weight: bold; }
        .logout-btn:hover { background: #555; }
        
        .content { 
            display: grid; 
            grid-template-columns: 1fr; /* Single column on mobile */
            gap: 2rem; 
            max-width: 1400px; /* Wider max width */
            margin-left: auto; 
            margin-right: auto;
            align-items: center; /* Vertically center the cards */
        }
        /* Asymmetrical layout on larger screens */
        @media (min-width: 900px) { 
            .content { grid-template-columns: 1fr 3fr; } /* 1:3 ratio */
        }
        
        .box { background: #181818; padding: 1.5rem; border-radius: 1rem; }
        .box h2 { 
            margin-top: 0; 
            border-bottom: 1px solid #282828; 
            padding-bottom: 0.5rem; 
        }
        
        /* Left Card ("Target") Specific Styles */
        .target-card { padding: 2rem; } /* More padding */
        .target-card h2 { font-size: 1.8rem; } /* Bigger text */
        .target-card p { font-size: 1.1rem; }
        .target-card .form-group label { font-size: 1rem; }

        .form-group { margin-bottom: 1.5rem; }
        .form-group label { display: block; margin-bottom: 0.5rem; font-weight: bold; }
        .form-group input[type='text'] { width: 100%; padding: 1rem; background: #282828; border: 1px solid #555; border-radius: 0.5rem; color: #fff; box-sizing: border-box; font-size: 1rem; }
        
        /* Right Card ("Filter") Specific Styles */
        .filter-card { padding: 2rem; }
        .filter-card h2 { font-size: 1.8rem; }
        .filter-card p { font-size: 1.1rem; }

        .playlist-list { 
            max-height: 700px; /* Taller list */
            overflow-y: auto; 
            background: #282828; 
            border-radius: 0.5rem; 
            padding: 1rem; 
            border: 1px solid #555;
            /* This creates the multi-column grid */
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 0.75rem; /* Space between items */
        }
        
        /* New Playlist Item Styling */
        .playlist-item {
            display: flex;
            align-items: center;
            padding: 0.75rem; /* More padding */
            border-radius: 8px;
            transition: background-color 0.2s;
            cursor: pointer;
            background-color: #181818; /* Darker item background */
            overflow: hidden; /* Ensure no overflow */
        }
        .playlist-item:hover {
            background-color: #3a3a3a;
        }
        
        .playlist-item input[type='checkbox'] {
            accent-color: #1DB954; /* Style the checkbox */
            width: 1.3rem; /* Larger checkbox */
            height: 1.3rem;
            flex-shrink: 0; 
        }
        
        .playlist-cover {
            width: 50px;
            height: 50px;
            object-fit: cover;
            border-radius: 4px; /* Spotify-like rounded square */
            margin-left: 1rem;
            margin-right: 1rem;
            flex-shrink: 0;
            background: #333; /* Placeholder background */
        }
        .playlist-cover.placeholder {
            display: grid;
            place-items: center;
            font-size: 1.5rem;
        }
        
        .playlist-info {
            display: flex;
            flex-direction: column;
            overflow: hidden; /* Prevent long names from breaking layout */
        }
        .playlist-name {
            font-size: 1rem; /* Larger name */
            font-weight: bold;
            color: #fff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .playlist-count {
            font-size: 0.9rem;
            color: #aaa;
        }
        
        .submit-btn { 
            width: 100%; 
            background-color: #1DB954; 
            color: white; 
            padding: 1.25rem 2rem; /* Taller button */
            border: none; 
            border-radius: 500px; 
            text-decoration: none; 
            font-size: 1.4rem; /* Bigger button text */
            font-weight: bold; 
            cursor: pointer; 
            margin-top: 1rem; 
        }
        .submit-btn:hover { background-color: #1ED760; }
        
        #response-box { 
            margin-top: 1.5rem; 
            background: #282828; 
            padding: 1.5rem; 
            border-radius: 0.5rem; 
            display: none; 
            font-size: 1.1rem;
        }
        
        /* Style for the new removed songs list */
        .removed-song-list {
            max-height: 200px;
            overflow-y: auto;
            background: #121212;
            padding: 1rem;
            border-radius: 8px;
            font-size: 0.9rem;
            list-style-type: decimal;
            margin-bottom: 0;
        }
        .removed-song-list li {
            padding: 0.25rem 0;
        }

    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            {{ logo|safe }}
            <h1>Spotify Filterer</h1>
        </div>
        <span>Logged in as: <b>{{ user_name }}</b> <a href="{{ url_for('logout') }}" class="logout-btn">Logout</a></span>
    </div>

    <!-- Form now wraps both columns -->
    <form id="filter-form">
    <div class="content">
        <div class="box target-card">
            <h2>1. Target Playlist</h2>
            <p>Paste the link of the playlist you want to clean up.</p>
            <div class="form-group">
                <label for="target_playlist">Target Playlist Link</label>
                <input type="text" id="target_playlist" name="target_playlist" required placeholder="https://open.spotify.com/playlist/...">
            </div>
            
            <h2>3. Run Filter</h2>
            <p>This will permanently remove songs from your target playlist.</p>
            <button type="submit" class="submit-btn">Start Filtering</button>
        </div>

        <div class="box filter-card">
            <h2>2. Filter Playlists</h2>
            <p>Select which songs to remove. Any song from these sources will be removed from your target playlist.</p>
            <div class="playlist-list" id="filter-playlists-container">
                
                <!-- Styled Liked Songs Item -->
                <label class="playlist-item">
                    <input type="checkbox" name="include_liked_songs" checked>
                    <div class="playlist-cover placeholder">
                        <!-- Inline SVG for a white heart -->
                        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="white">
                            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                        </svg>
                    </div>
                    <div class="playlist-info">
                        <span class="playlist-name">Your Liked Songs</span>
                    </div>
                </label>
                
                <!-- Playlists will be populated here -->
                {% for playlist in playlists %}
                <label class="playlist-item">
                    <input type="checkbox" name="filter_playlists" value="{{ playlist.id }}">
                    
                    {% if playlist.images and playlist.images|length > 0 %}
                        <img src="{{ playlist.images[-1].url }}" alt="{{ playlist.name }} cover" class="playlist-cover">
                    {% else %}
                        <!-- Placeholder for playlists with no image -->
                        <div class="playlist-cover placeholder">
                            <span>🎵</span>
                        </div>
                    {% endif %}

                    <div class="playlist-info">
                        <span class="playlist-name">{{ playlist.name }}</span>
                        <span class="playlist-count">{{ playlist.tracks.total }} songs</span>
                    </div>
                </label>
                {% endfor %}
            </div>
        </div>
    </div>
    </form> <!-- Form tag closes here -->
    
    <div style="max-width: 1400px; margin-left: auto; margin-right: auto;">
        <div id="response-box"></div>
    </div>

    <script>
        document.getElementById('filter-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const form = e.target;
            const formData = new FormData(form);
            const submitBtn = form.querySelector('.submit-btn');
            const responseBox = document.getElementById('response-box');
            
            submitBtn.disabled = true;
            submitBtn.textContent = 'Filtering...';
            responseBox.style.display = 'block';
            responseBox.style.color = '#fff'; // Default text color
            responseBox.innerHTML = 'Working... this may take a few minutes for large playlists.';

            try {
                const response = await fetch("{{ url_for('run_filter') }}", {
                    method: 'POST',
                    body: formData
                });
                
                const resultText = await response.text();
                
                if (response.ok) {
                    responseBox.style.color = '#1DB954';
                    // We now use innerHTML to render the returned list
                    responseBox.innerHTML = resultText;
                } else {
                    responseBox.style.color = '#FF4500'; // Red for error
                    responseBox.innerHTML = 'Error: ' + resultText;
                }
                
            } catch (error) {
                responseBox.style.color = '#FF4500'; // Red for error
                responseBox.innerHTML = 'A network error occurred: ' + error.message;
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Start Filtering';
            }
        });
    </script>
</body>
</html>
"""

# This makes the app runnable locally for testing (python app.py)
# Vercel will use a different method to run the 'app' object
if __name__ == "__main__":
    app.run(debug=True, port=8080)