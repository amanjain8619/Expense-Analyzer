import streamlit as st
import pandas as pd
import pdfplumber
import re
from rapidfuzz import process
from io import BytesIO
from datetime import datetime
import os

# ==============================
# Load vendor mapping
# ==============================
VENDOR_FILE = "vendors.csv"
if os.path.exists(VENDOR_FILE):
    vendor_map = pd.read_csv(VENDOR_FILE)
else:
    vendor_map = pd.DataFrame(columns=["merchant", "category"])
    vendor_map.to_csv(VENDOR_FILE, index=False)

# ------------------------------
# Fuzzy matching to find category
# ------------------------------
def get_category(merchant):
    m = str(merchant).lower()
    matches = process.extractOne(
        m,
        vendor_map["merchant"].str.lower().tolist(),
        score_cutoff=80
    )
    if matches:
        matched_merchant = matches[0]
        category = vendor_map.loc[
            vendor_map["merchant"].str.lower() == matched_merchant, "category"
        ].iloc[0]
        return category
    return "Others"

# ------------------------------
# Date Parser
# ------------------------------
def parse_date(date_str):
    """Handle dd/mm/yyyy and Month DD formats."""
    try:
        return datetime.strptime(date_str, "%d/%m/%Y").strftime("%d/%m/%Y")
    except:
        try:
            return datetime.strptime(date_str + " 2025", "%b %d %Y").strftime("%d/%m/%Y")
        except:
            try:
                return datetime.strptime(date_str + " 2025", "%B %d %Y").strftime("%d/%m/%Y")
            except:
                return date_str

# ------------------------------
# Extract transactions from PDF (supports HDFC/ICICI/BoB + AMEX)
# ------------------------------
def extract_transactions_from_pdf(pdf_file, account_name, debug=False):
    transactions = []
    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):

            # 🔎 First try table-based extraction (AMEX style)
            table = page.extract_table()
            if table:
                if debug:
                    st.write(f"🔎 Debug Table Page {page_num} (first 10 rows)", table[:10])

                headers = [str(h).strip().lower() if h else "" for h in table[0]]
                for row in table[1:]:
                    if not any(row):
                        continue
                    row_data = dict(zip(headers, row))

                    date = row_data.get("date") or row[0]
                    merchant = row_data.get("description") or row[1]
                    amount = row_data.get("amount") or row[-2]
                    drcr = row_data.get("drcr") or row[-1]

                    if not date or not amount:
                        continue

                    try:
                        amt = float(str(amount).replace(",", ""))
                        if drcr and str(drcr).strip().upper().startswith("CR"):
                            amt = -amt
                            drcr = "CR"
                        else:
                            drcr = "DR"
                        transactions.append([parse_date(date), merchant.strip(), round(amt, 2), drcr, account_name])
                    except:
                        continue

            # Fallback: regex-based parsing (HDFC/ICICI/BoB style)
            else:
                text = page.extract_text()
                if debug and text:
                    st.write(f"🔎 Debug Text Page {page_num}", text.split("\n")[:20])

                if not text:
                    continue
                lines = [l.strip() for l in text.split("\n") if l.strip()]

                for line in lines:
                    match = re.match(r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d,]+\.\d{2})\s?(CR|DR)?", line)
                    if match:
                        date, merchant, amount, drcr = match.groups()
                        amt = float(amount.replace(",", ""))
                        if drcr == "CR":
                            amt = -amt
                        transactions.append([parse_date(date), merchant.strip(), round(amt, 2), drcr if drcr else "DR", account_name])

            st.info(f"📄 Page {page_num}: extracted {len(transactions)} rows so far")

    return pd.DataFrame(transactions, columns=["Date", "Merchant", "Amount", "Type", "Account"])

# ------------------------------
# Extract transactions from CSV/XLSX
# ------------------------------
def extract_transactions_from_excel(file, account_name):
    df = pd.read_excel(file)
    return normalize_dataframe(df, account_name)

def extract_transactions_from_csv(file, account_name):
    df = pd.read_csv(file)
    return normalize_dataframe(df, account_name)

def normalize_dataframe(df, account_name):
    col_map = {
        "date": "Date",
        "transaction date": "Date",
        "txn date": "Date",
        "description": "Merchant",
        "narration": "Merchant",
        "merchant": "Merchant",
        "amount": "Amount",
        "debit": "Debit",
        "credit": "Credit",
        "type": "Type"
    }
    df_renamed = {}
    for col in df.columns:
        key = col.lower().strip()
        if key in col_map:
            df_renamed[col] = col_map[key]

    df = df.rename(columns=df_renamed)

    if "Debit" in df and "Credit" in df:
        df["Amount"] = df["Debit"].fillna(0) - df["Credit"].fillna(0)
        df["Type"] = df.apply(lambda x: "DR" if x["Debit"] > 0 else "CR", axis=1)
    elif "Amount" in df and "Type" in df:
        df["Amount"] = df.apply(lambda x: -abs(x["Amount"]) if str(x["Type"]).upper().startswith("CR") else abs(x["Amount"]), axis=1)
    elif "Amount" in df and "Type" not in df:
        df["Type"] = "DR"

    if "Date" not in df or "Merchant" not in df or "Amount" not in df:
        st.error("❌ Could not detect required columns (Date, Merchant, Amount). Please check your file.")
        return pd.DataFrame(columns=["Date", "Merchant", "Amount", "Type", "Account"])

    df["Amount"] = df["Amount"].astype(float).round(2)
    df["Account"] = account_name
    return df[["Date", "Merchant", "Amount", "Type", "Account"]]

# ------------------------------
# Categorize expenses
# ------------------------------
def categorize_expenses(df):
    df["Category"] = df["Merchant"].apply(get_category)
    return df

# ------------------------------
# Add new vendor if categorized by user
# ------------------------------
def add_new_vendor(merchant, category):
    global vendor_map
    new_row = pd.DataFrame([[merchant.lower(), category]], columns=["merchant", "category"])
    vendor_map = pd.concat([vendor_map, new_row], ignore_index=True)
    vendor_map.drop_duplicates(subset=["merchant"], keep="last", inplace=True)
    vendor_map.to_csv(VENDOR_FILE, index=False)

# ------------------------------
# Expense analysis
# ------------------------------
def analyze_expenses(df):
    st.write("💰 **Total Spent:**", f"{df['Amount'].sum():,.2f}")
    st.write("📊 **Expense by Category**")
    st.bar_chart(df.groupby("Category")["Amount"].sum().round(2))
    st.write("🏦 **Top 5 Merchants**")
    st.dataframe(df.groupby("Merchant")["Amount"].sum().round(2).sort_values(ascending=False).head())
    st.write("🏦 **Expense by Account**")
    st.bar_chart(df.groupby("Account")["Amount"].sum().round(2))

# ------------------------------
# Export Helpers
# ------------------------------
def convert_df_to_csv(df):
    df["Amount"] = df["Amount"].round(2)
    return df.to_csv(index=False).encode("utf-8")

def convert_df_to_excel(df):
    df["Amount"] = df["Amount"].round(2)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Expenses", float_format="%.2f")
    return output.getvalue()

# ==============================
# Streamlit UI
# ==============================
st.title("💳 Multi-Account Expense Analyzer")
st.write("Upload your bank/credit card statements (PDF, CSV, or Excel).")

debug_mode = st.checkbox("Enable Debug Mode 🔎", value=False)

uploaded_files = st.file_uploader("Upload Statements", type=["pdf", "csv", "xlsx"], accept_multiple_files=True)

if uploaded_files:
    all_data = pd.DataFrame(columns=["Date", "Merchant", "Amount", "Type", "Account"])

    for uploaded_file in uploaded_files:
        account_name = st.text_input(f"Enter account name for {uploaded_file.name}", value=uploaded_file.name)
        if account_name:
            if uploaded_file.name.endswith(".pdf"):
                df = extract_transactions_from_pdf(uploaded_file, account_name, debug=debug_mode)
            elif uploaded_file.name.endswith(".csv"):
                df = extract_transactions_from_csv(uploaded_file, account_name)
            elif uploaded_file.name.endswith(".xlsx"):
                df = extract_transactions_from_excel(uploaded_file, account_name)
            else:
                df = pd.DataFrame()
            all_data = pd.concat([all_data, df], ignore_index=True)

    if not all_data.empty:
        all_data = categorize_expenses(all_data)
        all_data["Amount"] = all_data["Amount"].round(2)

        st.subheader("📑 Extracted Transactions")
        st.dataframe(all_data)

        st.subheader("📊 Expense Analysis")
        analyze_expenses(all_data)

        st.subheader("📥 Download Results")
        st.download_button("⬇️ CSV", convert_df_to_csv(all_data), "expenses.csv", "text/csv")
        st.download_button("⬇️ Excel", convert_df_to_excel(all_data),
                           "expenses.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
