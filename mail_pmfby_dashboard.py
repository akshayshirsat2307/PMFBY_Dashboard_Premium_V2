from pathlib import Path
from datetime import datetime
import smtplib
from email.message import EmailMessage
import mimetypes
import os


# ============================================================
# CONFIGURATION
# ============================================================

DATA_DIR = Path("data")

# Gmail account / App Password supplied through GitHub Secrets
SENDER_EMAIL = os.environ["SENDER_EMAIL"]
SENDER_PASSWORD = os.environ["SENDER_PASSWORD"]

RECIPIENT_EMAILS = [
    "akshay.shirsat.2307@gmail.com"
]


# ============================================================
# CURRENT DATE
# ============================================================

today = datetime.now()

# Your PMFBY workflow generates filenames like:
# pmfby_2026_kharif_2026-11-01.csv

date_str = today.strftime("%Y-%m-%d")
date_display = today.strftime("%d-%m-%Y")

print("=" * 60)
print("PMFBY WEEKLY EMAIL")
print("=" * 60)

print("Looking for PMFBY files containing:", date_str)


# ============================================================
# FIND TODAY'S PMFBY FILES
# ============================================================

attachments = []

if not DATA_DIR.exists():
    raise FileNotFoundError(
        f"Data directory does not exist: {DATA_DIR}"
    )

for filepath in DATA_DIR.iterdir():

    if not filepath.is_file():
        continue

    if (
        filepath.suffix.lower() == ".csv"
        and filepath.name.startswith("pmfby_")
        and date_str in filepath.name
    ):
        attachments.append(filepath)


attachments.sort()


# ============================================================
# DISPLAY FILES
# ============================================================

print("\nFiles found:")

for filepath in attachments:
    print(" -", filepath.name)


# ============================================================
# STOP IF NO FILES FOUND
# ============================================================

if not attachments:

    raise FileNotFoundError(
        f"No PMFBY CSV files containing "
        f"{date_str} were found in "
        f"{DATA_DIR}"
    )


# ============================================================
# CREATE EMAIL
# ============================================================

msg = EmailMessage()

msg["Subject"] = (
    f"PMFBY Premium Weekly Rabi District Data - "
    f"{date_display}"
)

msg["From"] = SENDER_EMAIL

msg["To"] = ", ".join(
    RECIPIENT_EMAILS
)


# ============================================================
# EMAIL BODY
# ============================================================

body = f"""Dear Sir/Madam,

Please find attached the latest weekly PMFBY/WBCIS
Rabi district-level data.

Report Date: {date_display}

Files attached:
"""

for filepath in attachments:

    body += (
        f"- {filepath.name}\n"
    )


body += """

Regards,
Akshay
"""


msg.set_content(body)


# ============================================================
# ATTACH FILES
# ============================================================

for filepath in attachments:

    mime_type, _ = mimetypes.guess_type(
        filepath
    )

    if mime_type is None:

        mime_type = (
            "application/octet-stream"
        )


    maintype, subtype = (
        mime_type.split("/", 1)
    )


    with open(
        filepath,
        "rb"
    ) as f:

        file_data = f.read()


    msg.add_attachment(

        file_data,

        maintype=maintype,

        subtype=subtype,

        filename=filepath.name

    )


    print(
        "Attached:",
        filepath.name
    )


# ============================================================
# SEND EMAIL THROUGH GMAIL
# ============================================================

print("\nConnecting to Gmail...")


with smtplib.SMTP_SSL(
    "smtp.gmail.com",
    465
) as smtp:

    smtp.login(
        SENDER_EMAIL,
        SENDER_PASSWORD
    )

    smtp.send_message(
        msg
    )


# ============================================================
# SUCCESS
# ============================================================

print("\n" + "=" * 60)

print(
    "EMAIL SENT SUCCESSFULLY"
)

print("=" * 60)

print(
    "Date:",
    date_display
)

print(
    "Files attached:",
    len(attachments)
)

for filepath in attachments:

    print(
        " -",
        filepath.name
    )
