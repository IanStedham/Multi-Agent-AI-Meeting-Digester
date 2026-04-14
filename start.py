import subprocess
import webbrowser
import threading
import time
import http.server
import socketserver
import os
 
FRONTEND_PORT = 3000
API_PORT = 8000
 
def serve_frontend():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", FRONTEND_PORT), handler) as httpd:
        httpd.serve_forever()
 
def start_api():
    subprocess.Popen(["uvicorn", "api:app", "--port", str(API_PORT)])
 
def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{FRONTEND_PORT}/index.html")
 
if __name__ == "__main__":
    print("Starting API...")
    start_api()
 
    print("Starting frontend...")
    threading.Thread(target=serve_frontend, daemon=True).start()
 
    print("Opening browser...")
    open_browser()
 
    print("Running — press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down")