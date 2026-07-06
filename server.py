import os
import re
import sys
import uuid
import json
import shutil
import zipfile
import threading
import time
import requests

# Try importing dependencies and print clear installation instructions if missing
try:
    from flask import Flask, request, jsonify, send_from_directory
except ImportError:
    print("Error: Flask is not installed. Please run: pip install flask")
    sys.exit(1)

try:
    import yt_dlp
except ImportError:
    print("Error: yt-dlp is not installed. Please run: pip install yt-dlp")
    sys.exit(1)

# Import existing workspace scripts
try:
    import fitbeat
    import quest_injector
except ImportError as e:
    print(f"Error importing workspace scripts: {e}")
    sys.exit(1)

app = Flask(__name__)

# Task storage
tasks = {}
tasks_lock = threading.Lock()

# Temporary processing directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp_processing")
os.makedirs(TEMP_DIR, exist_ok=True)

# CORS Header implementation
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    return response

def update_task(task_id, status, message, progress=None, download_url=None):
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id]["status"] = status
            tasks[task_id]["message"] = message
            if progress is not None:
                tasks[task_id]["progress"] = progress
            if download_url is not None:
                tasks[task_id]["download_url"] = download_url

def sanitize_filename(name):
    # Keep alphanumeric characters, spaces, hyphens, and underscores
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')

def process_youtube_map_task(task_id, url, difficulties, modes, events, push_to_quest):
    task_temp_dir = os.path.join(TEMP_DIR, task_id)
    os.makedirs(task_temp_dir, exist_ok=True)
    
    audio_path = None
    song_title = "Unknown Song"
    song_artist = "Unknown Artist"

    try:
        # Step 1: Download YouTube Audio
        update_task(task_id, "downloading", "Extracting audio from YouTube...", 10)
        
        # Resolve ffmpeg location (direct fallback for Gyan.FFmpeg winget installations)
        ffmpeg_bin_dir = None
        winget_ffmpeg_dir = r"C:\Users\nm95a\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin"
        if os.path.exists(os.path.join(winget_ffmpeg_dir, "ffmpeg.exe")):
            ffmpeg_bin_dir = winget_ffmpeg_dir
            
        # Configure yt-dlp to extract audio
        ydl_opts = {
            'format': 'bestaudio/best',
            'paths': {'home': task_temp_dir},
            'outtmpl': 'audio.%(ext)s',
            'noplaylist': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
        }
        
        if ffmpeg_bin_dir:
            ydl_opts['ffmpeg_location'] = ffmpeg_bin_dir

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
                song_title = info.get('title', 'Unknown Title')
                song_artist = info.get('uploader', 'Unknown Artist')
                
                # Retrieve the actual filename generated
                audio_path = os.path.join(task_temp_dir, 'audio.mp3')
                
                # fallback checks
                if not os.path.exists(audio_path):
                    # Check if it was downloaded with another audio extension or format
                    for f in os.listdir(task_temp_dir):
                        if f.endswith('.mp3'):
                            audio_path = os.path.join(task_temp_dir, f)
                            break
            except Exception as e:
                raise Exception(f"yt-dlp download failed: {str(e)}. Make sure ffmpeg is installed and on your PATH.")

        if not audio_path or not os.path.exists(audio_path):
            raise Exception("Downloaded audio file was not found.")

        # Update metadata
        with tasks_lock:
            tasks[task_id]["song_title"] = song_title
            tasks[task_id]["song_artist"] = song_artist

        # Step 2: Upload to BeatSage API
        update_task(task_id, "uploading", "Uploading audio to BeatSage...", 30)
        
        beatsage_url = "https://beatsage.com/beatsaber_custom_level_create"
        
        payload = {
            "audio_metadata_title": song_title,
            "audio_metadata_artist": song_artist,
            "difficulties": ",".join(difficulties),
            "modes": ",".join(modes),
            "events": ",".join(events),
            "environment": "DefaultEnvironment",
            "system_tag": "v2"
        }
        
        with open(audio_path, 'rb') as f:
            files = {'audio_file': f}
            response = requests.post(beatsage_url, data=payload, files=files)
            
        if response.status_code != 200:
            raise Exception(f"BeatSage submission failed: {response.text}")
            
        res_data = response.json()
        level_id = res_data.get("id")
        if not level_id:
            raise Exception("BeatSage response did not contain a level ID.")

        # Step 3: Polling for Completion
        update_task(task_id, "mapping", "BeatSage is mapping the song (usually takes 30-60s)...", 50)
        
        status = "PENDING"
        poll_count = 0
        max_polls = 100  # Prevent infinite loop (~300 seconds max)
        
        while status in ("PENDING", "PROCESSING") and poll_count < max_polls:
            time.sleep(3)
            poll_count += 1
            
            heartbeat_url = f"https://beatsage.com/beatsaber_custom_level_heartbeat/{level_id}"
            try:
                hb_res = requests.get(heartbeat_url)
                if hb_res.status_code == 200:
                    status_data = hb_res.json()
                    status = status_data.get("status", "PENDING")
                    # Increment progress slightly while waiting
                    current_prog = 50 + min(int(poll_count * 0.4), 25)
                    update_task(task_id, "mapping", f"BeatSage mapping status: {status}...", current_prog)
            except Exception as e:
                # Log error and retry
                print(f"Polling warning: {e}")
                
        if status != "DONE":
            raise Exception(f"BeatSage mapping timed out or failed with status: {status}")

        # Step 4: Download generated ZIP file
        update_task(task_id, "downloading_zip", "Downloading generated level...", 75)
        
        download_url = f"https://beatsage.com/beatsaber_custom_level_download/{level_id}"
        zip_res = requests.get(download_url)
        if zip_res.status_code != 200:
            raise Exception("Failed to download custom level zip from BeatSage.")
            
        zip_path = os.path.join(task_temp_dir, "level.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_res.content)

        # Step 5: Extract and run fitbeat.py
        update_task(task_id, "processing", "Injecting fitness obstacles (fitbeat.py)...", 85)
        
        extract_dir = os.path.join(task_temp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            
        # Parse info.dat
        info_filename = "info.dat" if os.path.exists(os.path.join(extract_dir, "info.dat")) else "Info.dat"
        info_path = os.path.join(extract_dir, info_filename)
        
        if not os.path.exists(info_path):
            raise Exception("Could not find info.dat in extracted level folder.")
            
        with open(info_path, 'r', encoding='utf-8') as f:
            info_data = json.load(f)
            
        is_v2 = "_version" in info_data and info_data["_version"].startswith("2.")
        
        # Get highest difficulty map file
        highest_file, diff_name, diff_obj = quest_injector.get_highest_difficulty_map(info_data)
        if not highest_file:
            raise Exception("Could not parse map difficulties from info.dat.")
            
        # Run fitbeat obstacle generator
        local_map_path = os.path.join(extract_dir, highest_file)
        fitbeat_filename = "FitBeat.dat"
        local_fitbeat_path = os.path.join(extract_dir, fitbeat_filename)
        
        # Call process_map from workspace fitbeat.py
        fitbeat.process_map(local_map_path, local_fitbeat_path)
        
        # Add FitBeat characteristics to info.dat using quest_injector function
        quest_injector.add_fitbeat_to_info(info_path, diff_obj, fitbeat_filename, is_v2)

        # Create final zipped package
        final_zip_filename = f"BeatFit_{sanitize_filename(song_title)}.zip"
        final_zip_path = os.path.join(TEMP_DIR, final_zip_filename)
        
        with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for root, dirs, files_in_dir in os.walk(extract_dir):
                for file in files_in_dir:
                    file_abs = os.path.join(root, file)
                    file_rel = os.path.relpath(file_abs, extract_dir)
                    zip_out.write(file_abs, file_rel)

        # Step 6: Push to Quest via ADB (optional)
        quest_success = False
        if push_to_quest:
            update_task(task_id, "deploying", "Pushing map to Meta Quest via ADB...", 95)
            
            try:
                # Check if device is connected
                devices_res = quest_injector.run_adb_command(["devices"])
                devices_lines = devices_res.stdout.strip().split("\n")
                connected_devices = [line for line in devices_lines[1:] if line.strip() and "device" in line]
                
                if not connected_devices:
                    update_task(task_id, "processing", "Quest was requested but no device was found via ADB. Skipping Quest deployment.", 90)
                else:
                    quest_base_path = "/sdcard/ModData/com.beatgames.beatsaber/Mods/SongLoader/CustomLevels/"
                    remote_folder_name = f"BeatFit_{sanitize_filename(song_title)}"
                    remote_song_folder = f"{quest_base_path}{remote_folder_name}/"
                    
                    # Make remote folder
                    quest_injector.run_adb_command(["shell", "mkdir", "-p", remote_song_folder])
                    
                    # Push files
                    # adb push source_dir/. destination_dir/
                    # We can push files one by one to avoid issues
                    push_error = False
                    for f in os.listdir(extract_dir):
                        local_f = os.path.join(extract_dir, f)
                        if os.path.isfile(local_f):
                            push_res = quest_injector.run_adb_command(["push", local_f, remote_song_folder + f])
                            if push_res.returncode != 0:
                                push_error = True
                                print(f"Error pushing {f}: {push_res.stderr}")
                                
                    if not push_error:
                        quest_success = True
                        update_task(task_id, "processing", "Successfully pushed level directly to Meta Quest!", 98)
                    else:
                        update_task(task_id, "processing", "Warning: Some files failed to push to Quest.", 90)
            except (FileNotFoundError, OSError) as adb_err:
                print(f"ADB not found: {adb_err}")
                update_task(task_id, "processing", "Quest deployment skipped: ADB command tool not found on system PATH.", 90)

        # Finished!
        final_msg = "Successfully completed level generation!"
        if push_to_quest and quest_success:
            final_msg += " Pushed directly to Meta Quest!"
        elif push_to_quest and not quest_success:
            final_msg += " (Quest deployment failed, check USB connection)."
            
        update_task(
            task_id, 
            "completed", 
            final_msg, 
            100, 
            download_url=f"/downloads/{final_zip_filename}"
        )

    except Exception as e:
        print(f"Task error details: {e}")
        update_task(task_id, "failed", f"Failed: {str(e)}")

    finally:
        # Clean up temporary task subdirectories
        try:
            if os.path.exists(task_temp_dir):
                shutil.rmtree(task_temp_dir)
        except Exception as e:
            print(f"Cleanup warning: {e}")

@app.route("/", methods=["GET"])
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>BeatFit Companion Server</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {
                font-family: 'Inter', sans-serif;
                background-color: #0a0b0e;
                color: #f3f4f6;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-image: 
                    radial-gradient(circle at 100% 0%, rgba(236, 72, 153, 0.08) 0%, transparent 40%),
                    radial-gradient(circle at 0% 100%, rgba(139, 92, 246, 0.08) 0%, transparent 40%);
            }
            .card {
                background: rgba(20, 22, 28, 0.65);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.07);
                padding: 30px;
                border-radius: 16px;
                text-align: center;
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
                max-width: 400px;
                width: 90%;
            }
            h1 {
                margin: 0 0 10px 0;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: -0.025em;
            }
            .accent {
                background: linear-gradient(90deg, #06b6d4, #8b5cf6);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            .status-badge {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                background: rgba(34, 197, 94, 0.1);
                border: 1px solid rgba(34, 197, 94, 0.3);
                color: #4ade80;
                padding: 6px 14px;
                border-radius: 99px;
                font-size: 13px;
                font-weight: 600;
                margin-top: 15px;
            }
            .dot {
                width: 8px;
                height: 8px;
                background-color: #22c55e;
                border-radius: 50%;
                box-shadow: 0 0 8px #22c55e;
            }
            p {
                color: #9ca3af;
                font-size: 14px;
                margin: 15px 0 0 0;
                line-height: 1.6;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>BeatFit <span class="accent">Companion Server</span></h1>
            <div class="status-badge">
                <span class="dot"></span>
                <span>Online & Ready</span>
            </div>
            <p>The companion server is running successfully on port 5001 and listening for requests from the Chrome Extension.</p>
        </div>
    </body>
    </html>
    """

@app.route("/process", methods=["POST"])
def process_map():
    data = request.json or {}
    youtube_url = data.get("youtube_url")
    
    if not youtube_url:
        return jsonify({"error": "Missing youtube_url parameter"}), 400
        
    difficulties = data.get("difficulties", ["Normal", "Hard", "Expert", "ExpertPlus"])
    modes = data.get("modes", ["Standard"])
    events = data.get("events", ["Obstacles"])
    push_to_quest = bool(data.get("push_to_quest", False))
    
    task_id = str(uuid.uuid4())
    
    with tasks_lock:
        tasks[task_id] = {
            "id": task_id,
            "youtube_url": youtube_url,
            "song_title": "Detecting...",
            "song_artist": "Detecting...",
            "status": "queued",
            "message": "Task queued, initiating background worker...",
            "progress": 0,
            "download_url": None,
            "created_at": time.time()
        }
        
    # Start thread
    thread = threading.Thread(
        target=process_youtube_map_task, 
        args=(task_id, youtube_url, difficulties, modes, events, push_to_quest)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({"task_id": task_id})

@app.route("/status/<task_id>", methods=["GET"])
def get_status(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
        
    if not task:
        return jsonify({"error": "Task not found"}), 404
        
    return jsonify(task)

@app.route("/status", methods=["GET"])
def get_all_status():
    with tasks_lock:
        return jsonify(list(tasks.values()))

@app.route("/downloads/<filename>", methods=["GET"])
def download_file(filename):
    # Sanitize filename parameter for security
    filename = os.path.basename(filename)
    return send_from_directory(TEMP_DIR, filename, as_attachment=True)

@app.route("/quest/status", methods=["GET"])
def quest_status():
    try:
        devices_res = quest_injector.run_adb_command(["devices"])
        devices_lines = devices_res.stdout.strip().split("\n")
        # filter device names
        connected_devices = []
        for line in devices_lines[1:]:
            if line.strip():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    connected_devices.append(parts[0])
        
        return jsonify({
            "connected": len(connected_devices) > 0,
            "devices": connected_devices
        })
    except Exception as e:
        return jsonify({
            "connected": False,
            "error": str(e)
        })

if __name__ == "__main__":
    print("--------------------------------------------------")
    print("      BeatFit Companion Local Python Server       ")
    print("--------------------------------------------------")
    print(f"Workspace Directory: {BASE_DIR}")
    print(f"Processing Temp Directory: {TEMP_DIR}")
    print("Running on http://localhost:5001")
    print("Press Ctrl+C to quit.")
    print("--------------------------------------------------")
    
    # Run server locally on port 5001
    app.run(host="localhost", port=5001, debug=True, use_reloader=False)
