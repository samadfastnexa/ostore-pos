# Comprehensive Technical Audit: Thermal Printing & All Subsequent Commits

**Module:** `pos_retail`  
**Branch:** `feature/branch-scoped-users-and-dashboard`  
**Target URL:** `https://169-58-143-45.sslip.io/pos/ui/2/login`  
**Audit Date:** September 17, 2026  
**Auditor:** Antigravity Pairing Agent  

---

## 1. Executive Summary & Purpose

This audit documents every modification introduced during the **Thermal Printing** implementation (thermal barcode labels and thermal receipts) and **all subsequent commits** up to HEAD (`5d289ba`). 

Its primary objective is to dissect every line of code changed across the backend models, frontend OWL components, QWeb templates, XML security rules, and SCSS styles to diagnose why the Point of Sale login screen or register unlocking has continued to experience hangs or unresponsiveness.

---

## 2. Complete Commits Chronology (11 Commits)

| # | Commit | Date (PKT) | Type | Subject Line |
|---|--------|------------|------|--------------|
| 1 | `c4867a3` | Sep 16 02:49 | Feature | **feat(thermal-labels):** implement multi-format thermal barcode label printing system |
| 2 | `079e5a3` | Sep 16 03:13 | Fix | **fix(thermal-labels):** replace private _compute_preview_html button with action_refresh_preview |
| 3 | `42fa805` | Sep 16 03:17 | Chore | **chore:** clean deprecation warning for @route jsonrpc and set explicit string for wizard line product_name |
| 4 | `0d7c3df` | Sep 16 14:30 | Fix | **fix(thermal-labels):** add config argument to _load_pos_data_domain on preset model |
| 5 | `e96d14c` | Sep 16 16:54 | Feature | **feat(pos):** real-time stock deduction per completed order and live UI updates |
| 6 | `215a87b` | Sep 16 18:04 | Feature | **feat(receipt):** hide total discount from receipt while preserving full backend discount logs |
| 7 | `26f4580` | Sep 16 19:03 | Fix | **fix(pos):** resolve session undefined crash on pos login, scope session loading to branch company, and guard closeOtherTabs |
| 8 | `9b52041` | Sep 16 19:38 | Fix | **fix(pos):** prevent hardware proxy hang on startup, guard LoginScreen getters, and add loader dismissal watchdog |
| 9 | `d8789c3` | Sep 17 00:28 | Feature | **feat(pos):** add comprehensive diagnostic console logs and global error listeners for POS startup |
| 10| `4987fa2` | Sep 17 01:29 | Fix | **fix(pos):** resolve login screen CPU freeze on Firefox by removing backdrop blur and caching static getters |
| 11| `5d289ba` | Sep 17 02:07 | Fix | **fix(pos):** prevent loader click blockage and enable seamless cashier login on open register |

---

## 3. What Was Changed in Thermal Printing

Thermal printing modifications encompass two systems:
1. **Thermal Barcode Label Printing System** (`c4867a3` through `0d7c3df`).
2. **Thermal Customer Receipt Printing** (`215a87b` and earlier receipt commits).

### 3.1 Thermal Barcode Label Printing System (`c4867a3`, `079e5a3`, `42fa805`, `0d7c3df`)

#### Business Requirement:
Retail branches need to print barcode shelf labels and price stickers directly onto standard continuous or die-cut thermal label rolls (40x20mm, 50x25mm, 50x30mm, etc.) without requiring an A4 laser printer.

#### Architectural Breakdown:
1. **New Model `pos.retail.thermal.label.preset` (`models/pos_retail_thermal_label_preset.py`):**
   - Inherits `pos.load.mixin` so presets are serialized to POS client memory.
   - Stores label dimensions (roll width, label width, label height, columns, gaps, margins, orientation, DPI).
   - Factory data in `data/pos_retail_thermal_label_data.xml` defines 10 presets:
     - 40x20 mm, 50x25 mm, 50x30 mm, 50x40 mm, 60x30 mm, 60x40 mm, 70x40 mm, 80x50 mm, 100x30 mm (dual), 100x40 mm (dual).
   - Generates raw templates in ZPL (Zebra), TSPL (TSC / Xprinter), EPL, and CPCL.

2. **Integration into POS Data Loader (`models/pos_session.py`):**
   - Added `'pos.retail.thermal.label.preset'` to `_load_pos_data_models(config)`.
   - **Critical Bug Caught and Fixed (`0d7c3df`):**
     In Odoo 19, `_load_pos_data_domain` takes 2 arguments: `(data, config)`.
     `c4867a3` had `def _load_pos_data_domain(self, data):`, which crashed POS data loading with `TypeError: takes 2 positional arguments but 3 were given`.
     Commit `0d7c3df` corrected this to:
     ```python
     @api.model
     def _load_pos_data_domain(self, data, config=None):
         domain = [('active', '=', True)]
         if config and hasattr(config, 'company_id') and config.company_id:
             domain += ['|', ('company_id', '=', False), ('company_id', '=', config.company_id.id)]
         return domain
     ```

3. **POS Frontend Action Pad and Popup:**
   - `static/src/overrides/till_actions.xml` and `till_actions.js`: Added "Print Label" button on the Product Screen.
   - `static/src/overrides/thermal_label_popup.js`, `xml`, `scss`: Cashier modal to choose label format, set quantity, preview SVG barcode, and send to printer.

4. **Controllers and Barcode Generator:**
   - `models/thermal_barcode_generator.py`: Vector SVG rendering for Code128, EAN-13, QR codes.
   - `controllers/thermal_label_controller.py`: `/pos_retail/thermal_label/render_preview` and `/pos_retail/thermal_label/print_raw`.

---

### 3.2 Thermal Customer Receipt Printing (`215a87b` and earlier)

#### Business Requirement:
- Receipt rolls (58mm / 80mm) have limited horizontal space. Long numbers with currency symbols caused column wrapping.
- Store management required customer receipts to hide the "Total Discount" line so customers see only the final payable total, while preserving full audit logs (`pos.retail.discount.log`) in the backend.

#### Technical Implementation (`215a87b`):
1. Added `pos_retail_receipt_show_total_discount = fields.Boolean(default=False)` on `pos.config` and `res.config.settings`.
2. Gated Total Discount row in `static/src/receipt/receipt.xml`:
   ```xml
   <div t-if="order.config.pos_retail_receipt_show_total_discount and posRetailTotalDiscount"
        class="pos-receipt-amount receipt-discount text-start pt-1">
       <span class="label-total-discount fw-normal">Total Discount</span>
       <span t-out="posRetailTotalDiscount" class="pos-receipt-right-align font-monospace text-danger"/>
   </div>
   ```
3. Gated PDF and QWeb thermal receipt reports in `report/pos_retail_receipt_report.xml`.

---

## 4. In-Depth Audit of All Subsequent Commits

---

### 4.1 Commit `e96d14c` — Real-Time Stock Deduction and Live UI Updates
- **Date:** Sep 16, 2026 16:54
- **Files Modified:** `models/pos_order.py`, `models/pos_session.py`, `static/src/overrides/negative_stock_warning.js`

#### Details:
- **Backend:**
  - Enforced `_force_create_picking_real_time()` and `_should_create_picking_real_time()` on `PosOrder` returning `True`.
  - Overrode `PosSession.create` to force `vals['update_stock_at_closing'] = False`.
  - Overrode `PosSession._load_pos_data_read` to return `update_stock_at_closing = False` to POS client.
- **Frontend:**
  - In `negative_stock_warning.js`, hooked `OrderPaymentValidation.prototype.finalizeValidation` and `PaymentScreen.prototype.validateOrder`.
  - Decrements storable product quantities in client memory instantly upon order validation.
  - Calls `pos.data.read("product.product", productIds, ["qty_available"])` asynchronously in background.

---

### 4.2 Commit `215a87b` — Hide Total Discount from Receipt
- **Date:** Sep 16, 2026 18:04
- **Files Modified:** `models/pos_config.py`, `report/pos_retail_receipt_report.xml`, `static/src/receipt/invoice_receipt.xml`, `static/src/receipt/receipt.xml`, `views/pos_config_views.xml`

#### Details:
- Adds toggle to hide total discount row on receipts. Clean template gating.
- Safe; no runtime or startup dependencies introduced.

---

### 4.3 Commit `26f4580` — Multi-Company Session Scoping and closeOtherTabs Guard
- **Date:** Sep 16, 2026 19:03
- **Files Modified:** `models/pos_session.py`, `security/pos_retail_branch_rules.xml`, `static/src/overrides/negative_stock_warning.js`

#### Details:
- **Root Problem Addressed:**
  Users opening POS for a branch while having another company cookie active in their browser suffered from record-rule filtering, causing `pos.session` or `pos.config` to be omitted from the `load_data` response, resulting in `this.session is undefined` crash.
- **Backend Modifications (`models/pos_session.py`):**
  ```python
  def load_data(self, models_to_load):
      if self.company_id:
          self = self.with_company(self.company_id)
      response = super(PosSession, self).load_data(models_to_load)

      if self and 'pos.session' in response and self.id not in [r.get('id') for r in response['pos.session']]:
          session_data = self.sudo()._load_pos_data_read(self, self.config_id)
          response['pos.session'].extend(session_data)
      if self.config_id and 'pos.config' in response and self.config_id.id not in [r.get('id') for r in response['pos.config']]:
          config_data = self.config_id.sudo()._load_pos_data_read(self.config_id, self.config_id)
          response['pos.config'].extend(config_data)
      return response
  ```
- **Security Rule (`security/pos_retail_branch_rules.xml`):**
  Changed `pos_session_branch_rule` from `[('company_id', '=', company_id)]` to `['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]`.
- **Frontend Guard (`negative_stock_warning.js`):**
  Guarded `PosStore.prototype.closeOtherTabs` to return early if `!this.session`.

---

### 4.4 Commit `9b52041` — Prevent Hardware Proxy Hang and Add Loader Dismissal Watchdog
- **Date:** Sep 16, 2026 19:38
- **Files Modified:** `static/src/overrides/login_screen_label.js`, `static/src/overrides/negative_stock_warning.js`

#### Details:
- **Root Problem Addressed:**
  POS register was configured with an IoT / Hardware Proxy IP (`192.168.0.111`). Core Odoo's `hardware_proxy_service.autoConnect()` returns `new Promise(() => {})` when an IP is unreachable, causing `await this.connectToProxy()` in `PosStore.setup()` to hang **permanently** with 0 console errors.
- **Fix in `negative_stock_warning.js`:**
  ```javascript
  patch(PosStore.prototype, {
      async connectToProxy() {
          const proxyIp = this.config?.proxy_ip || "";
          const storedUrl = typeof localStorage !== "undefined" ? localStorage.hw_proxy_url : "";
          if (!proxyIp && !storedUrl) return;
          try {
              await Promise.race([
                  super.connectToProxy(...arguments),
                  new Promise((resolve) => setTimeout(resolve, 2000)),
              ]);
          } catch (_) {}
      },
  });
  ```
- Added 1.8s watchdog in `Chrome.setup()` and 4.5s global watchdog to hide and remove `.pos-loader`.
- Guarded `LoginScreen` property getters with optional chaining.

---

### 4.5 Commit `d8789c3` — Comprehensive Diagnostic Logs
- **Date:** Sep 17, 2026 00:28
- **Files Modified:** `static/src/overrides/login_screen_label.js`, `static/src/overrides/negative_stock_warning.js`

#### Details:
- Added global `window.addEventListener("unhandledrejection")` and `window.addEventListener("error")` to surface silent promise rejections.
- Added colored console traces (`[POS-DIAG]`) through the initialization pipeline:
  - `PosStore.setup() STARTING`
  - `PosStore.connectToProxy() called`
  - `PosStore.setup() FINISHED`
  - `Chrome root component setup() RUNNING`
  - `LoginScreen setup() complete`

---

### 4.6 Commit `4987fa2` — Firefox CPU Freeze and Static Getter Memoization
- **Date:** Sep 17, 2026 01:29
- **Files Modified:** `cashier_welcome_popup.scss`, `login_screen_details.scss`, `login_screen_label.js`, `navbar_menu.xml`, `negative_stock_warning.js`

#### Details:
- **Root Problem Addressed:**
  Firefox users received: *"This page is slowing down Firefox. To speed up your browser, stop this page."*
- **Root Cause:**
  1. CSS `backdrop-filter: blur(8px)` on multiple overlapping elements (`.pos-retail-login-card`, `.pos-retail-login-details`) forced continuous software compositor repainting.
  2. `LoginScreen` uses `useTime()` which re-renders the clock every 500ms. Getters `posRetailBranchName` and `posRetailCashierNames` were scanning and sorting the entire model store every 500ms!
- **Fix:**
  - Removed `backdrop-filter: blur`; applied solid rgba backgrounds.
  - Implemented `_posRetailInitDetails()` inside `LoginScreen.setup()` to cache branch, register, and cashier names once upon component mount.
  - Guarded `navbar_menu.xml` with `(this.pos.cashier and this.pos.cashier._can_admin_panel)`.

---

### 4.7 Commit `5d289ba` — Prevent Loader Click Blockage and Seamless Cashier Login
- **Date:** Sep 17, 2026 02:07
- **Files Modified:** `login_screen_details.scss`, `login_screen_details.xml`, `login_screen_label.js`, `negative_stock_warning.js`, `pos_theme.scss`

#### Details:
- **Root Problem Addressed:**
  User screenshot (`media_1789591474563.png`) confirmed POS loaded completely through `LoginScreen setup() complete`, but clicking **"Open Register" / "Unlock Register"** did nothing.
- **Root Causes:**
  1. **Invisible Click Shield:** In core Odoo 19, `.pos-loader` sits at `z-index: 100001` and takes up 100% viewport. When faded out, it has `opacity: 0`. In CSS, an element with `opacity: 0` **still intercepts all pointer clicks** unless `pointer-events: none` is set!
  2. **Core pos_hr Behaviour:** In standard Odoo `pos_hr`, `openRegister()` simply toggles `this.pos.login = true`, replacing the button with a blank text input for PIN/barcode scan. It does not open the register or display cashiers.
- **Fix Implemented:**
  1. Set `.pos-loader { pointer-events: none !important; }` in `pos_theme.scss` and removed element immediately upon Chrome mount.
  2. Overrode `openRegister()` in `login_screen_label.js` to call `this.pos.resetCashier()` and immediately prompt `await this.selectCashier(false, true, true)` (opening the Cashier Selection dialog).
  3. Made staff chips on login card clickable buttons (`Administrator`, `FAISAL`, `RASHID`):
     - If cashier has no PIN: logs them in directly with `this.selectOneCashier(emp)` straight into the sales screen.
     - If cashier has PIN: opens `NumberPopup` for masked PIN entry.

---

## 5. Why Is The Issue Still Not Fixed? Critical Failure Points and Hypotheses

If the till is still unresponsive or stuck on loading after `5d289ba`, here are the root hypotheses:

### Hypothesis 1: Production Server Is Not Running Commit `5d289ba`
- If the server has not pulled `5d289ba` or if the module upgrade command did not recompile the asset bundle, the browser is still executing the old code where `.pos-loader` intercepts mouse clicks.
- **Check on server:**
  ```bash
  cd /opt/odoo/custom_addons/pos_retail && git log -n 1 --oneline
  ```
  Must output: `5d289ba ...`

### Hypothesis 2: Missing Order Instance Crash on Navigation (`orderUuid` undefined)
- Look at `pos_hr/static/src/app/utils/select_cashier_mixin.js` lines 128-139:
  ```javascript
  const currentScreen = pos.router.state.current;
  if (currentScreen === "LoginScreen" && login && employee) {
      const selectedScreen = pos.defaultPage;
      const props = {
          ...selectedScreen.params,
          orderUuid: pos.selectedOrderUuid,
      };
      if (selectedScreen.page === "FloorScreen") {
          delete props.orderUuid;
      }
      pos.navigate(selectedScreen.page, props);
  }
  ```
- When POS boots up, **no orders exist yet**, so `pos.selectedOrderUuid` is `undefined`!
- Meanwhile, `ProductScreen` specifies:
  ```javascript
  static props = { orderUuid: { type: String } };
  ```
- When `pos.navigate("ProductScreen", { orderUuid: undefined })` is called, OWL throws a Prop Validation Error or `ProductScreen` crashes trying to access properties of an undefined order!
- In contrast, `point_of_sale.LoginScreen.prototype.cashierLogIn()` safely handles this:
  ```javascript
  cashierLogIn() {
      const selectedScreen = ...;
      const order = this.pos.getOrder();
      if (!order && selectedScreen.page === "ProductScreen") {
          this.pos.addNewOrder(); // <--- CREATES AN ORDER IF NONE EXISTS
      }
      const params = selectedScreen.page === "ProductScreen" ? { orderUuid: this.pos.getOrder().uuid } : {};
      this.pos.navigate(selectedScreen.page, params);
  }
  ```
- **Resolution:** In `login_screen_label.js`, before or inside `openRegister()` / `selectCashier()`, ensure `if (!this.pos.getOrder()) { this.pos.addNewOrder(); }` is called!

### Hypothesis 3: `CashierSelectionPopup` Employee List Filtered Out
- In `select_cashier_mixin.js`:
  ```javascript
  const allEmployees = pos.models["hr.employee"].filter(
      (employee) => employee.id !== pos.getCashier()?.id
  );
  ```
- If the register had a cashier previously assigned in memory/storage matching the only employee, `allEmployees` is empty!
- Then `selectCashier()` displays: *"There is no cashier available."* and stops.

---

## 6. Actionable Verification and Fix Plan

### Step 1: Run Diagnostic Shell on Production Server
Run this on `root@vmi3494070` to inspect backend data loading:
```bash
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin shell -c /etc/odoo/odoo.conf -d ostore_live --no-http << 'EOF'
config = env['pos.config'].browse(2)
session = env['pos.session'].search([('config_id', '=', 2)], order='id desc', limit=1)
print("=== CONFIG & SESSION ===")
print("Config:", config.name, "| Company:", config.company_id.name)
print("Session:", session.name, "| State:", session.state)

print("=== THERMAL PRESET DOMAIN ===")
domain = env['pos.retail.thermal.label.preset']._load_pos_data_domain({}, config)
presets = env['pos.retail.thermal.label.preset'].search(domain)
print("Preset count:", len(presets))

print("=== LOAD_DATA TEST ===")
res = session.load_data(['pos.session', 'pos.config', 'hr.employee', 'pos.retail.thermal.label.preset'])
print("Keys loaded:", list(res.keys()))
print("Session records:", len(res.get('pos.session', [])))
print("Employees loaded:", [e.get('name') for e in res.get('hr.employee', [])])
EOF
```

### Step 2: Ensure Order Pre-Creation Before Cashier Login
In `login_screen_label.js`, guarantee that an order is created if none exists before unlocking register:
```javascript
if (!this.pos.getOrder()) {
    this.pos.addNewOrder();
}
```

### Step 3: Hard-Refresh Browser and Check Console Logs
1. Open `https://169-58-143-45.sslip.io/pos/ui/2/login` in Chrome Incognito.
2. Open DevTools (**F12** -> **Console** tab).
3. Look for `[POS-DIAG] LoginScreen setup() complete`.
4. Click on staff badge (e.g. **Administrator**).
5. If an error occurs, inspect the exact line and stack trace logged in red.
