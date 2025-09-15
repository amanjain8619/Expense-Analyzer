import streamlit as st
import pandas as pd
import pdfplumber
import re
import matplotlib.pyplot as plt
from rapidfuzz import process

st.set_page_config(page_title="Expense Analyzer", layout="wide")
st.title("💳 Expense Analyzer")
st.write("Upload your bank/credit card statement PDF and get smart insights!")

# ==============================
# Load vendor mapping
# ==============================
@st.cache_data
def load_vendor_map():
    try:
        return pd.read_csv("vendors.csv")
    except Exception:
        return pd.DataFrame(columns=["merchant", "category"])

def save_vendor_map(vendor_map):
    vendor_map.to_csv("vendors.csv", index=False)

vendor_map = load_vendor_map()

# ==============================
# Extract transactions
# ==============================
def extract_transactions_from_pdf(pdf_file):
    transactions = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            lines = text.split("\n")
            for line in lines:
                match = re.match(r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\d+\.\d{2})", line)
                if match:
                    date, merchant, amount = match.groups()
                    transactions.append([date, merchant.strip(), float(amount)])
    return pd.DataFrame(transactions, columns=["Date", "Merchant", "Amount"])

# ==============================
# Fuzzy match category
# ==============================
def get_category(merchant, vendor_map):
    merchant_lower = merchant.lower()
    best_match = process.extractOne(
        merchant_lower,
        vendor_map['merchant'].str.lower().tolist(),
        score_cutoff=80
    )
    if best_match:
        category = vendor_map[vendor_map['merchant'].str.lower() == best_match[0]]['category'].iloc[0]
        return category
    return "Others"

def categorize_expenses(df, vendor_map):
    df["Category"] = df["Merchant"].apply(lambda m: get_category(m, vendor_map))
    return df

# ==============================
# Expense analysis
# ==============================
def analyze_expenses(df):
    st.subheader("💰 Total Spent")
    st.write(f"₹ {df['Amount'].sum():,.2f}")

    st.subheader("📊 Expense by Category")
    category_data = df.groupby("Category")["Amount"].sum()
    st.dataframe(category_data)

    fig, ax = plt.subplots()
    category_data.plot(kind="bar", ax=ax, title="Expenses by Category", color="teal")
    ax.set_ylabel("Amount (₹)")
    st.pyplot(fig)

    st.subheader("🏦 Top 5 Merchants")
    st.dataframe(df.groupby("Merchant")["Amount"].sum().sort_values(ascending=False).head())

# ==============================
# File upload
# ==============================
uploaded_file = st.file_uploader("Upload PDF Statement", type=["pdf"])

if uploaded_file:
    df = extract_transactions_from_pdf(uploaded_file)
    if not df.empty:
        df = categorize_expenses(df, vendor_map)

        st.subheader("📋 Transactions")
        st.dataframe(df)

        analyze_expenses(df)

        # ==============================
        # Handle "Others" → User feedback
        # ==============================
        st.subheader("🛠 Fix Uncategorized Merchants")
        others_df = df[df["Category"] == "Others"]

        if not others_df.empty:
            st.write("Some merchants were not recognized. Assign categories below:")

            categories = vendor_map["category"].unique().tolist()
            new_entries = []

            for _, row in others_df.iterrows():
                merchant = row["Merchant"]
                choice = st.selectbox(
                    f"Select category for: {merchant}",
                    options=["Food", "Shopping", "Travel", "Utilities", "Entertainment", "Others"],
                    key=merchant
                )
                if choice != "Others":
                    new_entries.append({"merchant": merchant.lower(), "category": choice})

            if st.button("✅ Save Mappings"):
                if new_entries:
                    new_df = pd.DataFrame(new_entries)
                    vendor_map = pd.concat([vendor_map, new_df]).drop_duplicates(subset=["merchant"])
                    save_vendor_map(vendor_map)
                    st.success("Saved! Next time these merchants will be auto-categorized.")
                    st.rerun()
        else:
            st.success("✅ All merchants categorized successfully!")
    else:
        st.warning("⚠️ No transactions found in the uploaded PDF.")
