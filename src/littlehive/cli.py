import sys
import os
import signal
import subprocess
import time
from littlehive.agent.paths import LITTLEHIVE_DIR, ensure_paths

PID_FILE = os.path.join(LITTLEHIVE_DIR, "littlehive.pid")
LOG_FILE = os.path.join(LITTLEHIVE_DIR, "logs", "agent.log")

def get_pid():
    if os.path.exists(PID_FILE):
        with open(PID_FILE, 'r') as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return None
    return None

def is_running(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def start():
    pid = get_pid()
    if is_running(pid):
        print(f"Agent is already running (PID: {pid}).")
        return

    ensure_paths()
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    # Get current log size to tail from this exact point
    log_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0

    # Run the main module in background
    with open(LOG_FILE, 'a') as log_out:
        process = subprocess.Popen(
            [sys.executable, "-m", "littlehive.agent.start_agent"],
            stdout=log_out,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
    
    with open(PID_FILE, 'w') as f:
        f.write(str(process.pid))
    
    # --- Foreground monitoring ---
    sys.stdout.write("Starting LittleHive agent in the background...\n")
    
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    current_status = "Initializing..."
    
    with open(LOG_FILE, 'r') as f:
        f.seek(log_size)
        while True:
            line = f.readline()
            if line:
                line = line.strip()
                if "Initializing Core Brain & loading model" in line:
                    current_status = "Loading AI Model (Patience is a virtue.. mostly 😉)"
                elif "Fetching" in line and "huggingface" in line:
                    current_status = "Downloading AI Model (This might take a few minutes...)"
                elif "Pre-warming prompt cache" in line:
                    current_status = "Warming up neural cache for fast responses"
                elif "Starting Web Dashboard" in line:
                    current_status = "Starting local servers"
                elif "All senses active" in line:
                    sys.stdout.write(f"\r\033[K✨ LittleHive is fully awake and ready!\n")
                    print(f"✅ Agent running in background (PID: {process.pid})")
                    print(f"📝 Logs: {LOG_FILE}")
                    print("🌐 Dashboard available at: http://localhost:8080")
                    break
            else:
                if process.poll() is not None:
                    sys.stdout.write(f"\r\033[K❌ Agent process died unexpectedly. Check logs.\n")
                    sys.exit(1)
                    
                sys.stdout.write(f"\r\033[K\033[96m{chars[i % len(chars)]}\033[0m {current_status}")
                sys.stdout.flush()
                time.sleep(0.1)
                i += 1

def stop():
    pid = get_pid()
    if not is_running(pid):
        print("Agent is not currently running.")
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        return

    print(f"Stopping agent (PID: {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait up to 5 seconds for graceful shutdown
        for _ in range(10):
            if not is_running(pid):
                break
            time.sleep(0.5)
        
        # Force kill if still running
        if is_running(pid):
            print("Process didn't stop gracefully. Force killing...")
            os.kill(pid, signal.SIGKILL)
    except OSError as e:
        print(f"Error stopping process: {e}")
    
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    print("✅ Agent stopped.")

def main():
    if len(sys.argv) < 2:
        print("Usage: lhive [start | stop | restart]")
        sys.exit(1)
        
    cmd = sys.argv[1].lower()
    
    if cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "restart":
        stop()
        time.sleep(1)
        start()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: lhive [start | stop | restart]")
        sys.exit(1)

if __name__ == "__main__":
    main()
