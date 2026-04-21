import subprocess
import webbrowser
import threading
import time
import http.server
import socketserver
import os
import platform
import socket

FRONTEND_PORT = 3000
API_PORT = 8000

def is_wsl():
    return "microsoft-standard" in platform.uname().release.lower()

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

class ThreadingSimpleServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

def serve_frontend():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    if not os.path.exists("Website.html"):
        print(f"ERROR: 'Website.html' not found in {base_dir}")
        print("Please ensure your HTML file is named 'Website.html' and is in the same folder as start.py.")
        return

    handler = http.server.SimpleHTTPRequestHandler
    ThreadingSimpleServer.allow_reuse_address = True
    
    try:
        with ThreadingSimpleServer(("0.0.0.0", FRONTEND_PORT), handler) as httpd:
            print(f"Frontend server active at http://localhost:{FRONTEND_PORT}")
            httpd.serve_forever()
    except Exception as e:
        print(f"Frontend server failed to start: {e}")

def start_api():
    subprocess.Popen([
        "uvicorn", "api:app", 
        "--host", "0.0.0.0", 
        "--port", str(API_PORT)
    ])

def open_browser():
    time.sleep(2)
    url = f"http://localhost:{FRONTEND_PORT}/Website.html"
    ip_url = f"http://{get_ip()}:{FRONTEND_PORT}/Website.html"
    
    print(f"\nApplication UI: {url}")
    print(f"Alternative (WSL IP): {ip_url}\n")
    
    if is_wsl():
        try:
            subprocess.run(["powershell.exe", "/c", "start", url], capture_output=True)
        except Exception:
            print("Could not auto-open browser. Please manually navigate to the URL above.")
    else:
        webbrowser.open(url)

if __name__ == "__main__":
    print("--- Initializing Meeting Digester ---")
    
    print("Starting API Server...")
    start_api()

    print("Starting Frontend Server...")
    threading.Thread(target=serve_frontend, daemon=True).start()

    open_browser()

    print("System Running — press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")