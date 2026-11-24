# Workflow and Process Models

## Process Model: ACME Submit Expense Claim

| Attribute | Value |
|---|---|
| UUID | `acme-0001` |

### Process Variables

| Variable | Type | Parameter | Required | Description |
|---|---|---|---|---|
| `claim` | ACME Expense Claims record | Yes | **Yes** | The claim being filled in |
| `isSubmit` | Boolean | No | No | Set when the employee presses Submit |

### Process Flow

```
START
  │
  ▼
[User Task: Fill Expense Claim]
  │   Interface: ACME_FRM_Expense_Claim
  │
  ├──[isSubmit = true]──▶
  │     │
  │     ▼
  │   [Service Task: Save Expense Claim]
  │     │
  │     ▼
  │    END
  │
  └──[isSubmit = false]──▶ END
```

Submit writes the claim to the ACME_EXPENSE_CLAIMS table. Cancel ends the process without writing anything.

---

## Process Model: ACME Review Expense Claim

| Attribute | Value |
|---|---|
| UUID | `acme-0002` |

### Process Variables

| Variable | Type | Parameter | Required | Description |
|---|---|---|---|---|
| `claim` | ACME Expense Claims record | Yes | **Yes** | The submitted claim |
| `approved` | Boolean | No | No | The manager's decision |

### Process Flow

```
START
  │
  ▼
[User Task: Review Expense Claim]
  │   Interface: ACME_FRM_Review_Claim
  │
  ├──[approved = true]──▶
  │     │
  │     ▼
  │   [Service Task: Record Approval]
  │     │
  │     ▼
  │    END
  │
  └──[approved = false]──▶
        │
        ▼
      [Service Task: Record Rejection]
        │
        ▼
       END
```

An approval is written to the ACME_APPROVED_CLAIMS table; a rejection to the ACME_REJECTED_CLAIMS table.
