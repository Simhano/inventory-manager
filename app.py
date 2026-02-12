import streamlit as st
import pandas as pd
import time
from datetime import datetime
from database import init_connection, add_item, update_stock, get_inventory_df, get_transactions_df, get_top_selling_items, delete_item, update_item_details, get_setting, set_setting

# Page Config
st.set_page_config(page_title="Inventory Manager (Supabase)", layout="wide", page_icon="⚡")

# Initialize DB connection (cached)
try:
    init_connection()
except Exception as e:
    st.error(f"Failed to connect to database: {e}")


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

# --- Authentication ---

def check_global_password():
    """Checks for the 'Global Wall' password."""
    # Retrieve dynamic password from DB (default 0000)
    correct_password = get_setting("global_password", "0000")
    
    def password_entered():
        if st.session_state["global_password_input"] == correct_password:
            st.session_state["global_access_granted"] = True
            del st.session_state["global_password_input"]
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
        if st.session_state["admin_password_input"] == correct_password:
            st.session_state["admin_access_granted"] = True
            del st.session_state["admin_password_input"]
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
            st.dataframe(style_dataframe(low_stock[['name', 'quantity', 'min_threshold']]), hide_index=True)
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
            
            col_maker, col_color, col_barcode = st.columns(3)
            maker = col_maker.text_input("Maker/Brand")
            color = col_color.text_input("Color")
            barcode = col_barcode.text_input("Barcode")
            
            col3, col4, col5 = st.columns(3)
            quantity = col3.number_input("Initial Quantity", min_value=0, value=0)
            price = col4.number_input("Price", min_value=0.0, value=0.0, step=0.01)
            min_threshold = col5.number_input("Low Stock Threshold", min_value=1, value=5)
            
            submitted = st.form_submit_button("Add Item")
            if submitted:
                if name:
                    success, msg = add_item(name, category, maker, color, barcode, quantity, price, min_threshold)
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
                    
                    col_maker, col_color, col_barcode = st.columns(3)
                    curr_maker = item_row['maker'] if 'maker' in item_row and item_row['maker'] is not None else ""
                    curr_color = item_row['color'] if 'color' in item_row and item_row['color'] is not None else ""
                    curr_barcode = item_row['barcode'] if 'barcode' in item_row and item_row['barcode'] is not None else ""
                    
                    new_maker = col_maker.text_input("Maker/Brand", value=curr_maker)
                    new_color = col_color.text_input("Color", value=curr_color)
                    new_barcode = col_barcode.text_input("Barcode", value=curr_barcode)
                    
                    col3, col4 = st.columns(2)
                    new_price = col3.number_input("Price", min_value=0.0, value=float(item_row['price']), step=0.01)
                    new_threshold = col4.number_input("Low Stock Threshold", min_value=1, value=int(item_row['min_threshold']))
                    
                    col_update, col_delete = st.columns([1, 1])
                    with col_update:
                        if st.form_submit_button("Update Item Details"):
                            success, msg = update_item_details(edit_id, new_name, new_category, new_maker, new_color, new_barcode, new_price, new_threshold)
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
    st.header("Record Transaction")
    
    # Use full dataframe to get all properties for search
    df = get_inventory_df()
    
    if df.empty:
        st.warning("No items to transact.")
    else:
        # Create a display label for each item that includes search terms
        def format_item_label(row):
            parts = [row['name']]
            if 'barcode' in row and row['barcode']: parts.append(str(row['barcode']))
            if row['category']: parts.append(str(row['category']))
            return " | ".join(parts)

        # Map the formatted label back to the data we need
        item_map = {}
        for index, row in df.iterrows():
            label = format_item_label(row)
            item_map[label] = row
            
        selected_label = st.selectbox("Search & Select Item (Name | Barcode | Category)", options=list(item_map.keys()), index=None, placeholder="Type to search or Scan Barcode...")
        
        if selected_label:
            row = item_map[selected_label]
            item_id = int(row['id'])
            current_qty = row['quantity']
            item_price = row['price']
            item_name = row['name']
            
            st.info(f"Current Stock: **{current_qty}** | Price: **${item_price:.2f}**")
            
            tab1, tab2 = st.tabs(["Sell", "Restock"])
            
            with tab1:
                with st.form("sell_form"):
                    sell_qty = st.number_input("Quantity to Sell", min_value=1, value=1)
                    sell_note = st.text_input("Note (Optional)", placeholder="e.g. Customer ID")
                    
                    if st.form_submit_button("Confirm Sale"):
                        # Negative quantity for sale
                        success, msg = update_stock(item_id, item_name, -sell_qty, 'SALE', sell_note)
                        if success:
                            st.success(f"Sold {sell_qty} of {item_name}!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

            with tab2:
                with st.form("restock_form"):
                    restock_qty = st.number_input("Quantity to Restock", min_value=1, value=10)
                    restock_note = st.text_input("Note (Optional)", placeholder="e.g. Supplier Invoice #")
                    
                    if st.form_submit_button("Confirm Restock"):
                        # Positive quantity for restock
                        success, msg = update_stock(item_id, item_name, restock_qty, 'RESTOCK', restock_note)
                        if success:
                            st.success(f"Restocked {restock_qty} of {item_name}!")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)

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
