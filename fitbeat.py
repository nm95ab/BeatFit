import json
import os
import random
import sys

def process_map(filepath, output_filepath=None):
    if not output_filepath:
        base, ext = os.path.splitext(filepath)
        output_filepath = f"{base}_FitBeat{ext}"

    with open(filepath, 'r', encoding='utf-8') as f:
        map_data = json.load(f)

    is_v2 = False
    if "_version" in map_data and map_data["_version"].startswith("2."):
        is_v2 = True
    elif "version" in map_data and map_data["version"].startswith("3."):
        is_v2 = False
    else:
        print(f"Warning: File {filepath} version not recognized. Assuming V3.")
        is_v2 = False

    # Try to find info.dat to get BPM
    bpm = 120.0
    info_path = os.path.join(os.path.dirname(filepath), 'info.dat')
    if not os.path.exists(info_path):
        info_path = os.path.join(os.path.dirname(filepath), 'Info.dat')
    if os.path.exists(info_path):
        try:
            with open(info_path, 'r', encoding='utf-8') as info_f:
                info_data = json.load(info_f)
                bpm = float(info_data.get('_beatsPerMinute', 120.0))
        except Exception:
            pass
    
    cold_period_seconds = 2.0
    cold_period_beats = (cold_period_seconds / 60.0) * bpm

    all_objects = []

    if is_v2:
        notes = map_data.get("_notes", [])
        obs = map_data.get("_obstacles", [])
        
        for n in notes:
            t = 'bomb' if n.get('_type') == 3 else 'note'
            all_objects.append({'type': t, 'b': n['_time'], 'x': n['_lineIndex'], 'y': n.get('_lineLayer', 0)})
        for o in obs:
            end_beat = o['_time'] + o.get('_duration', 0)
            all_objects.append({'type': 'obstacle', 'b': o['_time'], 'end_b': end_beat})
    else:
        color_notes = map_data.get("colorNotes", [])
        bomb_notes = map_data.get("bombNotes", [])
        obs = map_data.get("obstacles", [])
        
        for n in color_notes:
            all_objects.append({'type': 'note', 'b': n['b'], 'x': n['x'], 'y': n.get('y', 0)})
        for n in bomb_notes:
            all_objects.append({'type': 'bomb', 'b': n['b'], 'x': n['x'], 'y': n.get('y', 0)})
        for o in obs:
            end_beat = o['b'] + o.get('d', 0)
            all_objects.append({'type': 'obstacle', 'b': o['b'], 'end_b': end_beat})

    # Add a dummy object at beat 0 to represent the start of the map if it's empty early on
    all_objects.append({'type': 'start', 'b': 0, 'end_b': 0})

    all_objects.sort(key=lambda obj: obj['b'])
    new_obstacles = []

    for i in range(len(all_objects) - 1):
        curr_obj = all_objects[i]
        next_obj = all_objects[i+1]

        curr_end = curr_obj.get('end_b', curr_obj['b'])
        next_start = next_obj['b']
        gap = next_start - curr_end

        # --- FITNESS INTENSITY SETTINGS ---
        # Lower these numbers to make the script MUCH more aggressive
        wall_duration = 1.25  # How long you hold the squat (1.5 beats)
        entry_buffer = 0.5   # Beats to wait after the last note before wall appears
        exit_buffer = 0.75  # Beats to give you time to see the next note after the wall
        
        min_required_gap = entry_buffer + wall_duration + exit_buffer

        if gap >= min_required_gap:
            wall_start = curr_end + entry_buffer

            # Enforce 2-second cold period
            if wall_start < cold_period_beats:
                wall_start = cold_period_beats
            
            # Check if we still have the exit buffer after adjusting for the cold period
            if (next_start - wall_start) >= (wall_duration + exit_buffer):
                if gap >= 8.0:
                    # SUSTAINED SQUAT TUNNEL
                    tunnel_duration = (next_start - exit_buffer) - wall_start
                    if is_v2:
                        new_obstacles.append({"_time": wall_start, "_lineIndex": 0, "_type": 1, "_duration": tunnel_duration, "_width": 4})
                    else:
                        new_obstacles.append({"b": wall_start, "x": 0, "y": 2, "d": tunnel_duration, "w": 4, "h": 3})
                else:
                    # Duck
                    if is_v2:
                        new_obstacles.append({"_time": wall_start, "_lineIndex": 0, "_type": 1, "_duration": wall_duration, "_width": 4})
                    else:
                        new_obstacles.append({"b": wall_start, "x": 0, "y": 2, "d": wall_duration, "w": 4, "h": 3})

    # Add Pass 1 obstacles to all_objects for Pass 2 collision detection
    for o in new_obstacles:
        b = o.get('_time', o.get('b'))
        d = o.get('_duration', o.get('d', 0))
        all_objects.append({'type': 'obstacle', 'b': b, 'end_b': b + d})
    all_objects.sort(key=lambda obj: obj['b'])

    # PASS 2: LEAN WALLS (Over one-sided note streams)
    min_lean_duration = 2.0
    lean_entry_buffer = 0.5
    lean_exit_buffer = 0.5
    lean_obstacles = []

    def check_and_add_lean(start_note, end_note, side):
        if not start_note or not end_note: return
        start_b = start_note['b']
        end_b = end_note['b']
        duration = end_b - start_b
        if duration >= min_lean_duration:
            wall_start = start_b - lean_entry_buffer
            if wall_start < cold_period_beats:
                wall_start = cold_period_beats
            wall_end = end_b + lean_exit_buffer
            if wall_end <= wall_start:
                return

            collision = False
            for obj in all_objects:
                if obj['type'] in ('obstacle', 'bomb'):
                    obj_s = obj['b']
                    obj_e = obj.get('end_b', obj['b'])
                    if max(wall_start, obj_s) < min(wall_end, obj_e):
                        collision = True
                        break
            
            # Check against other lean walls to ensure we have physical time to transition
            min_lean_transition = 1.0  # Need at least 1 beat to move body across the play space
            if not collision:
                for lean_obs in lean_obstacles:
                    if is_v2:
                        obj_s = lean_obs["_time"]
                        obj_e = obj_s + lean_obs["_duration"]
                    else:
                        obj_s = lean_obs["b"]
                        obj_e = obj_s + lean_obs["d"]
                    
                    # If the new wall doesn't have enough buffer before or after an existing lean wall, reject it
                    if not (wall_start >= obj_e + min_lean_transition or wall_end <= obj_s - min_lean_transition):
                        collision = True
                        break
            
            if not collision:
                wall_d = wall_end - wall_start
                if side == 'left': # Notes left -> Wall Right (force dodge left)
                    if is_v2:
                        lean_obstacles.append({"_time": wall_start, "_lineIndex": 2, "_type": 0, "_duration": wall_d, "_width": 2})
                    else:
                        lean_obstacles.append({"b": wall_start, "x": 2, "y": 0, "d": wall_d, "w": 2, "h": 5})
                else: # Notes right -> Wall Left
                    if is_v2:
                        lean_obstacles.append({"_time": wall_start, "_lineIndex": 0, "_type": 0, "_duration": wall_d, "_width": 2})
                    else:
                        lean_obstacles.append({"b": wall_start, "x": 0, "y": 0, "d": wall_d, "w": 2, "h": 5})

    pure_notes = [obj for obj in all_objects if obj['type'] in ('note', 'bomb')]
    current_side = None
    seq_start_note = None
    seq_end_note = None

    for n in pure_notes:
        if n['type'] == 'bomb':
            check_and_add_lean(seq_start_note, seq_end_note, current_side)
            current_side = None
            seq_start_note = None
            seq_end_note = None
            continue
            
        x = n['x']
        side = 'left' if x <= 1 else 'right'
        if current_side == side:
            seq_end_note = n
        else:
            check_and_add_lean(seq_start_note, seq_end_note, current_side)
            current_side = side
            seq_start_note = n
            seq_end_note = n

    check_and_add_lean(seq_start_note, seq_end_note, current_side)

    # Add Pass 2 obstacles to all_objects for Pass 3 collision detection
    for o in lean_obstacles:
        b = o.get('_time', o.get('b'))
        d = o.get('_duration', o.get('d', 0))
        all_objects.append({'type': 'obstacle', 'b': b, 'end_b': b + d})
    all_objects.sort(key=lambda obj: obj['b'])

    # PASS 3: SQUAT SEQUENCES (Over low note streams)
    min_duck_duration = 2.0
    duck_entry_buffer = 0.5
    duck_exit_buffer = 0.5
    sequence_duck_obstacles = []

    def check_and_add_duck(start_note, end_note, is_low):
        if not start_note or not end_note or not is_low: return
        start_b = start_note['b']
        end_b = end_note['b']
        duration = end_b - start_b
        if duration >= min_duck_duration:
            wall_start = start_b - duck_entry_buffer
            if wall_start < cold_period_beats:
                wall_start = cold_period_beats
            wall_end = end_b + duck_exit_buffer
            if wall_end <= wall_start:
                return

            collision = False
            for obj in all_objects:
                if obj['type'] in ('obstacle', 'bomb'):
                    obj_s = obj['b']
                    obj_e = obj.get('end_b', obj['b'])
                    if max(wall_start, obj_s) < min(wall_end, obj_e):
                        collision = True
                        break
            
            min_duck_transition = 1.0
            if not collision:
                for duck_obs in sequence_duck_obstacles:
                    if is_v2:
                        obj_s = duck_obs["_time"]
                        obj_e = obj_s + duck_obs["_duration"]
                    else:
                        obj_s = duck_obs["b"]
                        obj_e = obj_s + duck_obs["d"]
                    
                    if not (wall_start >= obj_e + min_duck_transition or wall_end <= obj_s - min_duck_transition):
                        collision = True
                        break
            
            if not collision:
                wall_d = wall_duration # Use the standard 1.25 beat quick duck!
                if is_v2:
                    sequence_duck_obstacles.append({"_time": wall_start, "_lineIndex": 0, "_type": 1, "_duration": wall_d, "_width": 4, "is_squat_seq": True})
                else:
                    sequence_duck_obstacles.append({"b": wall_start, "x": 0, "y": 2, "d": wall_d, "w": 4, "h": 3, "is_squat_seq": True})

    current_is_low = False
    seq_start_note = None
    seq_end_note = None

    for n in pure_notes:
        if n['type'] == 'bomb':
            check_and_add_duck(seq_start_note, seq_end_note, current_is_low)
            current_is_low = False
            seq_start_note = None
            seq_end_note = None
            continue
            
        y = n.get('y', 0)
        is_low = (y == 0)
        if current_is_low == is_low:
            seq_end_note = n
        else:
            check_and_add_duck(seq_start_note, seq_end_note, current_is_low)
            current_is_low = is_low
            seq_start_note = n
            seq_end_note = n

    check_and_add_duck(seq_start_note, seq_end_note, current_is_low)

    all_new_obstacles = new_obstacles + lean_obstacles + sequence_duck_obstacles

    ducks = 0
    tunnels = 0
    left_dodges = 0
    right_dodges = 0
    squat_seqs = 0

    print("\n--- Fitness Obstacle Breakdown ---")
    if all_new_obstacles:
        for obs in all_new_obstacles:
            is_squat_seq = obs.get("is_squat_seq", False)
            if is_v2:
                obs_x = obs["_lineIndex"]
                obs_w = obs["_width"]
                obs_d = obs["_duration"]
                start_beat = obs["_time"]
            else:
                obs_x = obs["x"]
                obs_w = obs["w"]
                obs_d = obs["d"]
                start_beat = obs["b"]

            start_seconds = (start_beat / bpm) * 60.0
            duration_seconds = (obs_d / bpm) * 60.0

            if is_squat_seq:
                squat_seqs += 1
                print(f"[Beat: {start_beat:6.2f} | Time: {start_seconds:6.2f}s] -> Quick Duck (Low Notes)")
            elif obs_w == 4:
                if obs_d > wall_duration: # It's a tunnel!
                    tunnels += 1
                    print(f"[Beat: {start_beat:6.2f} | Time: {start_seconds:6.2f}s] -> SQUAT TUNNEL ({duration_seconds:.1f} sec hold)")
                else:
                    ducks += 1
                    print(f"[Beat: {start_beat:6.2f} | Time: {start_seconds:6.2f}s] -> Overhead Duck Wall (Gap)")
            elif obs_x >= 2:
                left_dodges += 1
                print(f"[Beat: {start_beat:6.2f} | Time: {start_seconds:6.2f}s] -> Right Wall (Force Dodge Left)")
            elif obs_x <= 1:
                right_dodges += 1
                print(f"[Beat: {start_beat:6.2f} | Time: {start_seconds:6.2f}s] -> Left Wall (Force Dodge Right)")
    else:
        print("No gaps or streams were large enough to safely insert a fitness obstacle.")

    print(f"Total: {tunnels} Squat Tunnels, {ducks} Ducks, {left_dodges} Left Dodges, {right_dodges} Right Dodges, {squat_seqs} Squat Sequences.")
    
    if is_v2:
        for o in all_new_obstacles:
            o.pop("is_squat_seq", None)
        map_data.setdefault("_obstacles", []).extend(all_new_obstacles)
        map_data["_obstacles"].sort(key=lambda o: o['_time'])
    else:
        for o in all_new_obstacles:
            o.pop("is_squat_seq", None)
        map_data.setdefault("obstacles", []).extend(all_new_obstacles)
        map_data["obstacles"].sort(key=lambda o: o['b'])

    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(map_data, f, indent=2)
    
    print(f"\nProcessed {filepath} -> added {len(all_new_obstacles)} fitness obstacles to {output_filepath}")
    
    return all_new_obstacles
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fitbeat.py <path_to_map.dat> [output_path.dat]")
        sys.exit(1)
    
    filepath = sys.argv[1]
    outpath = sys.argv[2] if len(sys.argv) > 2 else None
    process_map(filepath, outpath)
