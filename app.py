import streamlit as st
import pandas as pd
import time
import math
from datetime import datetime
from backend import init_connection, add_item, update_stock, get_inventory_df, get_transactions_df, get_top_selling_items, delete_item, update_item_details, get_setting, set_setting, process_batch_transaction, update_live_cart, get_live_cart, clear_live_cart, get_eastern_time

# Page Config
st.set_page_config(page_title="Inventory Manager (Supabase)", layout="wide", page_icon="⚡")

# Initialize DB connection (cached)
try:
    init_connection()
except Exception as e:
    st.error(f"Failed to connect to database: {e}")

# Initialize Session State for Cart
if "cart" not in st.session_state:
    st.session_state["cart"] = []


# --- Helper: Price Calculation ---
def get_effective_price(price, sale_percent):
    """Calculate the effective price after sale discount."""
    if sale_percent and sale_percent > 0:
        return price * (1 - sale_percent / 100)
    return price

def get_bogo_paid_qty(qty, bogo):
    """Calculate how many units to charge for (BOGO: buy 2 pay 1)."""
    if bogo and qty >= 2:
        return math.ceil(qty / 2)
    return qty

def calculate_cart_totals(cart_items, checkout_discount_pct=0):
    """Calculate all cart totals with promotions."""
    subtotal = 0
    for item in cart_items:
        price = item['price']
        sale_pct = item.get('sale_percent', 0)
        effective_price = get_effective_price(price, sale_pct)
        bogo = item.get('bogo', False)
        paid_qty = get_bogo_paid_qty(item['qty'], bogo)
        item_total = effective_price * paid_qty
        subtotal += item_total
    
    discount_amount = subtotal * (checkout_discount_pct / 100)
    final_total = subtotal - discount_amount
    return subtotal, discount_amount, final_total



# --- POS Helper to Sync ---
def sync_cart():
    if "cart" in st.session_state:
        # Defaults to 0 if not set
        disc_val = st.session_state.get("checkout_discount", 0) 
        sub, disc_amt, final = calculate_cart_totals(st.session_state["cart"], disc_val)
        cart_data = {
            "items": st.session_state["cart"],
            "subtotal": sub,
            "discount": disc_amt,
            "total": final
        }
        update_live_cart(cart_data)

# --- UI Helpers ---
def style_dataframe(df):
    """Applies alternating row colors (White / Light Blue) to a dataframe."""
    def highlight_rows(row):
        return ['background-color: #e6f3ff' if row.name % 2 != 0 else 'background-color: #ffffff' for _ in row]
    
    df = df.reset_index(drop=True)
    return df.style.apply(highlight_rows, axis=1)

def generate_receipt_html(cart_items, subtotal, discount_pct, discount_amount, final_total, receipt_id, auto_print=False):
    """Generates a simple HTML receipt with promotion info."""
    date_str = get_eastern_time().strftime("%Y-%m-%d %H:%M:%S")
    
    rows_html = ""
    for item in cart_items:
        price = item['price']
        sale_pct = item.get('sale_percent', 0)
        effective_price = get_effective_price(price, sale_pct)
        bogo = item.get('bogo', False)
        qty = item['qty']
        paid_qty = get_bogo_paid_qty(qty, bogo)
        item_total = effective_price * paid_qty
        
        # Build promo tags
        promo_tags = ""
        if sale_pct and sale_pct > 0:
            promo_tags += f' <small style="color:red;">(-{sale_pct}%)</small>'
        if bogo and qty >= 2:
            free_qty = qty - paid_qty
            promo_tags += f' <small style="color:green;">({free_qty} FREE)</small>'
        
        # Price display
        if sale_pct and sale_pct > 0:
            price_display = f'<s>${price:.2f}</s> ${effective_price:.2f}'
        else:
            price_display = f'${effective_price:.2f}'
        
        rows_html += f"""
        <tr>
            <td>{item['name']}{promo_tags}</td>
            <td>{qty}</td>
            <td>{price_display}</td>
            <td>${item_total:.2f}</td>
        </tr>
        """
    
    # Discount line
    discount_html = ""
    if discount_pct > 0:
        discount_html = f"""
        <p class="right">Subtotal: ${subtotal:.2f}</p>
        <p class="right" style="color:red;">Discount ({discount_pct}%): -${discount_amount:.2f}</p>
        """
        
    auto_print_script = "<script>window.onload = function() { window.print(); }</script>" if auto_print else ""

    def get_receipt_body(copy_type):
        return f"""
        <div class="receipt-container">
            <div class="header">
                <h3>Inventory Store</h3>
                <p>Receipt ID: {receipt_id[:8]}</p>
                <p>{date_str}</p>
                <p><strong>*** {copy_type} ***</strong></p>
            </div>
            
            <div class="divider"></div>
            
            <table>
                <tr><th>Item</th><th>Qty</th><th>Price</th><th>Total</th></tr>
                {rows_html}
            </table>
            
            <div class="divider"></div>
            
            {discount_html}
            <p class="right"><strong>TOTAL: ${final_total:.2f}</strong></p>
            
            <div class="footer">
                <p>Thank you for your business!</p>
            </div>
        </div>
        """

    html = f"""
    <html>
    <head>
        <title>Receipt</title>
        <style>
            body {{ font-family: 'Courier New', monospace; width: 300px; margin: 0 auto; }}
            .header, .footer {{ text-align: center; }}
            table {{ width: 100%; border-collapse: collapse; }}
            
            /* Spacing and Alignment */
            th, td {{ padding: 5px 2px; }}
            
            th:nth-child(1), td:nth-child(1) {{ text-align: left; width: 40%; }}
            th:nth-child(2), td:nth-child(2) {{ text-align: center; width: 15%; }}
            th:nth-child(3), td:nth-child(3) {{ text-align: right; width: 20%; }}
            th:nth-child(4), td:nth-child(4) {{ text-align: right; width: 25%; }}
            
            .right {{ text-align: right; }}
            .divider {{ border-top: 1px dashed black; margin: 10px 0; }}
            .cut-line {{ border-top: 2px dotted black; margin: 20px 0; text-align: center; }}
            .page-break {{ page-break-after: always; }}

            /* Hide browser headers/footers (URL, Page #) */
            @media print {{
                @page {{ margin: 0; }}
                body {{ margin: 0.5cm auto; }}
            }}
        </style>
        {auto_print_script}
    </head>
    <body>
        {get_receipt_body("CUSTOMER COPY")}
        
        <!-- Page Break for Receipt Printer (Triggers Cut) -->
        <div class="page-break"></div>
        
        {get_receipt_body("MERCHANT COPY")}
    </body>
    </html>
    """
    return html

# --- Authentication ---

def check_global_password():
    """Checks for the 'Global Wall' password."""
    correct_password = get_setting("global_password", "0000")
    
    def password_entered():
        entered = st.session_state.get("global_password_input", "")
        if entered == correct_password:
            st.session_state["global_access_granted"] = True
            st.session_state["global_password_input"] = ""
        else:
            st.session_state["global_access_granted"] = False

    if "global_access_granted" not in st.session_state:
        st.session_state["global_access_granted"] = False

    if not st.session_state["global_access_granted"]:
        st.text_input("🔒 Enter App Password to Access", type="password", on_change=password_entered, key="global_password_input")
        st.error("Please log in to access the system.")
        return False
    
    return True

def check_admin_password():
    """Checks for the 'Admin' password for sensitive actions."""
    correct_password = get_setting("admin_password", "0000")

    def password_entered():
        entered = st.session_state.get("admin_password_input", "")
        if entered == correct_password:
            st.session_state["admin_access_granted"] = True
            st.session_state["admin_password_input"] = ""
        else:
            st.session_state["admin_access_granted"] = False

    if "admin_access_granted" not in st.session_state:
        st.session_state["admin_access_granted"] = False

    if not st.session_state["admin_access_granted"]:
        st.text_input("🔑 Enter Admin Password for Full Access", type="password", on_change=password_entered, key="admin_password_input")
        return False
    else:
        if st.sidebar.button("Admin Logout"):
             st.session_state["admin_access_granted"] = False
             st.rerun()
        return True

st.title("⚡ Inventory Manager (Supabase Edition)")

# 1. Enforce Global Login
if not check_global_password():
    st.stop()

# Logout for Global
if st.sidebar.button("Exit App (Logout)"):
    st.session_state["global_access_granted"] = False
    st.session_state["admin_access_granted"] = False
    st.rerun()

# Sidebar Navigation
menu = ["Dashboard", "Transactions", "History", "Inventory (Admin)", "Settings (Admin)", "📺 Customer View"]
page = st.sidebar.selectbox("Navigate", menu)

if page == "📺 Customer View":
    st.markdown("""
        <style>
            [data-testid="stSidebar"], [data-testid="stHeader"], footer {display: none;}
            
            /* Large Fonts */
            .cust-item-name { font-size: 2.0rem !important; font-weight: bold; color: #333; }
            .cust-item-detail { font-size: 2.0rem !important; color: #555; }
            .cust-promo { font-size: 1.5rem !important; color: #d9534f; font-weight: bold; }
            
            /* Totals Box */
            .total-box { 
                background-color: #d1ecf1; 
                padding: 30px; 
                border-radius: 15px; 
                text-align: right; 
                margin-top: 30px;
                border: 2px solid #bee5eb;
            }
            .total-label { font-size: 1.8rem !important; color: #0c5460; }
            .total-amt { font-size: 3.2rem !important; font-weight: 800; color: #000; }
        </style>
    """, unsafe_allow_html=True)
    
    st.title("🛒 Customer Display (v2.1)")
    
    # Poll for live cart data
    cart_data = get_live_cart()
    
    # Adaptive Polling
    if "last_cart_data" not in st.session_state:
        st.session_state["last_cart_data"] = {}
    
    import json
    current_hash = json.dumps(cart_data, sort_keys=True) if cart_data else ""
    last_hash = json.dumps(st.session_state["last_cart_data"], sort_keys=True) if st.session_state["last_cart_data"] else ""
    
    has_changed = current_hash != last_hash
    if has_changed:
        st.session_state["last_cart_data"] = cart_data
        poll_interval = 1 # Active: Fast updates
    else:
        poll_interval = 2 # Idle: Fast check for resets
        
    # Main visual container for atomic updates
    main_placeholder = st.empty()
    
    with main_placeholder.container():
        if not cart_data or not cart_data.get("items"):
            st.markdown("<div style='text-align: center; margin-top: 100px;'>", unsafe_allow_html=True)
            st.info("👋 Welcome! Items will appear here.", icon="🛒")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            # Show Items
            items = cart_data.get("items", [])
            
            # Explicit Containers for DOM separation
            items_container = st.container()
            totals_container = st.container()
            
            with items_container:
                # Table Data Construction
                table_rows = []
                for item in items:
                    name = item['name']
                    qty = item['qty']
                    price = item['price']
                    sale_pct = item.get('sale_percent', 0)
                    bogo = item.get('bogo', False)
                    eff_price = price * (1 - sale_pct/100)
                    
                    promos = []
                    if sale_pct > 0:
                        promos.append(f"🔥 -{sale_pct}%")
                    if bogo:
                        paid = get_bogo_paid_qty(qty, bogo) 
                        free_qty = qty - paid
                        promos.append(f"🎁 {free_qty} FREE")
                    
                    item_total = eff_price * get_bogo_paid_qty(qty, bogo)
                    
                    table_rows.append({
                        "Item": name,
                        "Price": f"${eff_price:.2f}" + (f" (Reg: ${price:.2f})" if sale_pct > 0 else ""),
                        "Qty": qty,
                        "Promos": " ".join(promos),
                        "Total": f"${item_total:.2f}"
                    })
                
                # Display Table
                if table_rows:
                    df_display = pd.DataFrame(table_rows)
                    # Use st.dataframe for clean table view
                    st.dataframe(
                        style_dataframe(df_display),
                        width='stretch',
                        hide_index=True,
                        column_config={
                            "Item": st.column_config.TextColumn("Item", width="large"),
                            "Price": st.column_config.TextColumn("Price"),
                            "Qty": st.column_config.NumberColumn("Qty", format="%d"),
                            "Promos": st.column_config.TextColumn("Promos", width="medium"),
                            "Total": st.column_config.TextColumn("Total"),
                        }
                    )

            with totals_container:
                # Totals Logic
                subtotal = cart_data.get("subtotal", 0)
                discount = cart_data.get("discount", 0)
                total = cart_data.get("total", 0)
                
                col_t1, col_t2 = st.columns([1, 1])
                with col_t2:
                    st.markdown(f"<div class='total-box'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='total-label'>Subtotal: ${subtotal:.2f}</div>", unsafe_allow_html=True)
                    if discount > 0:
                         st.markdown(f"<div class='total-label' style='color: #d9534f;'>Discount: -${discount:.2f}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='total-amt'>${total:.2f}</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

    time.sleep(poll_interval)
    st.rerun()
    st.stop()

# --- POS Helper to Sync ---


# --- Page Routing ---
elif page == "Dashboard":
    st.header("Dashboard")
    df = get_inventory_df()
    
    if not df.empty:
        # Metrics
        col1, col2 = st.columns(2)
        col1.metric("Total Items", len(df))
        col2.metric("Total Stock", df['quantity'].sum())
        
        # Low Stock Alert
        low_stock = df[df['quantity'] <= df['min_threshold']]
        if not low_stock.empty:
            st.warning(f"⚠️ {len(low_stock)} items are low on stock!")
            cols = ['name', 'quantity', 'min_threshold']
            if 'supplier' in low_stock.columns:
                cols.append('supplier')
            st.dataframe(style_dataframe(low_stock[cols]), hide_index=True)
        else:
            st.success("All stock levels are healthy.")
            
        pass


    else:
        st.info("No items in inventory.")

elif page == "Inventory (Admin)":
    st.header("Inventory Management (Admin)")
    
    if not check_admin_password():
        st.stop()
        
    # Show Value Here
    df = get_inventory_df()
    if not df.empty:
        total_value = (df['quantity'] * df['price']).sum()
        st.metric("Total Inventory Value", f"${total_value:,.2f}")
    
    # Add New Item Form
    with st.expander("➕ Add New Item"):
        with st.form("add_item_form"):
            col1, col2 = st.columns(2)
            name = col1.text_input("Item Name")
            category = col2.text_input("Category")
            
            col_maker, col_supplier, col_color, col_barcode = st.columns(4)
            maker = col_maker.text_input("Maker/Brand")
            supplier = col_supplier.text_input("Supplier")
            color = col_color.text_input("Color")
            barcode = col_barcode.text_input("Barcode")
            
            col3, col4, col5 = st.columns(3)
            quantity = col3.number_input("Initial Quantity", min_value=0, value=0)
            price = col4.number_input("Price", min_value=0.0, value=0.0, step=0.01)
            min_threshold = col5.number_input("Low Stock Threshold", min_value=1, value=5)
            
            # Promotions
            st.markdown("**🏷️ Promotions**")
            col_sale, col_bogo = st.columns(2)
            sale_percent = col_sale.number_input("Sale % (0 = no sale)", min_value=0, max_value=90, value=0, help="Set a percentage discount for this product")
            bogo = col_bogo.checkbox("🎁 Buy One Get One Free (BOGO)", value=False)
            
            submitted = st.form_submit_button("Add Item")
            if submitted:
                if name:
                    success, msg = add_item(name, category, maker, supplier, color, barcode, quantity, price, min_threshold, sale_percent, bogo)
                    if success:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Item Name is required.")
    
    # Update Item Settings
    with st.expander("⚙️ Update Item Settings"):
        df = get_inventory_df()
        if not df.empty:
            # Create list of names
            item_list = df['name'].tolist()
            edit_item_name = st.selectbox("Select Item to Edit", options=item_list)
            
            if edit_item_name:
                item_row = df[df['name'] == edit_item_name].iloc[0]
                edit_id = int(item_row['id'])
                
                with st.form("edit_item_form"):
                    col1, col2 = st.columns(2)
                    new_name = col1.text_input("Item Name", value=item_row['name'])
                    new_category = col2.text_input("Category", value=item_row['category'] if item_row['category'] else "")
                    
                    col_maker, col_supplier, col_color, col_barcode = st.columns(4)
                    curr_maker = item_row['maker'] if 'maker' in item_row and item_row['maker'] is not None else ""
                    curr_supplier = item_row['supplier'] if 'supplier' in item_row and item_row['supplier'] is not None else ""
                    curr_color = item_row['color'] if 'color' in item_row and item_row['color'] is not None else ""
                    curr_barcode = item_row['barcode'] if 'barcode' in item_row and item_row['barcode'] is not None else ""
                    
                    new_maker = col_maker.text_input("Maker/Brand", value=curr_maker)
                    new_supplier = col_supplier.text_input("Supplier", value=curr_supplier)
                    new_color = col_color.text_input("Color", value=curr_color)
                    new_barcode = col_barcode.text_input("Barcode", value=curr_barcode)
                    
                    col3, col4 = st.columns(2)
                    new_price = col3.number_input("Price", min_value=0.0, value=float(item_row['price']), step=0.01)
                    new_threshold = col4.number_input("Low Stock Threshold", min_value=1, value=int(item_row['min_threshold']))
                    
                    # Promotions
                    st.markdown("**🏷️ Promotions**")
                    col_sale, col_bogo = st.columns(2)
                    curr_sale = int(item_row.get('sale_percent', 0)) if item_row.get('sale_percent') is not None else 0
                    curr_bogo = bool(item_row.get('bogo', False))
                    new_sale_percent = col_sale.number_input("Sale % (0 = no sale)", min_value=0, max_value=90, value=curr_sale, help="Set a percentage discount for this product")
                    new_bogo = col_bogo.checkbox("🎁 BOGO (Buy One Get One Free)", value=curr_bogo)
                    
                    col_update, col_delete = st.columns([1, 1])
                    with col_update:
                        if st.form_submit_button("Update Item Details"):
                            success, msg = update_item_details(edit_id, new_name, new_category, new_maker, new_supplier, new_color, new_barcode, new_price, new_threshold, new_sale_percent, new_bogo)
                            if success:
                                st.success(f"Updated {new_name}: {msg}")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(msg)
                    
                    with col_delete:
                        confirm_delete = st.checkbox("⚠️ Confirm I want to delete this item", key="confirm_delete_checkbox", help="You must check this box to enable deletion.")
                        if st.form_submit_button("🗑️ Delete Item", type="primary"):
                            if confirm_delete:
                                success, msg = delete_item(edit_id)
                                if success:
                                    st.success(msg)
                                    st.session_state["confirm_delete_checkbox"] = False
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(msg)
                            else:
                                st.error("Please check the 'Confirm' box first if you really want to delete this item.")
        else:
            st.info("No items to edit.")

    # View Inventory
    st.subheader("Current Stock")
    if not df.empty:
        # Add promo badges to display
        display_df = df.copy()
        def promo_badge(row):
            badges = []
            if row.get('sale_percent', 0) and row['sale_percent'] > 0:
                badges.append(f"🔥 {row['sale_percent']}% OFF")
            if row.get('bogo', False):
                badges.append("🎁 BOGO")
            return " | ".join(badges) if badges else ""
        
        display_df['Promos'] = display_df.apply(promo_badge, axis=1)
        show_cols = ['name', 'category', 'quantity', 'price', 'Promos', 'barcode']
        show_cols = [c for c in show_cols if c in display_df.columns]
        st.dataframe(style_dataframe(display_df[show_cols]), use_container_width=True, hide_index=True)
    else:
        st.info("Inventory is empty.")

elif page == "Transactions":
    st.header("🛒 Point of Sale (POS)")

    # 1. Search & Add to Cart
    col_mode_1, col_mode_2 = st.columns([3, 1])
    with col_mode_1:
        st.subheader("Add Item to Cart")
    with col_mode_2:
        mode = st.radio("Mode", ["Sale", "Restock"], horizontal=True, label_visibility="collapsed")
        
    df = get_inventory_df()
    if df.empty:
        st.warning("No items in inventory.")
    else:
        # Create a display label for each item with promo badges
        def format_item_label(row):
            parts = [row['name']]
            if 'color' in row and row['color']: parts.append(f"({row['color']})")
            if 'barcode' in row and row['barcode']: parts.append(str(row['barcode']))
            # Promo badges
            sale_pct = row.get('sale_percent', 0)
            if sale_pct and sale_pct > 0:
                eff_price = get_effective_price(float(row['price']), sale_pct)
                parts.append(f"🔥{sale_pct}%OFF ${row['price']:.2f}→${eff_price:.2f}")
            if row.get('bogo', False):
                parts.append("🎁BOGO")
            parts.append(f"Stock: {row['quantity']}")
            return " | ".join(parts)

        item_map = {}
        for index, row in df.iterrows():
            label = format_item_label(row)
            item_map[label] = row

        # --- Helper: Consolidated Cart Add ---
        def add_to_cart_consolidated(new_item):
            """Adds item to cart, incrementing quantity if it already exists."""
            # Check if item with same ID and Note already exists
            found = False
            for existing in st.session_state["cart"]:
                if existing['id'] == new_item['id'] and existing['note'] == new_item['note']:
                    existing['qty'] += new_item['qty']
                    found = True
                    break
            
            if not found:
                st.session_state["cart"].append(new_item)
            
        # --- Quick Scan Section ---
        def process_scan():
            code = st.session_state.get("barcode_input", "").strip()
            if code:
                matches = df[df['barcode'].astype(str) == code]
                
                if not matches.empty:
                    row = matches.iloc[0]
                    qty_to_add = 1
                    
                    if mode == "Sale" and row['quantity'] < qty_to_add:
                        st.session_state["scan_msg"] = (False, f"Not enough stock for {row['name']}! (Available: {row['quantity']})")
                    else:
                        item_data = {
                            "id": int(row['id']),
                            "name": row['name'],
                            "price": float(row['price']),
                            "qty": qty_to_add,
                            "note": "Scanned",
                            "max_qty": int(row['quantity']),
                            "sale_percent": int(row.get('sale_percent', 0)),
                            "bogo": bool(row.get('bogo', False))
                        }
                        add_to_cart_consolidated(item_data)
                        sync_cart() # Sync to Customer Display
                        st.session_state["scan_msg"] = (True, f"Added: {row['name']}")
                else:
                    st.session_state["scan_msg"] = (False, f"Barcode not found: {code}")
            
            st.session_state["barcode_input"] = ""

        st.text_input("⚡ Quick Scan (Barcode)", key="barcode_input", on_change=process_scan, placeholder="Click here and scan item...", help="Scans add 1 unit automatically.")
        
        if "scan_msg" in st.session_state and st.session_state["scan_msg"]:
             s_success, s_msg = st.session_state["scan_msg"]
             if s_success:
                 st.success(s_msg, icon="✅")
             else:
                 st.error(s_msg, icon="❌")
        
        # Default State for Manual Inputs
        if "pos_search" not in st.session_state: st.session_state.pos_search = None
        if "pos_qty" not in st.session_state: st.session_state.pos_qty = 1
        if "pos_note" not in st.session_state: st.session_state.pos_note = ""

        # --- Manual Reset for Customer Display ---
        with st.sidebar:
            st.divider()
            if st.button("🔄 Force Reset Customer Display", type="secondary"):
                 sync_cart()
                 st.toast("🔄 Customer Display Reset!")
                 time.sleep(0.2)
                 st.rerun()
            
            # Auto-Sync Heartbeat (5s)
            if hasattr(st, "fragment"):
                @st.fragment(run_every=5)
                def auto_sync_heartbeat():
                    sync_cart()
                auto_sync_heartbeat()
            else:
                # Fallback: Lazy sync on interaction
                if "last_auto_sync" not in st.session_state:
                    st.session_state.last_auto_sync = 0
                
                if time.time() - st.session_state.last_auto_sync > 5:
                    sync_cart()
                    st.session_state.last_auto_sync = time.time()


        # --- Manual Search Section ---
        col_search, col_qty = st.columns([3, 1])
        
        with col_search:
            selected_label = st.selectbox("Search Item (Manual)", options=list(item_map.keys()), placeholder="Type name or select...", key="pos_search", index=None)
            
        with col_qty:
            qty = st.number_input("Qty", min_value=1, key="pos_qty")
            
        col_add, col_note = st.columns([1, 3])
        with col_note:
            note = st.text_input("Note (Optional)", placeholder="Customer Name / ID", key="pos_note")
            
        with col_add:
            # Callback for manual Add
            def add_manual_item(item_map, mode):
                 key = st.session_state.get("pos_search")
                 qty = st.session_state.get("pos_qty", 1)
                 note = st.session_state.get("pos_note", "")
                 
                 if not key:
                     st.session_state["manual_msg"] = (False, "Please select an item first.")
                     return

                 row = item_map.get(key)
                 if row is None:
                     return
                     
                 # Check Stock Logic
                 if mode == "Sale" and row['quantity'] < qty:
                      st.session_state["manual_msg"] = (False, f"Not enough stock! (Available: {row['quantity']})")
                      return
                 
                 # Success - include promo info
                 item_data = {
                     "id": int(row['id']),
                     "name": row['name'],
                     "price": float(row['price']),
                     "qty": qty,
                     "note": note,
                     "max_qty": int(row['quantity']),
                     "sale_percent": int(row.get('sale_percent', 0)),
                     "bogo": bool(row.get('bogo', False))
                 }
                 add_to_cart_consolidated(item_data)
                 sync_cart() # Sync to Customer Display
                 st.session_state["manual_msg"] = (True, f"Added {row['name']}")
                 
                 # Clear Inputs
                 st.session_state["pos_search"] = None
                 st.session_state["pos_qty"] = 1
                 st.session_state["pos_note"] = ""

            st.button("Add to Cart", type="primary", on_click=add_manual_item, args=(item_map, mode))
            
            # Display Message
            if "manual_msg" in st.session_state and st.session_state["manual_msg"]:
                 m_success, m_msg = st.session_state["manual_msg"]
                 if m_success:
                     st.success(m_msg)
                     st.session_state["manual_msg"] = None
                 else:
                     st.error(m_msg)
                     st.session_state["manual_msg"] = None

    st.divider()

    # 2. View Cart & Checkout
    st.subheader("Shopping Cart")
    
    if st.session_state["cart"]:
        cart_df = pd.DataFrame(st.session_state["cart"])
        
        # Calculate display columns with promos
        display_rows = []
        for item in st.session_state["cart"]:
            price = item['price']
            sale_pct = item.get('sale_percent', 0)
            eff_price = get_effective_price(price, sale_pct)
            bogo = item.get('bogo', False)
            qty = item['qty']
            paid_qty = get_bogo_paid_qty(qty, bogo)
            item_total = eff_price * paid_qty
            
            # Build promo text
            promo = ""
            if sale_pct and sale_pct > 0:
                promo += f"🔥-{sale_pct}% "
            if bogo and qty >= 2:
                promo += f"🎁{qty - paid_qty} FREE "
            
            display_rows.append({
                "Name": item['name'],
                "Qty": qty,
                "Price": f"${eff_price:.2f}" + (f" (was ${price:.2f})" if sale_pct > 0 else ""),
                "Promos": promo.strip(),
                "Total": f"${item_total:.2f}",
                "Note": item.get('note', '')
            })
        
        display_cart_df = pd.DataFrame(display_rows)
        st.dataframe(style_dataframe(display_cart_df), width='stretch', hide_index=True)
        
        # Checkout Discount (use reset flag to avoid StreamlitAPIException)
        if st.session_state.get("_reset_discount", False):
            st.session_state["checkout_discount"] = 0
            st.session_state["_reset_discount"] = False
        elif "checkout_discount" not in st.session_state:
            st.session_state["checkout_discount"] = 0
        
        col_discount, col_total = st.columns([1, 2])
        with col_discount:
            checkout_discount_pct = st.number_input("🏷️ Checkout Discount %", min_value=0, max_value=50, key="checkout_discount", help="Apply an additional discount to the entire purchase", on_change=sync_cart)
        
        # Calculate totals
        subtotal, discount_amount, final_total = calculate_cart_totals(st.session_state["cart"], checkout_discount_pct)
        
        with col_total:
            if checkout_discount_pct > 0:
                st.markdown(f"Subtotal: ${subtotal:,.2f}")
                st.markdown(f"🏷️ Discount ({checkout_discount_pct}%): **-${discount_amount:,.2f}**")
            st.markdown(f"### 💰 Total: ${final_total:,.2f}")
        
        # Remove Item Logic
        item_to_remove = st.selectbox("Remove Item:", options=cart_df['name'].tolist(), index=None, placeholder="Select item to remove...")
        if st.button("Remove Selected Item"):
            if item_to_remove:
                st.session_state["cart"] = [i for i in st.session_state["cart"] if i['name'] != item_to_remove]
                sync_cart() # Sync to Customer Display
                time.sleep(0.2) # Ensure sync completes
                st.rerun()
        
        st.divider()
        
        # Checkout Section
        col_chk_1, col_chk_2 = st.columns(2)
        
        with col_chk_1:
            # Receipt Toggle
            if "generate_receipt_check" not in st.session_state:
                st.session_state["generate_receipt_check"] = True
            generate_receipt = st.checkbox("📄 Generate Receipt", value=st.session_state["generate_receipt_check"], key="gen_receipt_widget", on_change=lambda: st.session_state.update(generate_receipt_check=st.session_state.gen_receipt_widget))
            
            if generate_receipt:
                if "auto_print_check" not in st.session_state:
                    st.session_state["auto_print_check"] = True
                auto_print = st.checkbox("🖨️ Auto-Print Receipt", value=st.session_state["auto_print_check"], key="auto_print_check_widget", on_change=lambda: st.session_state.update(auto_print_check=st.session_state.auto_print_check_widget))
            else:
                auto_print = False
            
        with col_chk_2:
            if mode == "Sale":
                col_cash, col_card = st.columns(2)
                
                with col_cash:
                    if st.button("💵 PAY CASH", type="primary", use_container_width=True):
                        success, receipt_id = process_batch_transaction(st.session_state["cart"], "SALE", "CASH")
                        
                        if success:
                            st.success("Cash Transaction Complete!")
                            
                            if generate_receipt:
                                receipt_html = generate_receipt_html(st.session_state["cart"], subtotal, checkout_discount_pct, discount_amount, final_total, receipt_id, auto_print=False)
                                st.session_state["last_receipt"] = receipt_html
                                
                                if auto_print:
                                    receipt_html_print = receipt_html.replace("</head>", "<script>window.onload = function() { window.print(); }</head>")
                                    st.session_state["actions_trigger_print"] = receipt_html_print
                                else:
                                     st.session_state["actions_trigger_print"] = None
                            else:
                                st.session_state["last_receipt"] = None
                                st.session_state["actions_trigger_print"] = None

                            st.session_state["cart"] = []
                            st.session_state["_reset_discount"] = True
                            sync_cart() # Sync empty cart to Customer Display
                            time.sleep(0.2) # WAIT for DB sync!
                            st.rerun()
                        else:
                            st.error(f"Transaction Failed: {receipt_id}")

                with col_card:
                    if st.button("💳 PAY CARD", type="secondary", use_container_width=True):
                        success, receipt_id = process_batch_transaction(st.session_state["cart"], "SALE", "CARD")
                        
                        if success:
                            st.success("Card Transaction Recorded!")
                            
                            if generate_receipt:
                                receipt_html = generate_receipt_html(st.session_state["cart"], subtotal, checkout_discount_pct, discount_amount, final_total, receipt_id, auto_print=False)
                                st.session_state["last_receipt"] = receipt_html
                                
                                if auto_print:
                                    receipt_html_print = receipt_html.replace("</head>", "<script>window.onload = function() { window.print(); }</head>")
                                    st.session_state["actions_trigger_print"] = receipt_html_print
                                else:
                                     st.session_state["actions_trigger_print"] = None
                            else:
                                st.session_state["last_receipt"] = None
                                st.session_state["actions_trigger_print"] = None
                            
                            st.session_state["cart"] = []
                            st.session_state["_reset_discount"] = True
                            sync_cart() # Sync empty cart to Customer Display
                            time.sleep(0.2) # WAIT for DB sync!
                            st.rerun()
                        else:
                            st.error(f"Transaction Failed: {receipt_id}")
            
            else: # Restock Mode
                if st.button("📦 CONFIRM RESTOCK", type="primary", use_container_width=True):
                    success, receipt_id = process_batch_transaction(st.session_state["cart"], "RESTOCK", "MANUAL")
                    
                    if success:
                        st.success("Restock Complete! Inventory Updated.")
                        st.session_state["cart"] = []
                        st.session_state["_reset_discount"] = True
                        sync_cart() # Clear Customer Display
                        time.sleep(0.2) # WAIT for DB sync!
                        st.rerun()
                    else:
                        st.error(f"Restock Failed: {receipt_id}")
                    
        if st.button("Empty Cart (Cancel)"):
             st.session_state["cart"] = []
             st.session_state["_reset_discount"] = True
             sync_cart() # Clear Customer Display
             time.sleep(0.2) # WAIT for DB sync!
             st.rerun()
             
    # Handle Auto-Print Trigger (Immediate)
    if "actions_trigger_print" in st.session_state and st.session_state["actions_trigger_print"]:
         st.components.v1.html(st.session_state["actions_trigger_print"], height=0, width=0, scrolling=False)
         st.session_state["actions_trigger_print"] = None

    # Show Last Receipt (Passive View)
    if "last_receipt" in st.session_state and st.session_state["last_receipt"]:
        st.divider()
        st.subheader("📄 Last Transaction Receipt")
        col_repr_1, col_repr_2 = st.columns([1, 4])
        
        with col_repr_1:
            if st.button("🖨️ Reprint Receipt"):
                print_html = st.session_state["last_receipt"].replace("</head>", "<script>window.onload = function() { window.print(); }</script></head>")
                st.components.v1.html(print_html, height=0, width=0, scrolling=False)

        with st.expander("View Receipt", expanded=True):
             st.components.v1.html(st.session_state["last_receipt"], height=600, scrolling=True)
            
    else:
        st.info("Cart is empty.")

elif page == "History":
    st.header("Transaction History")
    df = get_transactions_df(limit=200)
    if not df.empty:
        st.dataframe(style_dataframe(df), width='stretch', hide_index=True)
    else:
        st.info("No transactions recorded yet.")

elif page == "Settings (Admin)":
    st.header("System Settings")
    
    if not check_admin_password():
        st.stop()
    
    st.subheader("Security Settings")
    with st.expander("🔐 Change Passwords"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            new_global = st.text_input("New App Access Password", type="password")
            if st.button("Update App Password"):
                if new_global:
                    set_setting("global_password", new_global)
                    st.success("App Password updated!")
                else:
                    st.error("Password cannot be empty")
        
        with col_p2:
            new_admin = st.text_input("New Admin Password", type="password")
            if st.button("Update Admin Password"):
                if new_admin:
                    set_setting("admin_password", new_admin)
                    st.success("Admin Password updated!")
                else:
                    st.error("Password cannot be empty")

    st.divider()

    st.subheader("Data Management")
    st.info("Your data is stored securely in Supabase (PostgreSQL). Backups are managed automatically by the cloud provider. ☁️")
    
    st.divider()
    st.subheader("Export Data")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Download Inventory as CSV"):
            df = get_inventory_df()
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Click to Download Inventory CSV",
                data=csv,
                file_name='inventory_export.csv',
                mime='text/csv',
            )
    
    with col2:
            if st.button("Download Transactions as CSV"):
                df = get_transactions_df(limit=10000)
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="Click to Download Transactions CSV",
                    data=csv,
                    file_name='transactions_export.csv',
                    mime='text/csv',
                )