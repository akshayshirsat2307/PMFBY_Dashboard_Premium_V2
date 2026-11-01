import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

SENDER_EMAIL = os.environ["SENDER_EMAIL"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]

msg = EmailMessage()

msg["From"] = SENDER_EMAIL
msg["To"] = RECIPIENT_EMAIL
msg["Subject"] = "Weekly PMFBY Rabi Data"

msg.set_content(
    """Dear Team,

Please find attached the latest weekly PMFBY Kharif district-level data.

Regards,
Akshay
"""
)

# Find newest generated PMFBY CSV
data_folder = Path("data")

csv_files = list(data_folder.glob("pmfby_*.csv"))

if not csv_files:
    raise FileNotFoundError("No PMFBY CSV found in data folder.")

latest_csv = max(csv_files, key=lambda p: p.stat().st_mtime)

print(f"Attaching: {latest_csv}")

with open(latest_csv, "rb") as f:
    msg.add_attachment(
        f.read(),
        maintype="text",
        subtype="csv",
        filename=latest_csv.name,
    )

with smtplib.SMTP("smtp.office365.com", 587) as smtp:
    smtp.starttls()

    smtp.login(
        SENDER_EMAIL,
        EMAIL_PASSWORD,
    )

    smtp.send_message(msg)

print(f"Email sent to {RECIPIENT_EMAIL}")
