import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from dotenv import load_dotenv

# --- AUTHENTICATION (Same as before) ---
# Load the variables from your .env file
load_dotenv()

CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI")

if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
    print("Error: Could not find CLIENT_ID, CLIENT_SECRET, or REDIRECT_URI in your .env file.")
    exit()

SCOPE = "user-library-read playlist-read-private playlist-modify-private playlist-modify-public"

# This will now use your .cache file automatically
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE,
    # Caching the token is on by default, but we'll be explicit
    cache_path=".cache"
))

try:
    user_info = sp.current_user()
    print(f"---")
    print(f"✅ Successfully authenticated as: {user_info['display_name']}")
    print(f"---")
except Exception as e:
    print(f"Error during authentication: {e}")
    exit()

# --- HELPER FUNCTION TO GET PLAYLIST ID ---
def get_playlist_id_from_link(link):
    """Extracts the Playlist ID from a Spotify URL or URI."""
    if "open.spotify.com/playlist/" in link:
        # It's a URL
        return link.split("playlist/")[1].split("?")[0]
    elif "spotify:playlist:" in link:
        # It's a URI
        return link.split("spotify:playlist:")[1]
    else:
        return None

# --- MAIN SCRIPT LOGIC ---
def clean_playlist():
    
    # 1. Get all Liked Songs
    print("Fetching all your Liked Songs (this may take a moment)...")
    liked_songs_ids = set() # A set is much faster for lookups
    offset = 0
    limit = 50 # Max limit per request

    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not results['items']:
            break # No more songs
        
        for item in results['items']:
            liked_songs_ids.add(item['track']['id'])
        
        offset += limit
        print(f"Loaded {len(liked_songs_ids)} liked songs...")

    print(f"\n✅ Total Liked Songs found: {len(liked_songs_ids)}")
    print("---")

    # 2. Get the target playlist
    playlist_link = input("Paste the Spotify playlist link (URL) and press Enter: \n")
    playlist_id = get_playlist_id_from_link(playlist_link)
    
    if not playlist_id:
        print("❌ That doesn't look like a valid Spotify playlist link. Please try again.")
        return

    try:
        playlist_name = sp.playlist(playlist_id, fields='name')['name']
        print(f"Scanning playlist: '{playlist_name}'")
    except Exception as e:
        print(f"❌ Could not find playlist. Make sure the link is correct and you own/follow it. Error: {e}")
        return

    # 3. Find songs in the playlist that are "Liked"
    print("Finding songs to remove...")
    
    playlist_tracks = []
    tracks_to_remove_ids = [] # This will hold the IDs of songs we need to delete
    offset = 0
    limit = 100 # Max limit per request

    while True:
        results = sp.playlist_items(playlist_id, limit=limit, offset=offset, fields="items(track(id, name)), next")
        if not results['items']:
            break # No more songs in the playlist
        
        for item in results['items']:
            track = item['track']
            # Spotify can have "local files" or unplayable tracks with no ID
            if not track or not track['id']:
                continue
                
            # This is the core logic!
            if track['id'] in liked_songs_ids:
                print(f"  -> Found liked song: {track['name']}")
                tracks_to_remove_ids.append(track['id'])
        
        offset += limit
    
    print("---")

    # 4. Remove the songs in batches of 100
    if not tracks_to_remove_ids:
        print("✅ All done. No liked songs were found in this playlist.")
        return

    print(f"Found {len(tracks_to_remove_ids)} songs to remove. Removing them now...")

    # We must remove in batches of 100
    for i in range(0, len(tracks_to_remove_ids), 100):
        batch = tracks_to_remove_ids[i:i+100]
        sp.playlist_remove_all_occurrences_of_items(playlist_id, batch)
        print(f"Removed batch {i//100 + 1}...")

    print(f"✅ Successfully removed {len(tracks_to_remove_ids)} liked songs from '{playlist_name}'.")

# --- Run the main function ---
if __name__ == "__main__":
    clean_playlist()