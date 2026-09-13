#!/usr/bin/env python3
import subprocess
import re
import curses
import time

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def get_remaining_packages():
    output = run_cmd(["emerge", "--resume", "--pretend"])
    if not output:
        return []
        
    packages = []
    for line in output.splitlines():
        if line.strip().startswith("[ebuild"):
            packages.append(line.strip())
    return packages

def extract_pkg_atom(ebuild_line):
    parts = ebuild_line.split()
    for part in parts:
        if "/" in part and "::" in part:
            atom_full = part.split("::")[0]
            return re.sub(r'-[0-9].*', '', atom_full)
    return None

def clean_atom(raw_atom):
    if not raw_atom:
        return ""
    cleaned = raw_atom.rstrip('.')
    return re.sub(r'-[0-9].*', '', cleaned)

def parse_time_to_seconds(time_str):
    if not time_str:
        return 0
    seconds = 0
    # Flexible search for hours, minutes, and seconds
    h_match = re.search(r'(\d+)\s*(?:h|sat|hour)', time_str, re.IGNORECASE)
    if h_match:
        seconds += int(h_match.group(1)) * 3600
        
    m_match = re.search(r'(\d+)\s*(?:m|min|′)', time_str, re.IGNORECASE)
    if m_match:
        seconds += int(m_match.group(1)) * 60
        
    s_match = re.search(r'(\d+)\s*(?:s|sec|″)', time_str, re.IGNORECASE)
    if s_match:
        seconds += int(s_match.group(1))
        
    # Fallback if qlop returns in HH:MM:SS format
    if seconds == 0 and ":" in time_str:
        parts = time_str.strip().split(":")
        try:
            if len(parts) == 3:
                seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                seconds = int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
            
    return seconds

def seconds_to_hhmmss(total_seconds):
    if total_seconds <= 0:
        return "00:00:00"
    total_seconds = int(total_seconds)
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def get_average_qlop_time(atom):
    output = run_cmd(["qlop", "-t", atom])
    if not output:
        return None
        
    durations = []
    for line in output.splitlines():
        if ">>>" in line and ":" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                time_part = ":".join(parts[1:]).strip()
                secs = parse_time_to_seconds(time_part)
                if secs > 0:
                    durations.append(secs)
                    
    if not durations:
        return None
    return sum(durations) / len(durations)

def get_current_package_info():
    raw_status = run_cmd(["qlop", "-r"])
    if not raw_status:
        return "No active compilation", 0
        
    atom = "Unknown"
    current_secs = 0
    
    match_atom = re.search(r'>>>\s+([^\s]+)', raw_status)
    if match_atom:
        atom = clean_atom(match_atom.group(1))
        
    match_eta = re.search(r'ETA:\s*([^\n]+)', raw_status)
    if match_eta:
        current_secs = parse_time_to_seconds(match_eta.group(1).strip())
            
    return atom, current_secs

def load_initial_packages():
    # Executed ONLY ONCE at startup
    raw_packages = get_remaining_packages()
    base_data = []
    
    for ebuild in raw_packages:
        atom = extract_pkg_atom(ebuild)
        if not atom:
            continue
        base_data.append(atom)
        
    return base_data

def build_display_list(base_packages, current_atom, time_cache):
    cleaned_current = clean_atom(current_atom)
    
    packages = []
    remaining_seconds_sum = 0
    counter = 1

    for atom in base_packages:
        # If it's the currently compiling package, skip it in the remaining list
        if clean_atom(atom) == cleaned_current:
            continue
            
        # Get or load package time from cache
        if atom in time_cache:
            avg_secs = time_cache[atom]
        else:
            avg_secs = get_average_qlop_time(atom)
            time_cache[atom] = avg_secs

        eta_str = "N/A"
        if avg_secs:
            remaining_seconds_sum += avg_secs
            eta_str = seconds_to_hhmmss(avg_secs)
            
        packages.append((str(counter), atom, eta_str))
        counter += 1

    return packages, remaining_seconds_sum

def draw_ui(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(1000)

    stdscr.clear()
    max_y, max_x = stdscr.getmaxyx()
    loading_msg = "Initializing, please wait..."
    if max_y > 0 and max_x > len(loading_msg):
        stdscr.addstr(max_y // 2, (max_x - len(loading_msg)) // 2, loading_msg, curses.A_BOLD)
    stdscr.refresh()

    # 1. One-time fetch of the entire list from emerge
    base_packages = load_initial_packages()
    time_cache = {}
    
    current_atom, current_secs = get_current_package_info()
    
    # If the current package is in the remaining list, permanently remove it from the base list
    cleaned_current = clean_atom(current_atom)
    if cleaned_current in [clean_atom(a) for a in base_packages]:
        base_packages = [a for a in base_packages if clean_atom(a) != cleaned_current]

    packages, remaining_seconds_sum = build_display_list(base_packages, current_atom, time_cache)
    total_seconds_all = current_secs + remaining_seconds_sum
    total_items = len(packages)

    scroll_pos = 0
    last_qlop_check = time.time()
    last_known_atom = current_atom

    while True:
        current_time = time.time()
        
        # Check qlop every 5 seconds
        if current_time - last_qlop_check >= 5:
            new_atom, new_secs = get_current_package_info()
            
            # If the current package changed (previous one finished)
            if new_atom != last_known_atom:
                # Permanently remove the old (now completed) package from the base list if present
                old_cleaned = clean_atom(last_known_atom)
                base_packages = [a for a in base_packages if clean_atom(a) != old_cleaned]
                
                last_known_atom = new_atom
            
            current_atom = new_atom
            if new_secs > 0:
                current_secs = new_secs
                
            packages, remaining_seconds_sum = build_display_list(base_packages, current_atom, time_cache)
            total_items = len(packages)
            total_seconds_all = current_secs + remaining_seconds_sum
            
            last_qlop_check = current_time

        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()

        if max_y < 10 or max_x < 30:
            stdscr.addstr(0, 0, "Terminal window is too small!")
            stdscr.refresh()
            key = stdscr.getch()
            if key == ord('q') or key == ord('Q'):
                break
            continue

        col1_w = 8    
        col3_w = 12   
        col2_w = max(10, max_x - col1_w - col3_w - 4)  

        # 1. Current package
        stdscr.addstr(0, 0, "[Current Package]", curses.A_BOLD)
        
        cur_header_y = 1
        header_str = f" {'No.':<{col1_w}} | {'Package Name':<{col2_w}} | {'ETA':<{col3_w}} "
        try:
            stdscr.addstr(cur_header_y, 0, header_str[:max_x - 1], curses.A_REVERSE)
        except curses.error:
            pass

        cur_row_y = 2
        cur_atom_display = current_atom
        if len(cur_atom_display) > col2_w:
            cur_atom_display = cur_atom_display[:col2_w - 3] + "..."
            
        cur_eta_str = seconds_to_hhmmss(current_secs) if current_secs > 0 else "N/A"
        cur_row_str = f" {'*':<{col1_w}} | {cur_atom_display:<{col2_w}} | {cur_eta_str:<{col3_w}} "
        try:
            stdscr.addstr(cur_row_y, 0, cur_row_str[:max_x - 1])
        except curses.error:
            pass

        stdscr.addstr(3, 0, "-" * min(max_x, 60))

        # 2. Remaining packages section header
        header_line = 4
        total_eta_str = seconds_to_hhmmss(total_seconds_all) if total_seconds_all > 0 else "N/A"
        info_text = f"[Remaining Packages] Total: {total_items} | Total ETA: {total_eta_str}"
        stdscr.addstr(header_line, 0, info_text[:max_x - 1], curses.A_BOLD)

        # 3. Remaining packages table header
        table_header_y = 5
        try:
            stdscr.addstr(table_header_y, 0, header_str[:max_x - 1], curses.A_REVERSE)
        except curses.error:
            pass

        # 4. Remaining packages table rows
        list_start_y = table_header_y + 1
        bottom_bar_y = max_y - 1
        available_height = bottom_bar_y - list_start_y

        if available_height > 0:
            if scroll_pos < 0:
                scroll_pos = 0
            if scroll_pos > max(0, total_items - available_height):
                scroll_pos = max(0, total_items - available_height)

            for i in range(available_height):
                idx = scroll_pos + i
                if idx < total_items:
                    rb, atom, eta = packages[idx]
                    
                    if len(atom) > col2_w:
                        atom = atom[:col2_w - 3] + "..."

                    row_str = f" {rb:<{col1_w}} | {atom:<{col2_w}} | {eta:<{col3_w}} "
                    try:
                        stdscr.addstr(list_start_y + i, 0, row_str[:max_x - 1])
                    except curses.error:
                        pass

        # 5. Bottom fixed instruction bar
        footer_text = "Navigation: Arrows, PgUp/PgDown, Home/End | Exit: q"
        try:
            stdscr.addstr(bottom_bar_y, 0, footer_text[:max_x - 1], curses.A_STANDOUT)
        except curses.error:
            pass

        stdscr.refresh()

        if current_secs > 0:
            current_secs -= 1
        if total_seconds_all > 0:
            total_seconds_all -= 1

        try:
            key = stdscr.getch()
        except:
            key = -1

        if key == ord('q') or key == ord('Q'):
            break
        elif key == curses.KEY_DOWN:
            if scroll_pos < total_items - 1:
                scroll_pos += 1
        elif key == curses.KEY_UP:
            if scroll_pos > 0:
                scroll_pos -= 1
        elif key == curses.KEY_NPAGE:
            scroll_pos += available_height
        elif key == curses.KEY_PPAGE:
            scroll_pos -= available_height
        elif key == curses.KEY_HOME:
            scroll_pos = 0
        elif key == curses.KEY_END:
            scroll_pos = max(0, total_items - available_height)

def main():
    try:
        curses.wrapper(draw_ui)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
