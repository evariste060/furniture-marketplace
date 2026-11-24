# Start the FurniHub API for development on port 8001 (port 8000 belongs to another project).
# Run from the backend folder with the virtual environment active: .\run.ps1
uvicorn app.main:app --reload --port 8001
