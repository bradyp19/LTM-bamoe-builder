# Data Model

## Record Type: ACME Expense Claims

**Primary Key:** `claimId`

### Fields

| Field Name | Data Type | Nullable | Description |
|---|---|---|---|
| `claimId` | Integer | No | Key |
| `employeeName` | Text | No | Who is claiming |
| `amount` | Decimal | No | Claimed amount |
| `spentOn` | Date | No | Date of the expense |
| `description` | Text | Yes | What it was for |
