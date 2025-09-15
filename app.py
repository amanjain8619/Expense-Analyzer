import streamlit as st
import pandas as pd
import pdfplumber
import re
import matplotlib.pyplot as plt

st.title("💳 Expense Analyzer")
st.write("Upload your bank/credit card statement PDF and get insights!")

# File uploader
uploaded_file = st.file_uploader("Upload PDF Statement", type=["pdf"])

# Function to extract transactions
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

# Function to categorize merchants
def categorize_expenses(df):
    categories = {
        "Food": ["swiggy", "zomato", "dominos", "mcdonald", "pizza"],
        "Shopping": ["amazon", "flipkart", "myntra"],
        "Travel": ["uber", "ola", "irctc", "indigo"],
        "Utilities": ["electricity", "gas", "water", "recharge", "airtel", "jio"],
        "Entertainment": ["netflix", "spotify", "hotstar", "prime"]
    }
    def get_category(merchant):
        m = merchant.lower()
        for cat, keywords in categories.items():
            if any(k in m for k in keywords):
                return cat
        return "Others"
    df["Category"] = df["Merchant"].apply(get_category)
    return df

# Function to analyze expenses
def analyze_expenses(df):
    st.subheader("💰 Total Spent")
    st.write(f"₹ {df['Amount'].sum():,.2f}")

    st.subheader("📊 Expense by Category")
    category_data = df.groupby("Category")["Amount"].sum()
    st.dataframe(category_data)

    # Bar chart
    fig, ax = plt.subplots()
    category_data.plot(kind="bar", ax=ax, title="Expenses by Category")
    ax.set_ylabel("Amount (₹)")
    st.pyplot(fig)

    st.subheader("🏦 Top 5 Merchants")
    st.dataframe(df.groupby("Merchant")["Amount"].sum().sort_values(ascending=False).head())

# Run pipeline when file is uploaded
if uploaded_file:
    df = extract_transactions_from_pdf(uploaded_file)
    if not df.empty:
        df = categorize_expenses(df)
        st.dataframe(df)
        analyze_expenses(df)
    else:
        st.warning("⚠️ No transactions found in the uploaded PDF.")
