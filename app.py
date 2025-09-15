import streamlit as st
import pandas as pd
import pdfplumber
import re
import matplotlib.pyplot as plt
from rapidfuzz import process
from io import BytesIO
from dateutil.parser import parse

# ==============================
# Page config
# ==============================
st.set_page_config(page_title="Expense Analyzer", layout="wide")

st.title("💳 Multi-Account Expense Analyzer")
st.write("Upload your bank/credit card statements, categorize expenses, and compare across accounts.")

# ==============================
# Load vendor mapping
# ==============================
VENDOR_FILE = "vendors.csv"
vendor_map = pd.read_csv(VENDOR_FILE)

# Fuzzy matching to find category
def get_category(merchant):
    m = merchant.lower()
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

# ==============================
# Helpers
# ==============================
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

# ==============================
# Extraction function (fixed)
# ==============================
def extract_transactions_from_pdf(uploaded_file, account_name):
    transactions = []
    regex_patterns = [
        r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})",
        r"(\d{2}-\d{2}-\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})",
        r"([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})"
    ]

    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                # First try table extraction
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
                    continue  # skip to next page if table worked

                # Fallback to text extraction
                text = page.extract_text()
                if text:
                    for line in text.split("\n"):
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
    except Exception as e:
        st.error(f"❌ PDF parsing failed: {e}")

    return pd.DataFrame(transactions, columns=["Date", "Merchant", "Amount", "Account"])

# ==============================
# Categorize + Vendor Mapping
# ==============================
def categorize_expenses(df):
    df["Category"] = df["Merchant"].apply(get_category)
    return df

def add_new_vendor(merchant, category):
    global vendor_map
    new_row = pd.DataFrame([[merchant.lower(), category]], columns=["merchant", "category"])
    vendor_map = pd.concat([vendor_map, new_row], ignore_index=True)
    vendor_map.drop_duplicates(subset=["merchant"], keep="last", inplace=True)
    vendor_map.to_csv(VENDOR_FILE, index=False)

# ==============================
# Analysis + Export
# ==============================
def analyze_expenses(df):
    st.write("💰 **Total Spent:**", df["Amount"].sum())
    st.write("📊 **Expense by Category**")
    st.bar_chart(df.groupby("Category")["Amount"].sum())
    st.write("🏦 **Top 5 Merchants**")
    st.table(df.groupby("Merchant")["Amount"].sum().sort_values(ascending=False).head())
    st.write("🏦 **Expense by Account**")
    st.bar_chart(df.groupby("Account")["Amount"].sum())

def convert_df_to_csv(df):
    return df.to_csv(index=False).encode("utf-8")

def convert_df_to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Expenses")
    return output.getvalue()

# ==============================
# Streamlit UI
# ==============================
uploaded_files = st.file_uploader("Upload PDF Statements", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    all_data = pd.DataFrame(columns=["Date", "Merchant", "Amount", "Account"])

    for uploaded_file in uploaded_files:
        account_name = st.text_input(
            f"Enter account name for {uploaded_file.name}",
            value=uploaded_file.name,
            key=f"account_input_{uploaded_file.name}"  # unique key fix
        )
        if account_name:
            df = extract_transactions_from_pdf(uploaded_file, account_name)
            all_data = pd.concat([all_data, df], ignore_index=True)

    if not all_data.empty:
        all_data = categorize_expenses(all_data)

        st.subheader("🔍 Select Account for Analysis")
        account_options = ["All Accounts"] + sorted(all_data["Account"].unique().tolist())
        selected_account = st.selectbox("Choose account", account_options)

        if selected_account != "All Accounts":
            filtered_data = all_data[all_data["Account"] == selected_account]
        else:
            filtered_data = all_data

        st.subheader("📑 Extracted Transactions")
        st.dataframe(filtered_data)

        # Unknown merchants
        others_df = filtered_data[filtered_data["Category"] == "Others"]
        if not others_df.empty:
            st.subheader("⚡ Assign Categories for Unknown Merchants")
            for merchant in others_df["Merchant"].unique():
                category = st.selectbox(
                    f"Select category for {merchant}:",
                    ["Food", "Shopping", "Travel", "Utilities", "Entertainment", "Banking", "Insurance", "Education", "Others"],
                    key=f"cat_{merchant}"
                )
                if category != "Others":
                    add_new_vendor(merchant, category)
                    all_data.loc[all_data["Merchant"] == merchant, "Category"] = category
                    st.success(f"✅ {merchant} categorized as {category}")

        st.subheader("📊 Expense Analysis")
        analyze_expenses(filtered_data)

        # Download buttons
        st.subheader("📥 Download Results")
        st.download_button(
            label="⬇️ Download as CSV",
            data=convert_df_to_csv(filtered_data),
            file_name=f"expenses_{selected_account.replace(' ','_')}.csv",
            mime="text/csv"
        )
        st.download_button(
            label="⬇️ Download as Excel",
            data=convert_df_to_excel(filtered_data),
            file_name=f"expenses_{selected_account.replace(' ','_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
