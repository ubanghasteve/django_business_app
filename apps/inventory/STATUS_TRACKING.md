# Status tracking – how each status is determined

This document tracks how every status label used in the app is determined, where it is stored, and when it updates. The goal is **accuracy**: one clear rule per status, persisted in the database and reflected on refresh.

---

## 1. In Stock

| Aspect | Detail |
|--------|--------|
| **Where** | `apps.inventory.models.Inventory.stock_status` |
| **Rule** | **Computed** on every save: **Rem. qqt** (remaining_quantity) > low_stock_threshold and Rem. qqt > 0. |
| **Source of truth** | `_compute_stock_status()` in `Inventory.save()`; uses same quantity as the "Rem. qqt" column. |
| **When it updates** | On create; on any full save (e.g. inline edit of quantity in/out, unit price, or low_stock_threshold). |
| **Display** | List: `{{ obj.get_stock_status_display }}`; badge class `stock-in_stock`. AJAX field update returns `stock_status` / `stock_status_display` so the badge updates in real time. |
| **Persists on refresh?** | Yes. Value is stored in DB; list and filters read from server. |

---

## 2. Low Stock

| Aspect | Detail |
|--------|--------|
| **Where** | `apps.inventory.models.Inventory.stock_status` |
| **Rule** | **Computed**: `0 < Rem. qqt (remaining_quantity) <= low_stock_threshold`. When Rem. qqt is less than threshold → Low Stock. |
| **Source of truth** | `_compute_stock_status()` in `Inventory.save()`. |
| **When it updates** | Same as In Stock (every full save). |
| **Display** | Same as In Stock; badge class `stock-low_stock`. |
| **Persists on refresh?** | Yes. |

---

## 3. Out of Stock

| Aspect | Detail |
|--------|--------|
| **Where** | `apps.inventory.models.Inventory.stock_status` |
| **Rule** | **Computed**: Rem. qqt (remaining_quantity) <= 0. |
| **Source of truth** | `_compute_stock_status()` in `Inventory.save()`. |
| **When it updates** | Same as In Stock (every full save). |
| **Display** | Same as In Stock; badge class `stock-out_of_stock`. |
| **Persists on refresh?** | Yes. |

---

## 4. Approved

| Aspect | Detail |
|--------|--------|
| **Where** | `apps.inventory.models.Inventory.approval_status` (and elsewhere: expenses, job orders, requisitions). |
| **Rule** | **User-set**. User selects "Approved" in the approval dropdown (or equivalent in other apps). |
| **Source of truth** | Stored in DB: `Inventory.approval_status`; updated via `ajax_status_update` (list) or form save. |
| **When it updates** | When the user changes the approval dropdown; or admin/API sets it. |
| **Display** | List: approval `<select>` and optional badge; filters use `approval_choices`. |
| **Persists on refresh?** | Yes. List is not cached by Service Worker; no-cache headers on inventory views. |

---

## 5. In Transit

| Aspect | Detail |
|--------|--------|
| **Where** | **Waybills**: `apps.waybills` (waybill `status`); **Job orders**: `apps.job_orders.models.Waybill.WAYBILL_STATUS`. |
| **Rule** | **User-set or workflow**. Waybill status `in_transit` (or `dispatched` in waybills views) means shipment is on the way. |
| **Source of truth** | Waybill/job order model `status` field in DB. |
| **Inventory** | Inventory app does **not** have an "In Transit" stock status. It only has In Stock, Low Stock, Out of Stock. In Transit is a **shipment/waybill** concept, not a per-row inventory stock status. |

---

## 6. Reserved

| Aspect | Detail |
|--------|--------|
| **Where** | **Not used** in current `Inventory` model. |
| **Rule** | N/A. Previously existed in legacy `InventoryStatus` (removed in migration 0002_rebuild_inventory). |
| **If you need it** | Would be **user-set** (e.g. "Reserved" for an order). Would require adding to `Inventory.STOCK_STATUS_CHOICES` and either a separate field or extending stock_status with a manual override. |

---

## 7. Overstock

| Aspect | Detail |
|--------|--------|
| **Where** | **Not used** in current `Inventory` model. |
| **Rule** | N/A. Could be **computed** in future as `balance_quantity > high_stock_threshold` if you add a high threshold field. |
| **If you need it** | Add `high_stock_threshold` and extend `_compute_stock_status()` to return `overstock` when `balance_quantity > high_stock_threshold`. |

---

## 8. Backordered

| Aspect | Detail |
|--------|--------|
| **Where** | **Not used** in current `Inventory` model. |
| **Rule** | N/A. Would be **user-set** (order placed, stock not yet received). |
| **If you need it** | Add to `STOCK_STATUS_CHOICES` and set manually, or add a separate "supply status" field. |

---

## 9. Pre-Order

| Aspect | Detail |
|--------|--------|
| **Where** | **Not used** in current `Inventory` model. |
| **Rule** | N/A. Would be **user-set**. |
| **If you need it** | Same as Backordered – add to choices or a separate field. |

---

## 10. Damaged

| Aspect | Detail |
|--------|--------|
| **Where** | **Not used** in current `Inventory` model. |
| **Rule** | N/A. Would be **user-set** (item damaged, not sellable). |
| **If you need it** | Add to `STOCK_STATUS_CHOICES` and set manually. |

---

## Summary table

| Status      | Module      | How determined | Stored in DB | Accurate today |
|------------|-------------|------------------|--------------|----------------|
| In Stock   | inventory   | Computed (balance > threshold, > 0) | Yes | Yes |
| Low Stock  | inventory   | Computed (0 < balance ≤ threshold)  | Yes | Yes |
| Out of Stock | inventory | Computed (balance ≤ 0)             | Yes | Yes |
| Approved   | inventory (and expenses, job_orders, etc.) | User-set | Yes | Yes |
| In Transit | waybills / job_orders | User-set or workflow (waybill status) | Yes | Yes (in those apps) |
| Reserved   | —           | Not implemented in Inventory        | No  | N/A |
| Overstock  | —           | Not implemented                     | No  | N/A |
| Backordered| —           | Not implemented in Inventory        | No  | N/A |
| Pre-Order  | —           | Not implemented in Inventory        | No  | N/A |
| Damaged    | —           | Not implemented in Inventory        | No  | N/A |

---

## Formulas (inventory, single source of truth)

- **balance_quantity** = previous record’s `balance_quantity` (by company) + `quantity_in` − `quantity_out`. (Used for "Balance qty" column.)
- **Rem. qqt (remaining_quantity)** = `quantity_in` − `quantity_out` for this row (same as the Rem. qqt column).
- **stock_status** (compared to **Rem. qqt** so the badge matches the column):
  - `out_of_stock` if Rem. qqt <= 0
  - `low_stock` if `0 < Rem. qqt <= low_stock_threshold`
  - `in_stock` if Rem. qqt > low_stock_threshold

All are recomputed in `Inventory.save()` and persisted; list and AJAX field update use this stored value so the badge is accurate and survives refresh.

---

### Threshold in sync with row and cards

- **Low stock threshold** is per record. When you change it (inline or on save), the backend runs `obj.save()`, which recomputes **stock_status** from **Rem. qqt** and the new `low_stock_threshold`. No other row is changed.
- **Important:** Status is based on **Rem. qqt** (remaining quantity for that row), not the running balance. If Rem. qqt is *less than or equal to* the threshold (e.g. Rem. qqt 189, threshold 267), the status is **Low Stock**.
- **Robustness:** Threshold is clamped to ≥ 0 in `save()`. On AJAX threshold update, empty input or parse failure keeps the existing threshold (never overwrites with 0, which would incorrectly show "In Stock" for all positive balances).
- **AJAX update response** (`ajax_update_field`) always returns the full row state: `remaining_quantity`, `total_amount`, `quantity_in`, `quantity_out`, `unit_price`, `stock_status`, `stock_status_display`, `low_stock_threshold`. The list page uses this to refresh the entire row (Rem. qqt, Balance, Stock badge, threshold, etc.) so the table stays in sync with the database.
- **Dashboard cards** (Total Products, Total Qty In/Out, Draft/Pending/Approved/Rejected, In Stock/Low Stock/Out of Stock) are refreshed after every successful field save via `refreshDashboardCards()`, so card counts stay in sync when the threshold (or any field) changes.
