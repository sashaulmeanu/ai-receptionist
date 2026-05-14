import os
import sqlite3
import pytz
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

DB_FILE = "appointments.db"
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Bucharest")
SCOPES = ["https://www.googleapis.com/auth/calendar"]

PROGRAM = {
    0: ("08:00", "19:00"),
    1: ("08:00", "19:00"),
    2: ("08:00", "19:00"),
    3: ("08:00", "19:00"),
    4: ("08:00", "19:00"),
    5: ("09:00", "14:00"),
    6: None
}
