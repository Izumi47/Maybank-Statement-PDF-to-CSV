"""Extract Maybank credit-card PDF statements into an auditable CSV."""

from __future__ import annotations

import argparse
import csv
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import fitz


DATE_RE = re.compile(r"^\d{2}/\d{2}$")
DEBIT_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
AMOUNT_RE = re.compile(r"^(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)(CR)?$", re.I)
SIGNED_AMOUNT_RE = re.compile(r"^(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)([+-])$")
STATEMENT_DATE_RE = re.compile(r"(\d{2})\s+([A-Z]{3})\s+(\d{2})", re.I)
MONTHS = {name: number for number, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
    1,
)}
IGNORED_LINES = {
    "posting date",
    "transaction date",
    "transaction description",
    "amount(rm)",
    "total credit this month",
    "total debit this month",
    "sub total/ jumlah",
    "sub total/jumlah",
}
DEFAULT_INPUT = Path(r"F:\Projects\Maybank Credit Card Statement\Credit Statements")
DEFAULT_OUTPUT = Path(__file__).parent / "output" / "maybank_credit_transactions.csv"
DEFAULT_DEBIT_INPUT = Path(r"F:\Projects\Maybank Credit Card Statement\Debit Statements")
DEFAULT_DEBIT_OUTPUT = Path(__file__).parent / "output" / "maybank_debit_transactions.csv"


@dataclass
class VisualLine:
    y: float
    words: list[tuple[float, str]]

    @property
    def text(self) -> str:
        return " ".join(word for _, word in self.words).strip()


def visual_lines(page: fitz.Page) -> list[VisualLine]:
    grouped: list[VisualLine] = []
    words = sorted(page.get_text("words"), key=lambda item: (item[1], item[0]))
    for x0, y0, _x1, y1, text, *_ in words:
        center_y = (y0 + y1) / 2
        line = next((candidate for candidate in grouped if abs(candidate.y - center_y) <= 2.5), None)
        if line is None:
            line = VisualLine(center_y, [])
            grouped.append(line)
        line.words.append((x0, text))
    for line in grouped:
        line.words.sort()
    return sorted(grouped, key=lambda item: item.y)


def parse_amount(value: str) -> tuple[float, str] | None:
    match = AMOUNT_RE.fullmatch(value.strip())
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    if match.group(2):
        return -amount, "credit"
    return amount, "debit"


def parse_signed_amount(value: str) -> tuple[float, str] | None:
    match = SIGNED_AMOUNT_RE.fullmatch(value.strip())
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    if match.group(2) == "+":
        return amount, "credit"
    return -amount, "debit"


def get_statement_date(text: str, filename: str) -> date:
    match = STATEMENT_DATE_RE.search(text.upper())
    if match:
        return date(2000 + int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))
    fallback = re.search(r"(20\d{2})(\d{2})(\d{2})", filename)
    if fallback:
        return date(int(fallback.group(1)), int(fallback.group(2)), int(fallback.group(3)))
    raise ValueError(f"Could not determine statement date for {filename}")


def get_account(lines: list[VisualLine], index: int, current: str) -> str:
    for line in reversed(lines[max(0, index - 12):index + 1]):
        text = line.text.upper()
        if "MAYBANK 2 GOLD AMEX" in text:
            return "Maybank 2 Gold Amex"
        if "MAYBANK 2 GOLD VISA" in text:
            return "Maybank 2 Gold Visa"
    return current


def categorize_transaction(description: object, entry_type: object) -> str:
    text = str(description).upper()
    rules = (
        ("Refund", ("REFUND", "REV PREAUTH")),
        ("Income", ("SALARY", "SVG GIRO CR")),
        ("Cash Withdrawal", ("CASH WITHDRAWAL",)),
        ("Interest Income", ("PROFIT PAID",)),
        ("Donations", ("ZAKAT",)),
        ("Card Payment", ("PYMT@MAYBANK2U.COM", "PYMT FROM A/C MAYBANK VISA CARD", "PYMT FROM A/C AMERICAN EXPRESS", "PAYMENT FR A/", "PAYMENT TO A/")),
        ("Installment", ("TRANSFER TO INSTALLMENT", "EZYPAY")),
        ("Insurance", ("PRUBSN", "PRUDENTIAL", "INSURANCE")),
        ("Rent", ("SEWA", "RENT", "SPEEDRENT")),
        ("Utilities", ("U MOBILE", "TIMEDOTCOM", "TNB", "ELECTRIC", "WATER BILL")),
        ("Groceries", ("JAYA GROCER", "LOTUS", "NSK ", "TCRS", "TESCO", "99 SPEEDMART", "SPEEDMART", "KK SUPER MART", "MYNEWS", "ECO-")),
        ("Pets", ("PET", "VETERINARY", "VET CLINIC", "AMYCATZ", "SIFOO PETS", "DR DOLITTLE")),
        ("Healthcare", ("CLINIC", "DENTAL", "KLINIK", "WATSON", "PHARMACY", "BIG PHARMACY", "P.KLINIK", "GUARDIAN")),
        ("Dining", ("RESTAURANT", "REST ", "FOODPANDA", "TC-SIZZLING", "BBQ TOWN", "MEE TARIK", "K FRY", "DUBUYO", "WASABI", "KEN CHAN", "BOOST JUICE", "LOOB ", "THE BOUSTEADOR", "SHINE SHINE", "KRISPY KREME", "MIXUE", "FUDTEC", "GOOD TASTE", "KFC", "SUSHI KING", "AWESOME SNACKS", "DAE MAEK")),
        ("Transport", ("SHELL", "SETEL", "GRAB RIDES", "AIRASIA", "PERODUA", "CAR PARK", "SMART PARKING", "MYDEBIT LDP", "TIMBRE", "MSPR", "STRM ", "CTX ", "ENERGY")),
        ("Shopping", ("SHOPEE", "SHOPEEPAY", "TIKTOK SHOP", "SPAYLATER", "MR DIY", "BRANDS OUTLET", "SPORTS DIRECT", "APSB_", "APSB ", "IT LEVEL", "TFM-", "7 ELEVEN", "7ELEVEN")),
        ("Digital Services", ("GITHUB", "OPENROUTER", "MOONSHOT AI", "MUDFISH", "NGROK", "MUSESCORE", "DEVELOPER.X", "VAST.AI", "GOOGLE ", "GOOGLE*", "CURSOR", "VPN*", "NETFLIX", "BNYTOOLS", "ANLATAN")),
        ("Entertainment", ("STEAMGAMES", "STEAM PURCHASE", "ROBLOX", "GSC", "GOLDEN SCREEN", "SUNWAY LOST WORLD", "MICROSOFT*STORE", "ZEUSX", "XSOLLA")),
        ("Accommodation", ("MOVENPICK", "HOTEL")),
        ("Government", ("MAJLIS", "SSM", "MARA")),
        ("Bank Transfer", ("FUND TRANSFER", "TRANSFER FROM", "TRANSFER TO", "DUITNOW", "IBK FUND TFR")),
        ("Bank Fees", ("SERVICE TAX", "INTEREST", "CHARGE", "FEE")),
    )
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    if entry_type == "credit":
        return "Other Credit"
    return "Other"


def parse_pdf(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    document = fitz.open(path)
    current_account = "Unknown"
    statement = None
    try:
        for page_number, page in enumerate(document, 1):
            lines = visual_lines(page)
            statement = statement or get_statement_date("\n".join(line.text for line in lines), path.name)
            in_table = False
            active: dict[str, object] | None = None
            for index, line in enumerate(lines):
                normalized = re.sub(r"\s+", " ", line.text.strip()).lower()
                current_account = get_account(lines, index, current_account)
                if "posting date" in normalized and "transaction date" in normalized:
                    in_table = True
                    continue
                if not in_table:
                    continue
                if normalized.startswith(("maybank card treats", "treatspoints", "warning on", "current payment")):
                    in_table = False
                    continue
                if "total credit this month" in normalized or "sub total" in normalized:
                    in_table = False
                    continue
                dates = [word for _, word in line.words if DATE_RE.fullmatch(word)]
                amount_items = [(word, parsed) for _, word in line.words if (parsed := parse_amount(word))]
                if len(dates) >= 2:
                    if active and active.get("Amount") is not None:
                        rows.append(active)
                    amount = amount_items[-1][1] if amount_items else None
                    date_words = dates[:2]
                    description_words = [word for _, word in line.words if word not in date_words]
                    if amount:
                        description_words = [word for word in description_words if word != amount_items[-1][0]]
                    active = {
                        "Statement File": path.name,
                        "Statement Date": statement.isoformat(),
                        "Account": current_account,
                        "Posting Date": date_words[0],
                        "Transaction Date": date_words[1],
                        "Description": " ".join(description_words),
                        "Amount": amount[0] if amount else None,
                        "Entry Type": amount[1] if amount else None,
                        "Page": page_number,
                    }
                elif active:
                    if amount_items and active.get("Amount") is None:
                        amount_word, amount = amount_items[-1]
                        active["Amount"] = amount[0]
                        active["Entry Type"] = amount[1]
                        text_words = [word for _, word in line.words if word != amount_word]
                    else:
                        text_words = [word for _, word in line.words]
                    continuation = " ".join(text_words).strip()
                    if continuation and continuation.lower() not in IGNORED_LINES:
                        active["Description"] = f"{active['Description']} {continuation}".strip()
            if active and active.get("Amount") is not None:
                rows.append(active)
    finally:
        document.close()
    return [row for row in rows if row["Amount"] is not None and row["Description"]]


def parse_debit_pdf(path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    document = fitz.open(path)
    statement = None
    beginning = ending = total_credit = total_debit = None
    try:
        for page_number, page in enumerate(document, 1):
            lines = visual_lines(page)
            page_text = "\n".join(line.text for line in lines)
            statement = statement or get_statement_date(page_text, path.name)
            in_table = False
            active: dict[str, object] | None = None
            for line in lines:
                normalized = re.sub(r"\s+", " ", line.text.strip()).lower()
                candidate_dates = [word for _, word in line.words if DEBIT_DATE_RE.fullmatch(word)]
                is_footer_date = "statement date" in normalized or "結單日期" in normalized
                if candidate_dates and not is_footer_date:
                    in_table = True
                if normalized == "beginning balance":
                    in_table = True
                    continue
                if "entry date" in normalized and "transaction description" in normalized:
                    in_table = True
                    continue
                if not in_table:
                    continue
                if normalized.startswith(("maybank islamic", "protected by pidm", "savings account", "perhation", "all items")):
                    if active and active.get("Amount") is not None:
                        rows.append(active)
                        active = None
                    in_table = False
                    continue
                if normalized.startswith("ending balance"):
                    if active and active.get("Amount") is not None:
                        rows.append(active)
                        active = None
                    match = re.search(r"([\d,]+\.\d{2})", line.text)
                    if match:
                        ending = float(match.group(1).replace(",", ""))
                    in_table = False
                    continue
                for label, target in (("beginning balance", "beginning"), ("total credit", "credit"), ("total debit", "debit")):
                    if normalized.startswith(label):
                        if active and active.get("Amount") is not None:
                            rows.append(active)
                            active = None
                        match = re.search(r"([\d,]+\.\d{2})", line.text)
                        if match:
                            value = float(match.group(1).replace(",", ""))
                            if target == "beginning":
                                beginning = value
                            elif target == "credit":
                                total_credit = value
                            else:
                                total_debit = value
                        in_table = False
                        break
                else:
                    dates = [word for _, word in line.words if DEBIT_DATE_RE.fullmatch(word)]
                    signed_amounts = [(word, parsed) for _, word in line.words if (parsed := parse_signed_amount(word))]
                    balances = [word for _, word in line.words if re.fullmatch(r"\d{1,3}(?:,\d{3})*\.\d{2}", word)]
                    if dates:
                        if active and active.get("Amount") is not None:
                            rows.append(active)
                        amount = signed_amounts[-1][1] if signed_amounts else None
                        amount_word = signed_amounts[-1][0] if signed_amounts else None
                        balance = float(balances[-1].replace(",", "")) if balances else None
                        description = [word for _, word in line.words if word not in dates]
                        if amount_word:
                            description = [word for word in description if word != amount_word]
                        if balance is not None:
                            description = [word for word in description if word != balances[-1]]
                        active = {
                            "Statement File": path.name,
                            "Statement Date": statement.isoformat(),
                            "Account": "Savings Account-I",
                            "Entry Date": dates[0],
                            "Description": " ".join(description),
                            "Amount": amount[0] if amount else None,
                            "Entry Type": amount[1] if amount else None,
                            "Statement Balance": balance,
                            "Page": page_number,
                        }
                    elif active:
                        if signed_amounts and active.get("Amount") is None:
                            amount_word, amount = signed_amounts[-1]
                            active["Amount"] = amount[0]
                            active["Entry Type"] = amount[1]
                            continuation = [word for _, word in line.words if word != amount_word]
                        else:
                            continuation = [word for _, word in line.words]
                        if balances and active.get("Statement Balance") is None:
                            active["Statement Balance"] = float(balances[-1].replace(",", ""))
                            continuation = [word for word in continuation if word != balances[-1]]
                        text = " ".join(continuation).strip()
                        if text and text.lower() not in IGNORED_LINES:
                            active["Description"] = f"{active['Description']} {text}".strip()
            if active and active.get("Amount") is not None:
                rows.append(active)
    finally:
        document.close()
    clean_rows = [row for row in rows if row["Amount"] is not None and row["Statement Balance"] is not None and row["Description"]]
    summary = {
        "Statement File": path.name,
        "Statement Date": statement.isoformat() if statement else None,
        "Beginning Balance": beginning,
        "Total Credit": total_credit,
        "Total Debit": total_debit,
        "Ending Balance": ending,
    }
    return clean_rows, summary


def write_csv(rows: list[dict[str, object]], output: Path) -> None:
    categorized_rows = []
    for row in rows:
        categorized = dict(row)
        categorized["Category"] = categorize_transaction(categorized.get("Description"), categorized.get("Entry Type"))
        categorized_rows.append(categorized)
    fields = list(categorized_rows[0]) if categorized_rows else []
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(categorized_rows)


def write_debit_outputs(input_folder: Path, transaction_output: Path, reconciliation_output: Path) -> tuple[int, float, float]:
    pdfs = sorted(input_folder.glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDF statements found in {input_folder}")
    all_rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for pdf in pdfs:
        rows, summary = parse_debit_pdf(pdf)
        all_rows.extend(rows)
        calculated_credits = round(sum(float(row["Amount"]) for row in rows if float(row["Amount"]) > 0), 2)
        calculated_debits = round(-sum(float(row["Amount"]) for row in rows if float(row["Amount"]) < 0), 2)
        beginning_balance = summary["Beginning Balance"]
        ending_balance = summary["Ending Balance"]
        expected_credit = summary["Total Credit"]
        expected_debit = summary["Total Debit"]
        calculated_ending = (
            round(float(beginning_balance) + calculated_credits - calculated_debits, 2)
            if beginning_balance is not None
            else None
        )
        difference = (
            round(calculated_ending - float(ending_balance), 2)
            if calculated_ending is not None and ending_balance is not None
            else None
        )
        status = (
            "PASS"
            if calculated_ending is not None
            and ending_balance is not None
            and expected_credit is not None
            and expected_debit is not None
            and calculated_ending == float(ending_balance)
            and calculated_credits == float(expected_credit)
            and calculated_debits == float(expected_debit)
            else "REVIEW"
        )
        summary.update({
            "Extracted Credit": calculated_credits,
            "Extracted Debit": calculated_debits,
            "Calculated Ending Balance": calculated_ending,
            "Difference": difference,
            "Status": status,
        })
        summaries.append(summary)
    write_csv(all_rows, transaction_output)
    reconciliation_output.parent.mkdir(parents=True, exist_ok=True)
    with reconciliation_output.open("w", newline="", encoding="utf-8") as handle:
        fields = list(summaries[0])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)
    amounts = [float(row["Amount"]) for row in all_rows]
    return len(all_rows), -sum(amount for amount in amounts if amount < 0), sum(amount for amount in amounts if amount > 0)


def extract_folder(input_folder: Path, output_file: Path) -> tuple[int, float, float]:
    pdfs = sorted(input_folder.glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDF statements found in {input_folder}")
    rows = [row for pdf in pdfs for row in parse_pdf(pdf)]
    write_csv(rows, output_file)
    amounts = [float(row["Amount"]) for row in rows]
    credits = -sum(amount for amount in amounts if amount < 0)
    debits = sum(amount for amount in amounts if amount > 0)
    return len(rows), debits, credits


def run_gui() -> None:
    root = tk.Tk()
    root.title("Maybank Statement Tool")
    root.geometry("760x220")
    root.minsize(620, 220)

    input_var = tk.StringVar(value=str(DEFAULT_INPUT))
    output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
    mode_var = tk.StringVar(value="Credit card")
    status_var = tk.StringVar(value="Ready")

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill=tk.BOTH, expand=True)
    frame.columnconfigure(1, weight=1)

    ttk.Label(frame, text="Statement type").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=6)
    mode = ttk.Combobox(frame, textvariable=mode_var, values=("Credit card", "Debit account"), state="readonly")
    mode.grid(row=0, column=1, sticky=tk.W, pady=6)

    def update_defaults(_event: object | None = None) -> None:
        if mode_var.get() == "Debit account":
            input_var.set(str(DEFAULT_DEBIT_INPUT))
            output_var.set(str(DEFAULT_DEBIT_OUTPUT))
        else:
            input_var.set(str(DEFAULT_INPUT))
            output_var.set(str(DEFAULT_OUTPUT))

    mode.bind("<<ComboboxSelected>>", update_defaults)

    ttk.Label(frame, text="Statements folder").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=6)
    ttk.Entry(frame, textvariable=input_var).grid(row=1, column=1, sticky=tk.EW, pady=6)

    def browse_folder() -> None:
        selected = filedialog.askdirectory(initialdir=input_var.get(), title="Select statements folder")
        if selected:
            input_var.set(selected)

    ttk.Button(frame, text="Browse...", command=browse_folder).grid(row=1, column=2, padx=(8, 0), pady=6)

    ttk.Label(frame, text="Output CSV").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=6)
    ttk.Entry(frame, textvariable=output_var).grid(row=2, column=1, sticky=tk.EW, pady=6)

    def browse_output() -> None:
        selected = filedialog.asksaveasfilename(
            initialdir=str(DEFAULT_OUTPUT.parent),
            initialfile=Path(output_var.get()).name,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Choose output CSV",
        )
        if selected:
            output_var.set(selected)

    ttk.Button(frame, text="Choose...", command=browse_output).grid(row=2, column=2, padx=(8, 0), pady=6)

    def process() -> None:
        try:
            if mode_var.get() == "Debit account":
                reconciliation = Path(output_var.get()).with_name("maybank_debit_reconciliation.csv")
                count, debits, credits = write_debit_outputs(Path(input_var.get()), Path(output_var.get()), reconciliation)
            else:
                count, debits, credits = extract_folder(Path(input_var.get()), Path(output_var.get()))
        except (OSError, ValueError, RuntimeError) as error:
            status_var.set("Processing failed")
            messagebox.showerror("Processing failed", str(error), parent=root)
            return
        net = debits - credits
        status_var.set(f"Completed: {count} transactions")
        messagebox.showinfo(
            "Processing complete",
            f"Wrote {count} transactions.\n\n"
            f"Debits: RM{debits:,.2f}\n"
            f"Credits: RM{credits:,.2f}\n"
            f"Net: RM{net:,.2f}",
            parent=root,
        )

    ttk.Button(frame, text="Process statements", command=process).grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=(14, 8))
    ttk.Label(frame, textvariable=status_var).grid(row=4, column=0, columnspan=3, sticky=tk.W)
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Maybank credit-card or debit-account statements.")
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--mode", choices=("credit", "debit"))
    args = parser.parse_args()
    mode = args.mode or "credit"
    if args.input is None and args.output is None and args.mode is None:
        run_gui()
        return
    input_folder = args.input or (DEFAULT_DEBIT_INPUT if mode == "debit" else DEFAULT_INPUT)
    output_file = args.output or (DEFAULT_DEBIT_OUTPUT if mode == "debit" else DEFAULT_OUTPUT)
    if mode == "debit":
        reconciliation = output_file.with_name("maybank_debit_reconciliation.csv")
        count, debits, credits = write_debit_outputs(input_folder, output_file, reconciliation)
    else:
        count, debits, credits = extract_folder(input_folder, output_file)
    print(f"Wrote {count} transactions to {output_file}")
    print(f"Debits: RM{debits:,.2f} | Credits: RM{credits:,.2f} | Net: RM{debits - credits:,.2f}")


if __name__ == "__main__":
    main()