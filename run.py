import uvicorn
import os

if __name__ == "__main__":
    # Force the script to run from the root directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    uvicorn.run(
        "app.main:app",       # Crucial: Tells Uvicorn to look inside the 'app' folder for 'main.py'
        host="127.0.0.1", 
        port=8000, 
        reload=True, 
        # Crucial: ONLY watch the 'app' folder. 
        # This creates a "firewall" between your backend and frontend.
        reload_dirs=["app"] 
    )