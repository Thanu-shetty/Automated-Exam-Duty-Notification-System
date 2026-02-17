from models import db

def init_db(app, force=False):
    """Initializes the database without test data."""
    with app.app_context():
        if force:
            db.drop_all()
        db.create_all()
        print("Database initialized (no test data added).")