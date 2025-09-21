def extract_transactions_from_pdf(pdf_file, account_name, debug=False):
    transactions = []
    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):

            text = page.extract_text()
            if debug and text:
                st.write(f"🔎 Debug Text Page {page_num}", text.split("\n")[:20])

            if not text:
                continue

            lines = [l.strip() for l in text.split("\n") if l.strip()]

            for line in lines:
                # ----------------------------
                # 1️⃣ HDFC / ICICI / BoB style
                # ----------------------------
                m1 = re.match(r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d,]+\.\d{2})\s?(CR|DR)?", line)
                if m1:
                    date, merchant, amount, drcr = m1.groups()
                    amt = float(amount.replace(",", ""))
                    if drcr and drcr.upper() == "CR":
                        amt = -amt
                    transactions.append([parse_date(date), merchant.strip(), round(amt, 2), drcr if drcr else "DR", account_name])
                    continue

                # ----------------------------
                # 2️⃣ AMEX style (Month DD ...)
                # Example: "July 15 TRIDENT NARIMAN POINT 4,973.70"
                # ----------------------------
                m2 = re.match(r"([A-Za-z]{3,9}\s+\d{1,2})\s+(.+?)\s+([\d,]+\.\d{2})$", line)
                if m2:
                    date_str, merchant, amount = m2.groups()
                    amt = float(amount.replace(",", ""))
                    drcr = "DR"

                    # Detect credits (sometimes AMEX shows "Payment Received" or "Credit")
                    if "CR" in line.upper() or "CREDIT" in line.upper() or "PAYMENT RECEIVED" in line.upper():
                        amt = -amt
                        drcr = "CR"

                    transactions.append([parse_date(date_str), merchant.strip(), round(amt, 2), drcr, account_name])
                    continue

            st.info(f"📄 Page {page_num}: extracted {len(transactions)} rows so far")

    return pd.DataFrame(transactions, columns=["Date", "Merchant", "Amount", "Type", "Account"])
