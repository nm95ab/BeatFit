import json
import os
import subprocess
import shutil

# Import the existing fitbeat generator
import fitbeat

def run_adb_command(args, capture=True):
    """Helper to run adb commands"""
    cmd = ["adb"] + args
    result = subprocess.run(cmd, capture_output=capture, text=True)
    return result

def get_quest_custom_songs(base_path):
    """Scans the Quest via ADB and returns a list of song folder names."""
    print("Scanning your Quest for custom songs...")
    result = run_adb_command(["shell", f"ls -1 {base_path}"])

    if result.returncode != 0 or not result.stdout.strip():
        print("Error: Could not find any custom songs or device is offline.")
        return []

    # Clean the output into a python list of folders
    folders = [f.strip() for f in result.stdout.split("\n") if f.strip()]
    return folders

def get_highest_difficulty_map(info_data):
    """Parses info.dat to find the highest difficulty beatmap filename."""
    difficulty_order = ["ExpertPlus", "Expert", "Hard", "Normal", "Easy"]
    
    # Check for V2 info.dat schema
    if "_difficultyBeatmapSets" in info_data:
        for ds in info_data["_difficultyBeatmapSets"]:
            if ds.get("_beatmapCharacteristicName") == "Standard":
                beatmaps = ds.get("_difficultyBeatmaps", [])
                # Create a dict mapping difficulty name to filename
                diff_map = {b.get("_difficulty"): b for b in beatmaps}
                for diff in difficulty_order:
                    if diff in diff_map:
                        return diff_map[diff].get("_beatmapFilename"), diff, diff_map[diff]
                        
    # Check for V3 info.dat schema
    elif "difficultyBeatmaps" in info_data:
        beatmaps = info_data["difficultyBeatmaps"]
        diff_map = {b.get("difficulty"): b for b in beatmaps if b.get("characteristic") == "Standard"}
        for diff in difficulty_order:
            if diff in diff_map:
                return diff_map[diff].get("beatmapAuthors", diff_map[diff].get("beatmapDataFilename")), diff, diff_map[diff]

    return None, None, None

def add_fitbeat_to_info(info_path, highest_diff_obj, new_filename, is_v2):
    """Modifies info.dat to include the new FitBeat extra level."""
    with open(info_path, 'r', encoding='utf-8') as f:
        info_data = json.load(f)

    # We will try to add it as a new Characteristic called "FitBeat" 
    # so it doesn't overwrite the original Standard difficulties.
    if is_v2:
        new_set = {
            "_beatmapCharacteristicName": "Lawless", # Lawless is a natively supported extra tab
            "_difficultyBeatmaps": [
                {
                    "_difficulty": highest_diff_obj.get("_difficulty", "ExpertPlus"),
                    "_difficultyRank": highest_diff_obj.get("_difficultyRank", 9),
                    "_beatmapFilename": new_filename,
                    "_noteJumpMovementSpeed": highest_diff_obj.get("_noteJumpMovementSpeed", 16),
                    "_noteJumpStartBeatOffset": highest_diff_obj.get("_noteJumpStartBeatOffset", 0),
                    "_customData": {
                        "_difficultyLabel": "FitBeat"
                    }
                }
            ]
        }
        
        # Remove old Lawless if it exists, or just append
        info_data["_difficultyBeatmapSets"] = [ds for ds in info_data.get("_difficultyBeatmapSets", []) if ds.get("_beatmapCharacteristicName") != "Lawless"]
        info_data["_difficultyBeatmapSets"].append(new_set)

    else:
        # V3
        new_beatmap = highest_diff_obj.copy()
        new_beatmap["characteristic"] = "Lawless"
        new_beatmap["beatmapDataFilename"] = new_filename
        if "customData" not in new_beatmap:
            new_beatmap["customData"] = {}
        new_beatmap["customData"]["difficultyLabel"] = "FitBeat"
        
        # Remove old Lawless if it exists
        info_data["difficultyBeatmaps"] = [b for b in info_data.get("difficultyBeatmaps", []) if b.get("characteristic") != "Lawless"]
        info_data["difficultyBeatmaps"].append(new_beatmap)

    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump(info_data, f, indent=2)

def main():
    # Standard path for custom levels on modded standalone Quest
    quest_base_path = "/sdcard/ModData/com.beatgames.beatsaber/Mods/SongLoader/CustomLevels/"
    
    # Temporary local processing directory
    temp_dir = os.path.expanduser("~/Desktop/FitBeat_Temp")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    songs = get_quest_custom_songs(quest_base_path)
    if not songs:
        return

    # --- GRAND LOOP ---
    show_list = True
    while True:
        # --- MENU INTERFACE ---
        displayed_songs = songs
        songs_to_process = []

        while True:
            if show_list:
                print("\n==============================")
                print("      FITBEAT MAP INJECTOR    ")
                print("==============================")
                print("0. [PROCESS ALL DISPLAYED SONGS]")
                for idx, song in enumerate(displayed_songs, start=1):
                    print(f"{idx}. {song}")
                show_list = False

            user_input = input("\nSelect a number, type a substring to filter, 'del <num>' to delete, 'all' to reset, 'l' to list, or 'q' to quit: ").strip()

            if not user_input:
                continue
                
            if user_input.lower() == 'q':
                print("Exiting...")
                return
                
            if user_input.lower() == 'l':
                show_list = True
                continue
                
            if user_input.lower() == 'all':
                displayed_songs = songs
                show_list = True
                continue

            # Check for delete command
            if user_input.lower().startswith('del ') or user_input.lower().startswith('d '):
                try:
                    parts = user_input.split()
                    if len(parts) >= 2:
                        del_idx = int(parts[1])
                        if 1 <= del_idx <= len(displayed_songs):
                            song_to_delete = displayed_songs[del_idx - 1]
                            confirm = input(f"Are you sure you want to completely delete '{song_to_delete}' from your Quest? (y/n): ").strip().lower()
                            if confirm == 'y':
                                print(f"Deleting '{song_to_delete}'...")
                                remote_song_folder = f"{quest_base_path}{song_to_delete}/"
                                run_adb_command(["shell", "rm", "-rf", remote_song_folder])
                                if song_to_delete in songs:
                                    songs.remove(song_to_delete)
                                if song_to_delete in displayed_songs:
                                    displayed_songs.remove(song_to_delete)
                                print("Song deleted successfully.")
                                show_list = True
                            else:
                                print("Deletion cancelled.")
                            continue
                        else:
                            print("Invalid song number to delete.")
                            continue
                except ValueError:
                    pass

            try:
                choice = int(user_input)
                
                # Determine which songs to process based on input
                if choice == 0:
                    songs_to_process = displayed_songs
                    print(f"\nBatch processing started for {len(displayed_songs)} songs...")
                    break
                elif 1 <= choice <= len(displayed_songs):
                    songs_to_process = [displayed_songs[choice - 1]]
                    break
                else:
                    print("Invalid choice selection. Try again.")
                    
            except ValueError:
                # If the user didn't enter a number, filter the list!
                filtered = [s for s in songs if user_input.lower() in s.lower()]
                if filtered:
                    displayed_songs = filtered
                    show_list = True
                else:
                    print(f"\nNo songs found containing '{user_input}'. Try again.")

        # --- PROCESSING LOOP ---
        for current_song in songs_to_process:
            print(f"\n--- Processing: {current_song} ---")
            remote_song_folder = f"{quest_base_path}{current_song}/"
            
            local_info_path = os.path.join(temp_dir, "info.dat")
            
            # 1. Pull info.dat to find the highest difficulty
            pull_info = run_adb_command(["pull", remote_song_folder + "info.dat", local_info_path])
            if pull_info.returncode != 0:
                # Try uppercase Info.dat
                pull_info = run_adb_command(["pull", remote_song_folder + "Info.dat", local_info_path])
                if pull_info.returncode != 0:
                    print("-> Skipped: Could not find info.dat or Info.dat")
                    continue

            with open(local_info_path, 'r', encoding='utf-8') as f:
                info_data = json.load(f)
                
            is_v2 = "_version" in info_data and info_data["_version"].startswith("2.")

            # Find the hardest map
            highest_file, diff_name, diff_obj = get_highest_difficulty_map(info_data)
            if not highest_file:
                print("-> Skipped: Could not parse difficulties from info.dat.")
                continue

            print(f"-> Highest difficulty found: {diff_name} ({highest_file})")

            # 2. Pull the hardest map file
            local_map_path = os.path.join(temp_dir, highest_file)
            pull_map = run_adb_command(["pull", remote_song_folder + highest_file, local_map_path])
            if pull_map.returncode != 0:
                print(f"-> Skipped: Failed to pull {highest_file}")
                continue

            # 3. Generate the FitBeat map locally
            fitbeat_filename = "FitBeat.dat"
            local_fitbeat_path = os.path.join(temp_dir, fitbeat_filename)
            
            print("-> Generating FitBeat workout level...")
            try:
                # We call the process_map function from your original script
                fitbeat.process_map(local_map_path, local_fitbeat_path)
                
                # Update info.dat to register the new level
                add_fitbeat_to_info(local_info_path, diff_obj, fitbeat_filename, is_v2)
                
                # 4. Push the new map and updated info.dat back to the Quest
                print("-> Pushing new Extra Level back to Quest...")
                push_map = run_adb_command(["push", local_fitbeat_path, remote_song_folder + fitbeat_filename])
                
                # Use original casing for info.dat
                remote_info_name = "Info.dat" if "Info.dat" in pull_info.args[2] else "info.dat"
                push_info = run_adb_command(["push", local_info_path, remote_song_folder + remote_info_name])
                
                if push_map.returncode == 0 and push_info.returncode == 0:
                    print(f"-> Success! Created new 'FitBeat' level under the 'Lawless' tab.")
                else:
                    print("-> Error pushing files back to Quest.")
                    
            except Exception as e:
                print(f"-> Error generating fitbeat map: {e}")

            # Clean up local temp files for this song
            for f in [local_info_path, local_map_path, local_fitbeat_path]:
                if os.path.exists(f):
                    os.remove(f)

        print("\nExecution Finished! Returning to menu...")

if __name__ == "__main__":
    main()
