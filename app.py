"""Entry point for the Smart Campus Service Request System.

    python app.py            # start the development server
    python seed.py           # (optional) load demo data first

Author: Rajesh S (GitHub: Rajeshh-S)
"""
import os

from smartcampus import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
