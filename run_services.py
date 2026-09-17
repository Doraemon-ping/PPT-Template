"""Start/stop only this launcher's three child services. No reload subprocesses."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    services = [('hpdc',8001), ('machining',8002), ('workbench',8003)]
    # Fail instead of silently choosing ports that no longer match connectors.
    for name, port in services:
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1',port))
            except OSError:
                print(f'{name}: port {port} is occupied. Stop its existing service first.', flush=True)
                return 1
    processes=[]
    try:
        for name, port in services:
            processes.append(subprocess.Popen([sys.executable,'-m','uvicorn',f'app.services.{name}:app','--host','127.0.0.1','--port',str(port)],
                cwd=root, env=os.environ.copy(), creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
        print('HPDC: http://127.0.0.1:8001\nMachining: http://127.0.0.1:8002\nPPT: http://127.0.0.1:8003\nCtrl+C stops all three child services.',flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(.3)
        print('A child service exited; stopping the remaining services.',flush=True)
        return 1
    except KeyboardInterrupt:
        print('\nStopping services...',flush=True)
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)


if __name__ == '__main__':
    sys.exit(main())
