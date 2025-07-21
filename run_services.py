#!/usr/bin/env python3
"""
Script to run both the main app and scraper service simultaneously
"""

import subprocess
import time
import sys
import os
import signal
import threading
from pathlib import Path

class ServiceRunner:
    def __init__(self):
        self.processes = []
        self.running = True
        
    def run_service(self, script_name, port, service_name):
        """Run a service in a separate process"""
        try:
            print(f"Starting {service_name} on port {port}...")
            
            # Run the service
            process = subprocess.Popen([
                sys.executable, script_name
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            self.processes.append((process, service_name))
            
            # Monitor the process
            def monitor():
                while self.running:
                    if process.poll() is not None:
                        print(f"❌ {service_name} stopped unexpectedly")
                        break
                    time.sleep(1)
            
            thread = threading.Thread(target=monitor, daemon=True)
            thread.start()
            
            return process
            
        except Exception as e:
            print(f"❌ Failed to start {service_name}: {e}")
            return None
    
    def check_file_exists(self, filename):
        """Check if a required file exists"""
        if not Path(filename).exists():
            print(f"❌ Error: {filename} not found in current directory")
            return False
        return True
    
    def wait_for_startup(self, port, service_name, timeout=30):
        """Wait for a service to start up"""
        import requests
        
        print(f"⏳ Waiting for {service_name} to start...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f'http://localhost:{port}/', timeout=2)
                if response.status_code == 200:
                    print(f"✅ {service_name} is ready!")
                    return True
            except:
                pass
            time.sleep(1)
        
        print(f"⚠️  {service_name} may not be ready yet")
        return False
    
    def cleanup(self):
        """Clean up all processes"""
        print("\n🛑 Stopping all services...")
        self.running = False
        
        for process, service_name in self.processes:
            try:
                process.terminate()
                process.wait(timeout=5)
                print(f"✅ Stopped {service_name}")
            except subprocess.TimeoutExpired:
                process.kill()
                print(f"🔧 Force killed {service_name}")
            except Exception as e:
                print(f"⚠️  Error stopping {service_name}: {e}")
    
    def run(self):
        """Run both services"""
        try:
            # Check if required files exist
            if not self.check_file_exists('app.py'):
                return False
            if not self.check_file_exists('w3bcopier_scraper.py'):
                return False
            
            print("🚀 Starting AWS Automation Suite with W3bCopier...")
            print("=" * 50)
            
            # Start the scraper service first (port 8000)
            scraper_process = self.run_service(
                'w3bcopier_scraper.py', 
                8000, 
                'W3bCopier Scraper Service'
            )
            
            if not scraper_process:
                return False
            
            # Wait a bit for scraper to start
            time.sleep(3)
            
            # Start the main app (port 5000)
            main_process = self.run_service(
                'app.py', 
                5000, 
                'Main AWS Automation App'
            )
            
            if not main_process:
                return False
            
            # Wait for services to be ready
            self.wait_for_startup(8000, 'Scraper Service')
            self.wait_for_startup(5000, 'Main App')
            
            print("\n" + "=" * 50)
            print("✅ All services are running!")
            print("🌐 Main App: http://localhost:5000")
            print("🔧 Scraper Service: http://localhost:8000")
            print("=" * 50)
            print("📝 Logs will appear below. Press Ctrl+C to stop all services.")
            print("=" * 50)
            
            # Keep the script running and show logs
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n👋 Received shutdown signal...")
            
            return True
            
        except Exception as e:
            print(f"❌ Error running services: {e}")
            return False
        finally:
            self.cleanup()

def main():
    """Main function"""
    print("AWS Automation Suite - Service Runner")
    print("=" * 40)
    
    # Handle Ctrl+C gracefully
    runner = ServiceRunner()
    
    def signal_handler(signum, frame):
        runner.cleanup()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    success = runner.run()
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()