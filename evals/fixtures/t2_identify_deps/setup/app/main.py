from app.db import connect
from app.auth import validate_token
from app.handlers import handle_request


def run():
    db = connect()
    handle_request(db)
