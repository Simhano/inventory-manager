import streamlit as st
import pandas as pd
import time
from datetime import datetime
from database import init_connection, add_item, update_stock, get_inventory_df, get_transactions_df, get_top_selling_items, delete_item, update_item_details, get_setting, set_setting, process_batch_transaction

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


# --- UI Helpers ---
def style_dataframe(df):
    """Applies alternating row colors (White / Light Blue) to a dataframe."""
    def highlight_rows(row):
        # Check if index is integer, if not try to use implicit counter
        # robust way: alternating colors regardless of index value
        return ['background-color: #e6f3ff' if row.name % 2 != 0 else 'background-color: #ffffff' for _ in row]
    
    # Ensure zero-based integer index for styling
    df = df.reset_index(drop=True)
    return df.style.apply(highlight_rows, axis=1)

def generate_receipt_html(cart_items, total_amount, receipt_id, auto_print=False):
    """Generates a simple HTML receipt."""
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    rows_html = ""
    for item in cart_items:
        rows_html += f"""
        <tr>
            <td>{item['name']}</td>
            <td>{item['qty']}</td>
            <td>${item['price']:.2f}</td>
            <td>${item['qty'] * item['price']:.2f}</td>
        </tr>
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
            
            <p class="right"><strong>TOTAL: ${total_amount:.2f}</strong></p>
            
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
            th, td {{ text-align: left; padding: 5px 0; }}
            .right {{ text-align: right; }}
            .divider {{ border-top: 1px dashed black; margin: 10px 0; }}
            .cut-line {{ border-top: 2px dotted black; margin: 20px 0; text-align: center; }}
            .page-break {{ page-break-after: always; }}
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
    # Retrieve dynamic password from DB (default 0000)
    correct_password = get_setting("global_password", "0000")
    
    def password_entered():
        # Use .get() to avoid KeyError if widget state is lost
        entered = st.session_state.get("global_password_input", "")
        if entered == correct_password:
            st.session_state["global_access_granted"] = True
            st.session_state["global_password_input"] = "" # Clear input instead of deleting
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
        # Logout button for admin
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
    st.session_state["admin_access_granted"] = False  # Log out admin too
    st.rerun()

# Sidebar Navigation
page = st.sidebar.selectbox("Navigation", ["Dashboard", "Transactions", "History", "Inventory (Admin)", "Settings (Admin)"])

if page == "Dashboard":
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
            
        # Recent Activity (Mini)
        st.subheader("Recent Activity")
        trans_df = get_transactions_df(limit=5)
        st.dataframe(style_dataframe(trans_df), hide_index=True)

        # Top Selling Items
        st.subheader("🏆 Top Selling Items")
        tab_week, tab_month = st.tabs(["This Week", "This Month"])
        
        with tab_week:
            top_week = get_top_selling_items("week", 10)
            if not top_week.empty:
                st.bar_chart(top_week, x="Item Name", y="Total Sold")
                st.dataframe(style_dataframe(top_week), hide_index=True)
            else:
                st.info("No sales this week.")
                
        with tab_month:
            top_month = get_top_selling_items("month", 10)
            if not top_month.empty:
                st.bar_chart(top_month, x="Item Name", y="Total Sold")
                st.dataframe(style_dataframe(top_month), hide_index=True)
            else:
                st.info("No sales this month.")
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
            
            submitted = st.form_submit_button("Add Item")
            if submitted:
                if name:
                    success, msg = add_item(name, category, maker, supplier, color, barcode, quantity, price, min_threshold)
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
                edit_id = int(item_row['id']) # Ensure int
                
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
                    
                    col_update, col_delete = st.columns([1, 1])
                    with col_update:
                        if st.form_submit_button("Update Item Details"):
                            success, msg = update_item_details(edit_id, new_name, new_category, new_maker, new_supplier, new_color, new_barcode, new_price, new_threshold)
                            if success:
                                st.success(f"Updated {new_name}: {msg}")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(msg)
                    
                    with col_delete:
                        if st.form_submit_button("🗑️ Delete Item", type="primary"):
                            success, msg = delete_item(edit_id)
                            if success:
                                st.success(msg)
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(msg)
        else:
            st.info("No items to edit.")

    # View Inventory
    st.subheader("Current Stock")
    if not df.empty:
        st.dataframe(style_dataframe(df), use_container_width=True, hide_index=True)
    else:
        st.info("Inventory is empty.")

elif page == "Transactions":
    st.header("🛒 Point of Sale (POS)")

    # 1. Search & Add to Cart
    st.subheader("Add Item to Cart")
    
    df = get_inventory_df()
    if df.empty:
        st.warning("No items in inventory.")
    else:
        # Create a display label for each item
        def format_item_label(row):
            parts = [row['name']]
            if 'barcode' in row and row['barcode']: parts.append(str(row['barcode']))
            if row['category']: parts.append(str(row['category']))
            return " | ".join(parts)

        item_map = {}
        for index, row in df.iterrows():
            label = format_item_label(row)
            item_map[label] = row
            
        col_search, col_qty = st.columns([3, 1])
        
        with col_search:
            selected_label = st.selectbox("Search Item", options=list(item_map.keys()), index=None, placeholder="Type to search or Scan Barcode...", key="pos_search")
            
        with col_qty:
            qty = st.number_input("Qty", min_value=1, value=1, key="pos_qty")
            
        col_add, col_note = st.columns([1, 3])
        with col_note:
            note = st.text_input("Note (Optional)", placeholder="Customer Name / ID", key="pos_note")
            
        with col_add:
            if st.button("Add to Cart", type="primary"):
                if selected_label:
                    row = item_map[selected_label]
                    
                    # check stock
                    if row['quantity'] < qty:
                        st.error(f"Not enough stock! (Available: {row['quantity']})")
                    else:
                        # Add to cart
                        item_data = {
                            "id": int(row['id']),
                            "name": row['name'],
                            "price": float(row['price']),
                            "qty": qty,
                            "note": note,
                            "max_qty": int(row['quantity'])
                        }
                        st.session_state["cart"].append(item_data)
                        st.success(f"Added {row['name']} to cart")
                else:
                    st.error("Please select an item first.")

    st.divider()

    # 2. View Cart & Checkout
    st.subheader("Shopping Cart")
    
    if st.session_state["cart"]:
        cart_df = pd.DataFrame(st.session_state["cart"])
        cart_df['Total'] = cart_df['price'] * cart_df['qty']
        
        # Display Cart Table (Custom HTML/Table for Actions is hard in pure Streamlit, using dataframe for display)
        # We will add a "Clear Cart" button for simplicity instead of per-row delete for this version, 
        # or use a Multiselect to remove items.
        
        st.dataframe(style_dataframe(cart_df[['name', 'qty', 'price', 'Total', 'note']]), use_container_width=True, hide_index=True)
        
        total_amount = cart_df['Total'].sum()
        st.markdown(f"### Total: ${total_amount:,.2f}")
        
        # Remove Item Logic
        item_to_remove = st.selectbox("Remove Item:", options=cart_df['name'].tolist(), index=None, placeholder="Select item to remove...")
        if st.button("Remove Selected Item"):
            if item_to_remove:
                st.session_state["cart"] = [item for item in st.session_state["cart"] if item['name'] != item_to_remove]
                st.rerun()
        
        st.divider()
        
        # Checkout Section
        col_chk_1, col_chk_2 = st.columns(2)
        
        with col_chk_1:
            auto_print = st.checkbox("Auto-Print Receipt", value=True)
            
        with col_chk_2:
            col_cash, col_card = st.columns(2)
            
            with col_cash:
                if st.button("💵 PAY CASH", type="primary", use_container_width=True):
                    success, receipt_id = process_batch_transaction(st.session_state["cart"], "SALE", "CASH")
                    
                    if success:
                        st.success("Cash Transaction Complete!")
                        
                        # Generate Receipt
                        receipt_html = generate_receipt_html(st.session_state["cart"], total_amount, receipt_id, auto_print)
                        
                        # Store in session state for reprint
                        st.session_state["last_receipt"] = receipt_html
                        
                        # Clear Cart
                        st.session_state["cart"] = []
                        st.rerun()
                    else:
                        st.error(f"Transaction Failed: {receipt_id}")

            with col_card:
                if st.button("💳 PAY CARD", type="secondary", use_container_width=True):
                    success, receipt_id = process_batch_transaction(st.session_state["cart"], "SALE", "CARD")
                    
                    if success:
                        st.success("Card Transaction Recorded!")
                        
                        # Generate Receipt
                        receipt_html = generate_receipt_html(st.session_state["cart"], total_amount, receipt_id, auto_print)
                        
                        # Store in session state for reprint
                        st.session_state["last_receipt"] = receipt_html
                        
                        # Clear Cart
                        st.session_state["cart"] = []
                        st.rerun()
                    else:
                        st.error(f"Transaction Failed: {receipt_id}")
                    
        if st.button("Empty Cart (Cancel)"):
             st.session_state["cart"] = []
             st.rerun()
             
    if "last_receipt" in st.session_state and st.session_state["last_receipt"]:
        st.divider()
        st.subheader("📄 Last Transaction Receipt")
        col_repr_1, col_repr_2 = st.columns([1, 4])
        
        with col_repr_1:
            # We can't trigger a browser print directly from a button click easily without re-rendering the HTML with auto-print
            # So we re-render the HTML components
            if st.button("🖨️ Reprint Receipt"):
                # Append auto-print script if not present (simple hack)
                if "window.print()" not in st.session_state["last_receipt"]:
                     st.session_state["last_receipt"] = st.session_state["last_receipt"].replace("</head>", "<script>window.onload = function() { window.print(); }</script></head>")
                st.rerun()

        with st.expander("View Receipt", expanded=True):
             st.components.v1.html(st.session_state["last_receipt"], height=600, scrolling=True)
            
    else:
        st.info("Cart is empty.")

elif page == "History":
    st.header("Transaction History")
    df = get_transactions_df(limit=200)
    if not df.empty:
        st.dataframe(style_dataframe(df), use_container_width=True, hide_index=True)
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