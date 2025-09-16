import streamlit as st
import pandas as pd
import pdfplumber
import re
from rapidfuzz import process
from io import BytesIO
from statistics import mean

# ==============================
# Config / vendor mapping file
# ==============================
VENDOR_FILE = "vendors.csv"
vendor_map = pd.read_csv(VENDOR_FILE)

# ------------------------------
# Fuzzy matching to find category
# ------------------------------
def get_category(merchant):
    m = str(merchant).lower()
    try:
        matches = process.extractOne(
            m,
            vendor_map["merchant"].str.lower().tolist(),
            score_cutoff=80
        )
    except Exception:
        return "Others"
    if matches:
        matched_merchant = matches[0]
        category = vendor_map.loc[
            vendor_map["merchant"].str.lower() == matched_merchant, "category"
        ].iloc[0]
        return category
    return "Others"

# ------------------------------
# Helpers for parsing amounts & dates
# ------------------------------
date_regex = re.compile(r"\d{2}/\d{2}/\d{4}")

def parse_amount_field(s):
    """Return (amount_float, type_str) where type_str is 'DR' or 'CR' or ''. CR -> negative amount."""
    if s is None:
        return None, ""
    s = str(s).upper().strip()
    # detect CR/DR token anywhere
    dr = "DR" in s and "CR" not in s
    cr = "CR" in s and "DR" not in s
    # remove INR, CR, DR, commas, non-numeric except dot and minus
    clean = re.sub(r"INR|\s|CR|DR|,", "", s, flags=re.IGNORECASE)
    clean = re.sub(r"[^\d\.\-]", "", clean)
    if clean == "":
        return None, ""
    try:
        val = float(clean)
    except:
        return None, ""
    if cr:
        return -abs(val), "CR"
    if dr:
        return abs(val), "DR"
    # if neither specified, return positive number (we'll handle sign logic outside if needed)
    return val, ""

# ------------------------------
# Primary extraction function
# ------------------------------
def extract_transactions_from_pdf(pdf_file, account_name):
    """
    Attempts three strategies per page:
      1) page.extract_table()
      2) line-regex scans (multiple date patterns)
      3) word-position column reconstruction (for columnar / vertical layouts)
    Returns DataFrame with columns: Date, Merchant, Amount, Type, Account
    """
    regex_patterns = [
        re.compile(r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})"),   # dd/mm/yyyy merchant amount
        re.compile(r"(\d{2}-\d{2}-\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})"),
        re.compile(r"([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s+(.+?)\s+(-?\d[\d,]*\.\d{2})"),
    ]

    transactions = []
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_table_count = 0
                page_text_count = 0
                page_words_count = 0

                # -------------------------
                # 1) Table extraction
                # -------------------------
                try:
                    table = page.extract_table()
                except Exception:
                    table = None

                if table and len(table) > 1:
                    headers = [ (h or "").strip().lower() for h in table[0] ]
                    for row in table[1:]:
                        # safe zip
                        row_dict = dict(zip(headers, row))
                        date_raw = row_dict.get("date") or row_dict.get("transaction date") or row_dict.get("txn date")
                        desc = row_dict.get("description") or row_dict.get("merchant") or row_dict.get("narration")
                        amt_raw = row_dict.get("amount") or row_dict.get("debit") or row_dict.get("credit")
                        amt, ttype = parse_amount_field(amt_raw)
                        if date_raw and desc and amt is not None:
                            transactions.append([date_raw.strip(), desc.strip(), amt, ttype, account_name])
                            page_table_count += 1
                    st.info(f"📄 Page {page_num}: extracted {page_table_count} rows from table")
                    continue  # go to next page

                # -------------------------
                # 2) Line-based regex extraction
                # -------------------------
                text = page.extract_text() or ""
                if text.strip():
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    for line in lines:
                        matched = False
                        for pat in regex_patterns:
                            m = pat.match(line)
                            if m:
                                date_raw = m.group(1)
                                merchant = m.group(2)
                                amt_str = m.group(3)
                                amt, ttype = parse_amount_field(amt_str)
                                if amt is not None:
                                    transactions.append([date_raw.strip(), merchant.strip(), amt, ttype, account_name])
                                    page_text_count += 1
                                    matched = True
                                    break
                        if matched:
                            continue
                    if page_text_count:
                        st.info(f"📄 Page {page_num}: extracted {page_text_count} rows from text (regex)")
                        continue  # go to next page if regex found rows

                # -------------------------
                # 3) Word-position based column reconstruction (for vertical columns)
                # -------------------------
                words = page.extract_words()  # list of dicts: text, x0, x1, top, bottom
                if words and len(words) > 4:
                    # cluster x0 positions into column groups
                    x0s = sorted({int(round(w["x0"])) for w in words})
                    # make clusters splitting when gap > threshold (empirical)
                    clusters = []
                    if x0s:
                        cur = [x0s[0]]
                        for x in x0s[1:]:
                            if x - cur[-1] <= 30:  # threshold (px)
                                cur.append(x)
                            else:
                                clusters.append(cur)
                                cur = [x]
                        clusters.append(cur)
                    centers = [mean(c) for c in clusters] if clusters else []

                    # map words into nearest cluster index
                    rows_by_top = {}
                    for w in words:
                        if not centers:
                            col_idx = 0
                        else:
                            col_idx = min(range(len(centers)), key=lambda i: abs(w["x0"] - centers[i]))
                        top_key = int(round(w["top"]))
                        rows_by_top.setdefault(top_key, {}).setdefault(col_idx, []).append(w["text"])

                    # convert rows_by_top into ordered rows
                    top_keys = sorted(rows_by_top.keys())
                    for top in top_keys:
                        cols = rows_by_top[top]
                        fields = []
                        for col_idx in range(len(centers)):
                            txts = cols.get(col_idx, [])
                            fields.append(" ".join(txts).strip())
                        # heuristic: find date in any field; find amount in any field; remaining text -> merchant
                        date_field = None
                        amount_field = None
                        amount_type = ""
                        for f in fields:
                            if f and date_regex.search(f):
                                date_field = date_regex.search(f).group(0)
                                break
                        # find amount (pattern with at least one digit and decimal)
                        for f in reversed(fields):  # prefer rightmost columns for amount
                            if re.search(r"[\d,]+\.\d{2}", f):
                                amount_field = f
                                break
                        if amount_field and date_field:
                            amt, ttype = parse_amount_field(amount_field)
                            # merchant is best guess: take the middle columns joined except date and amount
                            # pick field index of date and of amount
                            date_idx = next((i for i,f in enumerate(fields) if date_field in f), None)
                            amount_idx = next((i for i,f in enumerate(fields) if amount_field in f), None)
                            merchant_parts = []
                            for i,f in enumerate(fields):
                                if i not in (date_idx, amount_idx) and f:
                                    merchant_parts.append(f)
                            merchant = " ".join(merchant_parts).strip() if merchant_parts else ""
                            if amt is not None:
                                transactions.append([date_field, merchant, amt if ttype != "CR" else -abs(amt), ttype, account_name])
                                page_words_count += 1

                    st.info(f"📄 Page {page_num}: extracted {page_words_count} rows from word-column reconstruction")

                else:
                    st.info(f"📄 Page {page_num}: no words/columns found to reconstruct")

    except Exception as e:
        st.error(f"PDF open/parse error: {e}")

    df = pd.DataFrame(transactions, columns=["Date", "Merchant", "Amount", "Type", "Account"])
    if df.empty:
        st.warning("⚠️ No transactions extracted. Please try downloading a text-based PDF or CSV from your bank, or paste one sample transaction line here so I can tune the parser.")
    return df

# ------------------------------
# Categorize expenses
# ------------------------------
def categorize_expenses(df):
    df["Category"] = df["Merchant"].apply(get_category)
    return df

# ------------------------------
# Add new vendor if categorized by user (persist to CSV)
# ------------------------------
def add_new_vendor(merchant, category):
    global vendor_map
    new_row = pd.DataFrame([[merchant.lower(), category]], columns=["merchant", "category"])
    vendor_map = pd.concat([vendor_map, new_row], ignore_index=True)
    vendor_map.drop_duplicates(subset=["merchant"], keep="last", inplace=True)
    vendor_map.to_csv(VENDOR_FILE, index=False)

# ------------------------------
# Analysis & Export helpers
# ------------------------------
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
st.set_page_config(page_title="Expense Analyzer", layout="wide")
st.title("💳 Multi-Account Expense Analyzer")
st.write("Upload your bank/credit card statements (PDF or CSV), categorize expenses, and compare across accounts.")

uploaded_files = st.file_uploader("Upload PDF Statements", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    all_data = pd.DataFrame(columns=["Date", "Merchant", "Amount", "Type", "Account"])
    for idx, uploaded_file in enumerate(uploaded_files):
        key = f"account_input_{idx}_{uploaded_file.name}"
        account_name = st.text_input(f"Enter account name for {uploaded_file.name}", value=uploaded_file.name, key=key)
        if account_name:
            df = extract_transactions_from_pdf(uploaded_file, account_name)
            if not df.empty:
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
            for i, merchant in enumerate(others_df["Merchant"].unique()):
                k = f"cat_{i}_{merchant[:30]}"
                category = st.selectbox(
                    f"Select category for {merchant}:",
                    ["Food", "Shopping", "Travel", "Utilities", "Entertainment", "Banking", "Others"],
                    key=k
                )
                if category != "Others":
                    add_new_vendor(merchant, category)
                    all_data.loc[all_data["Merchant"] == merchant, "Category"] = category
                    st.success(f"✅ {merchant} categorized as {category}")

        st.subheader("📊 Expense Analysis")
        analyze_expenses(filtered_data)

        st.subheader("📥 Download Results")
        csv_data = convert_df_to_csv(filtered_data)
        excel_data = convert_df_to_excel(filtered_data)

        st.download_button(
            label="⬇️ Download as CSV",
            data=csv_data,
            file_name=f"expenses_{selected_account.replace(' ','_')}.csv",
            mime="text/csv"
        )

        st.download_button(
            label="⬇️ Download as Excel",
            data=excel_data,
            file_name=f"expenses_{selected_account.replace(' ','_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
