import pytesseract
from pdf2image import convert_from_path
import os

def extract_transactions_from_pdf(pdf_file, account_name):
    transactions = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # ==============================
            # First try: Table extraction
            # ==============================
            table = page.extract_table()
            if table:
                headers = [h.lower() if h else "" for h in table[0]]
                for row in table[1:]:
                    row_dict = dict(zip(headers, row))
                    date_raw = row_dict.get("date") or row_dict.get("transaction date")
                    desc = row_dict.get("description") or row_dict.get("merchant") or row_dict.get("narration")
                    amt_raw = row_dict.get("amount") or row_dict.get("debit") or row_dict.get("credit")

                    if date_raw and desc and amt_raw:
                        transactions.append([
                            clean_date(date_raw),
                            desc.strip(),
                            clean_amount(amt_raw),
                            account_name
                        ])
                continue  # go to next page after table

            # ==============================
            # Fallback: Text + Regex
            # ==============================
            text = page.extract_text()
            if text:
                lines = text.split("\n")
                regex_patterns = [
                    r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})",  # 01/08/2025
                    r"(\d{2}-\d{2}-\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})",  # 01-08-2025
                    r"([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})"  # Aug 01, 2025
                ]

                for line in lines:
                    for pattern in regex_patterns:
                        match = re.match(pattern, line)
                        if match:
                            date_raw, merchant, amt_raw = match.groups()
                            transactions.append([
                                clean_date(date_raw),
                                merchant.strip(),
                                clean_amount(amt_raw),
                                account_name
                            ])
                            break

    # ==============================
    # OCR Fallback (Scanned PDFs)
    # ==============================
    if not transactions:  # If nothing extracted
        images = convert_from_path(pdf_file)
        for img in images:
            text = pytesseract.image_to_string(img)
            lines = text.split("\n")
            for line in lines:
                for pattern in regex_patterns:
                    match = re.match(pattern, line)
                    if match:
                        date_raw, merchant, amt_raw = match.groups()
                        transactions.append([
                            clean_date(date_raw),
                            merchant.strip(),
                            clean_amount(amt_raw),
                            account_name
                        ])
                        break

    return pd.DataFrame(transactions, columns=["Date", "Merchant", "Amount", "Account"])


# ==============================
# Helper Functions
# ==============================
from dateutil.parser import parse

def clean_date(date_str):
    try:
        return parse(date_str, dayfirst=True).date()
    except Exception:
        return date_str

def clean_amount(amt_str):
    amt_str = amt_str.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(amt_str)
    except Exception:
        return 0.0
