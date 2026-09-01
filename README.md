# Maybank Statement Tool

This folder contains Maybank credit-card and debit-account statements, plus a local PDF-to-CSV extraction tool. The default credit-card statements folder is `F:\Projects\Maybank Credit Card Statement\Credit Statements`; the default debit-account folder is `F:\Projects\Maybank Credit Card Statement\Debit Statements`.

## Run

From PowerShell in this folder, launch the GUI:

```powershell
& ".\.venv\Scripts\python.exe" ".\maybank_statement_tool.py"
```

The statements folder is prefilled in the GUI. Use **Browse...** to select a different folder, or keep the hard-coded default. The default credit-card output is `output\maybank_credit_transactions.csv`.

For a headless run, supply the input and output paths:

```powershell
& ".\.venv\Scripts\python.exe" ".\maybank_statement_tool.py" `
  "F:\Projects\Maybank Credit Card Statement\Credit Statements" `
  ".\output\maybank_credit_transactions.csv"
```

The credit-card CSV contains the source PDF, statement date, account, posting date, transaction date, description, amount, entry type, source page, and transaction category. The parser reads every page and uses the PDF layout to associate dates, descriptions, and amounts.

Select **Debit account** in the GUI to process `F:\Projects\Maybank Credit Card Statement\Debit Statements`. It writes `output\maybank_debit_transactions.csv` and `output\maybank_debit_reconciliation.csv`. The transaction CSV includes the entry date, description, amount, entry type, statement balance, and category. The reconciliation CSV compares extracted credits and debits with each statement's reported balances.

For a headless debit run:

```powershell
& ".\.venv\Scripts\python.exe" ".\maybank_statement_tool.py" `
  --mode debit `
  "F:\Projects\Maybank Credit Card Statement\Debit Statements" `
  ".\output\maybank_debit_transactions.csv"
```