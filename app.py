import streamlit as st
import pandas as pd
import pdfplumber
import re
from rapidfuzz import process
from io import BytesIO

# ==============================
# Load vendor mapping
# ==============================
VENDOR_FILE = "vendors.csv"
vendor_map = pd.read_csv(VENDOR_FILE)

# ------------------------------
# Fuzzy matching to find category
# ------------------------------
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

# ------------------------------
# Extract transactions from PDF
# ------------------------------
def extract_transactions_from_pdf(pdf_file, account_name):
    transactions = []
    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            dates, merchants, amounts, drcr_flags = [], [], [], []

            for line in lines:
                # 1️⃣ Capture dates
                if re.match(r"\d{2}/\d{2}/\d{4}", line):
                    dates.append(line)

                # 2️⃣ Capture amounts (with DR/CR or INR prefix)
                elif re.search(r"[\d,]+\.\d{2}\s?(DR|CR)?$", line) or re.match(r"INR\s*[\d,]+\.\d{2}", line):
                    drcr = "DR" if "DR" in line else ("CR" if "CR" in line else "")
                    amt = re.sub(r"[^\d\.\-]", "", line)  # remove INR, DR/CR, commas
                    try:
                        amounts.append(float(amt))
                        drcr_flags.append(drcr)
                    except:
                        continue

                # 3️⃣ Everything else = merchant description
                else:
                    merchants.append(line)

            # 4️⃣ Align lists
            n = min(len(dates), len(merchants), len(amounts))
            for i in range(n):
                transactions.append([
                    dates[i],
                    merchants[i],
                    amounts[i] if drcr_flags[i] != "CR" else -amounts[i],  # negate CR
                    drcr_flags[i] if i < len(drcr_flags) else "",
                    account_name
                ])

            st.info(f"📄 Page {page_num}: extracted {n} rows")

    return pd.DataFrame(transactions, columns=["Date", "Merchant", "Amount", "Type", "Account"])

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
    st.write("💰 **Total Spent:**", df["Amount"].sum())

    st.write("📊 **Expense by Category**")
    st.bar_chart(df.groupby("Category")["Amount"].sum())

    st.write("🏦 **Top 5 Merchants**")
    st.table(df.groupby("Merchant")["Amount"].sum().sort_values(ascending=False).head())

    st.write("🏦 **Expense by Account**")
    st.bar_chart(df.groupby("Account")["Amount"].sum())

# ------------------------------
# Export Helpers
# ------------------------------
def convert_df_to_csv(df):
    return df.to_csv(index=False).encode("utf-8")

def convert_df_to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Expenses")
    processed_data = output.getvalue()
    return processed_data

# ==============================
# Streamlit UI
# ==============================
st.title("💳 Multi-Account Expense Analyzer")
st.write("Upload your bank/credit card statements, categorize expenses, and compare across accounts.")

uploaded_files = st.file_uploader("Upload PDF Statements", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    all_data = pd.DataFrame(columns=["Date", "Merchant", "Amount", "Type", "Account"])

    for uploaded_file in uploaded_files:
        account_name = st.text_input(f"Enter account name for {uploaded_file.name}", value=uploaded_file.name)
        if account_name:
            df = extract_transactions_from_pdf(uploaded_file, account_name)
            all_data = pd.concat([all_data, df], ignore_index=True)

    if not all_data.empty:
        all_data = categorize_expenses(all_data)

        # Account Filter
        st.subheader("🔍 Select Account for Analysis")
        account_options = ["All Accounts"] + sorted(all_data["Account"].unique().tolist())
        selected_account = st.selectbox("Choose account", account_options)

        if selected_account != "All Accounts":
            filtered_data = all_data[all_data["Account"] == selected_account]
        else:
            filtered_data = all_data

        # Show raw data
        st.subheader("📑 Extracted Transactions")
        st.dataframe(filtered_data)

        # Handle unknown merchants
        others_df = filtered_data[filtered_data["Category"] == "Others"]
        if not others_df.empty:
            st.subheader("⚡ Assign Categories for Unknown Merchants")
            for merchant in others_df["Merchant"].unique():
                category = st.selectbox(
                    f"Select category for {merchant}:",
                    ["Food", "Shopping", "Travel", "Utilities", "Entertainment", "Banking", "Others"],
                    key=merchant
                )
                if category != "Others":
                    add_new_vendor(merchant, category)
                    all_data.loc[all_data["Merchant"] == merchant, "Category"] = category
                    st.success(f"✅ {merchant} categorized as {category}")

        # Show analysis
        st.subheader("📊 Expense Analysis")
        analyze_expenses(filtered_data)

        # ==============================
        # Export Options
        # ==============================
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
