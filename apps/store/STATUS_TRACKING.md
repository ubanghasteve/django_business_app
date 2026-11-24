# Store App Status Tracking

## Stock Status Determination

The `stock_status` field is computed automatically based on the net quantity and low_stock_threshold:

```
Net quantity = Quantity In - Waste - Quantity Out

if Net quantity <= 0:
    stock_status = 'out_of_stock'
elif Net quantity <= low_stock_threshold:
    stock_status = 'low_stock'
else:
    stock_status = 'in_stock'
```

## Approval Status

User-set status for workflow management:
- `draft`: Initial state, not yet submitted
- `pending`: Awaiting approval
- `approved`: Approved by authorized personnel
- `rejected`: Rejected

## Workflow Status

Extended workflow states:
- `draft`: Initial state
- `pending_approval`: Submitted for approval
- `approved`: Approved
- `rejected`: Rejected
- `posted`: Finalized/posted

## Calculations

### Backend Calculations (in save())
1. `total_amount = quantity_in * unit_price`
2. `stock_balance_remaining = (quantity_in - quantity_out) * unit_price`
3. `balance_quantity = previous_balance + quantity_in - quantity_out`
4. `stock_status` auto-computed from net_quantity vs threshold

### Waste Tracking
Waste is tracked separately in WasteLog model and aggregated back to Store.waste field via signals.
