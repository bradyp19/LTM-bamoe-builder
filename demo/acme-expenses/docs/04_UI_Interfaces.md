# UI Interfaces

### 1. ACME_FRM_Expense_Claim
**Type:** Form

#### Rule Inputs
| Input | Type | Description |
|---|---|---|
| `ri!claim` | ACME Expense Claims | The claim being filled in |
| `ri!isSubmit` | Boolean | Set by the Submit button |

Submit saves the form into `pv!claim` and sets `pv!isSubmit = true`. Cancel sets `pv!isSubmit = false`.

---

### 2. ACME_FRM_Review_Claim
**Type:** Form

#### Rule Inputs
| Input | Type | Description |
|---|---|---|
| `ri!claim` | ACME Expense Claims | The claim under review |
| `ri!approved` | Boolean | Set by the Approve or Reject button |

Approve sets `pv!approved = true`. Reject sets `pv!approved = false`.

---
